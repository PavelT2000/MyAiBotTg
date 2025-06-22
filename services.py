import logging
import json
from functools import lru_cache
import openai
from typing import Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from amplitude import Amplitude, BaseEvent
from database import save_value_to_db, AsyncSession
import httpx

logger = logging.getLogger(__name__)

# Создаём ThreadPoolExecutor для Amplitude
executor = ThreadPoolExecutor(max_workers=1)

class OpenAIService:
    def __init__(self, api_key: str, amplitude_api_key: str):
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            http_client=httpx.AsyncClient()
        )
        self.amplitude = Amplitude(amplitude_api_key)
        self.vector_store_id: Optional[str] = None
        self.assistant_id: Optional[str] = None

    async def create_assistant(self) -> str:
        logger.info("create assistant used")
        try:
            assistant = await self.client.beta.assistants.create(
                name="Voice and Values Assistant",
                instructions="""
                Вы полезный голосовой ассистент. Ваши задачи:
                1. Помогать пользователю определять ключевые ценности через диалог.
                   - Начните с вопроса: 'Что для вас наиболее важное в жизни? Назови одну ценность (например, семья, свобода, успех).'
                   - Если пользователь называет ценность (например, 'добавить к ценностям [ценность]'), вызывайте save_value.
                   - Если ответ неясен, задавайте уточняющие вопросы, например: 'Пожалуйста, назовите конкретную ценность.'
                   - Не вызывайте save_value для невалидных ценностей.
                2. Отвечать на вопросы о тревожности, используя file_search с документом в vector_store.
                   - Если вопрос связан с тревожностью, предоставьте точный ответ на основе документа.
                   - Включите ссылку на источник (file_citation) в ответе.
                3. Для голосовых сообщений преобразуйте текст в ответы с помощью TTS (модель tts-1, голос alloy).
                Всегда отвечайте на русском языке, будьте дружелюбны и понятны.
                """,
                model="gpt-4o",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "save_value",
                            "description": "Сохранить ценность пользователя в базе данных",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "value": {
                                        "type": "string",
                                        "description": "Ценность пользователя (например, 'семья', 'свобода', 'успех')"
                                    }
                                },
                                "required": ["value"]
                            }
                        }
                    },
                    {"type": "file_search"}
                ]
            )
            logger.info(f"Создан новый ассистент с ID: {assistant.id}")
            print(f"!!! ВАЖНО: Добавьте в .env следующий ASSISTANT_ID: {assistant.id}")
            self.assistant_id = assistant.id
            return assistant.id
        except Exception as e:
            logger.error(f"Ошибка при создании ассистента: {e}")
            raise

    async def verify_or_create_assistant(self, assistant_id: str) -> str:
        logger.info("verify or create assistant handler used")
        try:
            assistant = await self.client.beta.assistants.retrieve(assistant_id)
            logger.info(f"Ассистент найден: {assistant.name}")
            self.assistant_id = assistant_id
            return assistant_id
        except openai.NotFoundError:
            logger.warning(f"Ассистент с ID {assistant_id} не найден. Создаём новый...")
            return await self.create_assistant()
        except Exception as e:
            logger.error(f"Ошибка при проверке ассистента: {e}")
            raise

    async def update_assistant_with_file_search(self, assistant_id: str) -> None:
        """Обновляет ассистента с file_search и vector_store_id."""
        if not self.vector_store_id:
            raise ValueError("Vector store ID is not set.")
        try:
            logger.debug(f"Updating assistant {assistant_id} with vector store {self.vector_store_id}")
            assistant = await self.client.beta.assistants.update(
                assistant_id=assistant_id,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "save_value",
                            "description": "Сохранить ценность",
                            "parameters": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"]
                            }
                        }
                    },
                    {"type": "file_search"}
                ],
                tool_resources={"file_search": {"vector_store_ids": [self.vector_store_id]}}
            )
            self.assistant_id = assistant.id
            logger.info(f"Assistant {assistant.id} updated with vector store {self.vector_store_id}")
        except Exception as e:
            logger.error(f"Error updating assistant: {e}")
            raise

    @lru_cache(maxsize=100)
    async def validate_value(self, value: str) -> bool:
        logger.info("validate value used")
        try:
            if not value or not isinstance(value, str) or len(value.strip()) == 0:
                return False
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Вы валидатор ценностей. Верните 'true' для корректных ценностей (например, 'семья', 'свобода', 'успех'), и 'false' для некорректных. Ответьте только 'true' или 'false'."},
                    {"role": "user", "content": value}
                ],
                max_tokens=1
            )
            is_valid = response.choices[0].message.content.strip().lower() == "true"
            logger.info(f"Валидация ценности '{value}': {is_valid}")
            return is_valid
        except Exception as e:
            logger.error(f"Ошибка валидации ценности: {e}")
            return False

    async def process_thread(self, thread_id: str, assistant_id: str) -> Tuple[Optional[str], Optional[str]]:
        run = await self.client.beta.threads.runs.create_and_poll(thread_id=thread_id, assistant_id=assistant_id)
        if run.status == "requires_action" and run.required_action and run.required_action.submit_tool_outputs:
            return await self.handle_tool_outputs(thread_id, run)
        elif run.status != "completed":
            raise Exception(f"Run завершился с ошибкой, статус: {run.status}")
        messages = await self.client.beta.threads.messages.list(thread_id=thread_id)
        for msg in messages.data:
            if msg.role == "assistant" and msg.content[0].type == "text":
                response = msg.content[0].text.value
                citations = []
                for annotation in msg.content[0].text.annotations:
                    if annotation.type == "file_citation":
                        file_id = annotation.file_citation.file_id
                        file_name = await self.get_file_name(file_id)
                        citations.append(f"[Источник: {file_name}]")
                if citations:
                    response += "\n" + "\n".join(citations)
                return response, None
        return None, None

    async def get_file_name(self, file_id: str) -> str:
        """Получает имя файла по его ID."""
        try:
            file = await self.client.files.retrieve(file_id)
            return file.filename
        except Exception as e:
            logger.error(f"Ошибка при получении имени файла {file_id}: {e}")
            return "Unknown File"

    async def handle_tool_outputs(self, thread_id: str, run) -> Tuple[Optional[str], Optional[str]]:
        logger.info(f"Статус requires_action, tool_calls: {run.required_action.submit_tool_outputs.tool_calls}")
        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
            if tool_call.function.name == "save_value":
                logger.info(f"Вызов save_value с аргументами: {tool_call.function.arguments}")
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    value = arguments.get("value")
                    if not value or not isinstance(value, str) or not value.strip():
                        logger.warning(f"Некорректное значение value: {value}")
                        return None, "Ценность не определена. Пожалуйста, уточните."
                    logger.info(f"Извлечённая ценность: {value}")
                    return value, None
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка декодирования аргументов: {e}")
                    return None, "Ошибка обработки. Попробуйте снова."
                except Exception as e:
                    logger.error(f"Ошибка при обработке tool_call: {e}", exc_info=True)
                    return None, "Ошибка обработки. Попробуйте снова."
        return None, None

    async def process_tool_call(self, thread_id: str, run, session: AsyncSession, user_id: int) -> Tuple[str, bool]:
        logger.info(f"Обработка tool_call, thread_id: {thread_id}")
        value, error = await self.handle_tool_outputs(thread_id, run)
        if error:
            return error, False
        if value:
            success, response = await save_value_to_db(session, user_id, value)
            await self.submit_tool_output(thread_id, run.id, run.required_action.submit_tool_outputs.tool_calls[0].id, success, response)
            return response, success
        return "Ошибка обработки. Попробуйте снова.", False

    async def submit_tool_output(self, thread_id: str, run_id: str, tool_call_id: str, success: bool, response: str):
        await self.client.beta.threads.runs.submit_tool_outputs_and_poll(
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=[{"tool_call_id": tool_call_id, "output": json.dumps({"success": success, "message": response})}]
        )

    async def analyze_mood(self, image_url: str, user_id: int) -> str:
        logger.info(f"Analytics mood for user_id: {user_id}")
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "Вы эксперт по анализу эмоций. Определите настроение человека на фото (например, 'радость', 'грусть', 'злость', 'спокойствие') и верните только название эмоции."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ]
                    }
                ],
                max_tokens=10
            )
            mood = response.choices[0].message.content.strip()
            logger.info(f"Определено настроение: {mood}")
            executor.submit(
                self.amplitude.track,
                BaseEvent(
                    event_type="mood_analyzed",
                    user_id=str(user_id),
                    event_properties={"mood": mood}
                )
            )
            return mood
        except Exception as e:
            logger.error(f"Ошибка при анализе настроения: {e}")
            return "Ошибка при анализе настроения."

    def send_amplitude_event(self, event_type: str, user_id: str, event_properties: dict = None):
        logger.info(f"Отправка события Amplitude: {event_type} для user_id: {user_id}")
        executor.submit(
            self.amplitude.track,
            BaseEvent(
                event_type=event_type,
                user_id=user_id,
                event_properties=event_properties or {}
            )
        )
import logging
import json
from functools import lru_cache
import openai
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def create_assistant(self) -> str:
        logger.info("create assistant used")
        try:
            assistant = await self.client.beta.assistants.create(
                name="Voice and Values Assistant",
                instructions="""
                Вы полезный голосовой ассистент. Ваша задача — помогать пользователю определять его ключевые ценности через диалог.
                Начните с вопроса: 'Что для вас наиболее важно в жизни? Назови одну ценность (например, семья, свобода, успех).'
                Если пользователь говорит 'добавить к ценностям [ценность]' или называет новую ценность, вызывайте save_value с этой ценностью.
                Если ответ неясен, продолжайте задавать вопросы, такие как: 'Пожалуйста, назовите конкретную ценность.'
                Не вызывайте save_value, если ответ не является валидной ценностью.
                Для голосовых сообщений преобразуйте текст в ответы, используя TTS.
                """,
                model="gpt-4o",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "save_value",
                            "description": "Сохранить определённую ценность пользователя в базе данных",
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
                    }
                ]
            )
            logger.info(f"Создан новый ассистент с ID: {assistant.id}")
            print(f"!!! ВАЖНО: Добавьте в .env следующий ASSISTANT_ID: {assistant.id}")
            return assistant.id
        except Exception as e:
            logger.error(f"Ошибка при создании ассистента: {e}")
            raise

    async def verify_or_create_assistant(self, assistant_id: str) -> str:
        logger.info("verify or create assistant handler used")
        try:
            await self.client.beta.assistants.retrieve(assistant_id)
            logger.info(f"Ассистент найден: Voice and Values Assistant")
            return assistant_id
        except openai.NotFoundError:
            logger.warning(f"Ассистент с ID {assistant_id} не найден. Создаём новый...")
            return await self.create_assistant()
        except Exception as e:
            logger.error(f"Ошибка при проверке ассистента: {e}")
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
                    {"role": "system", "content": "Вы валидатор ценностей. Верните 'true' для корректных ценностей (например, 'семья', 'свобода', 'успех'), и 'false' для некорректных (пустые, бессмысленные или бред). Ответьте только 'true' или 'false'."},
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
                return msg.content[0].text.value, None
        return None, None

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

    async def submit_tool_output(self, thread_id: str, run_id: str, tool_call_id: str, success: bool, response: str):
        await self.client.beta.threads.runs.submit_tool_outputs_and_poll(
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=[{"tool_call_id": tool_call_id, "output": json.dumps({"success": success, "message": response})}]
        )

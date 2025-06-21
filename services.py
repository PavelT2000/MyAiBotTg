import logging
import os
import asyncio
import base64
from typing import Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self, api_key: str, assistant_id: str):
        """Инициализирует сервис OpenAI с асинхронным клиентом."""
        logger.debug("Initializing OpenAIService with AsyncOpenAI client")
        self.client = AsyncOpenAI(api_key=api_key)
        self.assistant_id = assistant_id
        self.vector_store_id: Optional[str] = None

    async def create_vector_store(self, file_path: str) -> str:
        """Создаёт векторное хранилище для файла и возвращает его ID."""
        try:
            logger.debug(f"Creating vector store for file: {file_path}")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File {file_path} not found")
            with open(file_path, "rb") as file:
                vector_store = await self.client.beta.vector_stores.create(
                    name="Anxiety Document Store",
                    file_streams=[file]
                )
            self.vector_store_id = vector_store.id
            logger.info(f"Vector store created with ID: {vector_store.id}")
            return vector_store.id
        except AttributeError as e:
            logger.error(f"AttributeError in create_vector_store: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating vector store: {e}")
            raise

    async def update_assistant(self) -> None:
        """Обновляет ассистента с file_search и vector_store_id."""
        if not self.vector_store_id:
            raise ValueError("Vector store ID is not set. Call create_vector_store first.")
        try:
            logger.debug(f"Updating assistant {self.assistant_id} with vector store {self.vector_store_id}")
            assistant = await self.client.beta.assistants.update(
                assistant_id=self.assistant_id,
                tools=[{"type": "file_search"}],
                tool_resources={"file_search": {"vector_store_ids": [self.vector_store_id]}}
            )
            logger.info(f"Assistant {assistant.id} updated with vector store {self.vector_store_id}")
        except Exception as e:
            logger.error(f"Error updating assistant: {e}")
            raise

    async def process_message(self, thread_id: str, message: str) -> str:
        """Обрабатывает текстовое сообщение и возвращает ответ ассистента."""
        try:
            logger.debug(f"Processing message in thread {thread_id}: {message}")
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )
            run = await self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.assistant_id
            )
            # Ожидание завершения run
            while True:
                run_status = await self.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                if run_status.status in ["completed", "failed"]:
                    break
                await asyncio.sleep(1)
            if run_status.status == "failed":
                raise RuntimeError(f"Run failed: {run_status.last_error}")
            
            # Получение сообщений
            messages = await self.client.beta.threads.messages.list(thread_id=thread_id)
            response = ""
            for msg in messages.data:
                if msg.role == "assistant":
                    for content in msg.content:
                        if content.type == "text":
                            response += content.text.value
                            # Обработка аннотаций (file_citations)
                            for annotation in content.text.annotations:
                                if annotation.type == "file_citation":
                                    response += "\n[Источник: Anxiety.docx]"
                    break
            logger.info(f"Message processed, response: {response}")
            return response
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return "Ошибка при обработке сообщения."

    async def transcribe_audio(self, audio_path: str) -> str:
        """Транскрибирует аудиофайл с помощью Whisper."""
        try:
            logger.debug(f"Transcribing audio: {audio_path}")
            with open(audio_path, "rb") as audio_file:
                transcription = await self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
            logger.info(f"Audio transcribed: {transcription.text}")
            return transcription.text
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return "Ошибка при транскрибации аудио."

    async def process_image(self, image_path: str) -> str:
        """Обрабатывает изображение для анализа настроения."""
        try:
            logger.debug(f"Processing image: {image_path}")
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")
                response = await self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Опиши настроение на этом изображении."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                            ],
                        }
                    ],
                    max_tokens=300,
                )
            mood = response.choices[0].message.content
            logger.info(f"Image processed, mood: {mood}")
            return mood
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            return "Ошибка при анализе изображения."

async def save_value_to_db(session, user_id: int, value: str) -> None:
    """Сохраняет ценность пользователя в базу данных."""
    from database import save_value_to_db as db_save_value
    try:
        await db_save_value(session, user_id, value)
    except Exception as e:
        logger.error(f"Error saving value to database: {e}")
        raise
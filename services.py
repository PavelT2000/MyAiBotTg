import logging
from openai import AsyncOpenAI
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

async def create_vector_store(client: AsyncOpenAI, file_path: str) -> str:
    """Создаёт векторное хранилище для файла и возвращает его ID."""
    try:
        logger.debug(f"Creating vector store for file: {file_path}")
        with open(file_path, "rb") as file:
            vector_store = await client.beta.vector_stores.create(
                name="Anxiety Document Store",
                file_streams=[file]
            )
        logger.info(f"Vector store created with ID: {vector_store.id}")
        return vector_store.id
    except Exception as e:
        logger.error(f"Error creating vector store: {e}")
        raise

async def update_assistant(client: AsyncOpenAI, assistant_id: str, vector_store_id: str) -> None:
    """Обновляет ассистента с file_search и vector_store_id."""
    try:
        logger.debug(f"Updating assistant {assistant_id} with vector store {vector_store_id}")
        assistant = await client.beta.assistants.update(
            assistant_id=assistant_id,
            tools=[{"type": "file_search"}],
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}
        )
        logger.info(f"Assistant {assistant.id} updated with vector store {vector_store_id}")
    except Exception as e:
        logger.error(f"Error updating assistant: {e}")
        raise

async def save_value_to_db(session, user_id: int, value: str) -> None:
    """Сохраняет ценность пользователя в базу данных."""
    from database import save_value_to_db  # Отложенный импорт для избежания циклических зависимостей
    try:
        await save_value_to_db(session, user_id, value)
    except Exception as e:
        logger.error(f"Error saving value to database: {e}")
        raise

async def process_image(client: AsyncOpenAI, image_path: str) -> str:
    """Обрабатывает изображение для анализа настроения."""
    try:
        logger.debug(f"Processing image: {image_path}")
        with open(image_path, "rb") as image_file:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Опиши настроение на этом изображении."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_file.read().hex()}"}},
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

async def transcribe_audio(client: AsyncOpenAI, audio_path: str) -> str:
    """Транскрибирует аудиофайл с помощью Whisper."""
    try:
        logger.debug(f"Transcribing audio: {audio_path}")
        with open(audio_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        logger.info(f"Audio transcribed: {transcription.text}")
        return transcription.text
    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        return "Ошибка при транскрибации аудио."
import logging
import asyncio
import os
import requests
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
from database import init_db, Base
from services import OpenAIService
from handlers import register_handlers
import openai
import httpx

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_upload_file(file_path: str, api_key: str) -> str:
    """Загружает файл в OpenAI через /files."""
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found")
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError(f"File {file_path} is empty")
        logger.debug(f"File {file_path} size: {file_size} bytes")
        
        url = "https://api.openai.com/v1/files"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "assistants=v2"
        }
        with open(file_path, "rb") as file:
            files = {
                "file": (os.path.basename(file_path), file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            }
            data = {"purpose": "assistants"}
            response = requests.post(url, headers=headers, files=files, data=data)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error uploading file: {e}, Response body: {response.text}")
                raise
            file_data = response.json()
        file_id = file_data["id"]
        logger.info(f"File uploaded with ID: {file_id}")
        return file_id
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise

def sync_create_vector_store(file_id: str, api_key: str) -> str:
    """Создаёт векторное хранилище с file_id через /vector_stores."""
    try:
        url = "https://api.openai.com/v1/vector_stores"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }
        data = {
            "name": "Anxiety Document Store",
            "file_ids": [file_id]
        }
        response = requests.post(url, headers=headers, json=data)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error creating vector store: {e}, Response body: {response.text}")
            raise
        vector_store = response.json()
        vector_store_id = vector_store["id"]
        logger.info(f"Vector store created with ID: {vector_store_id}")
        return vector_store_id
    except Exception as e:
        logger.error(f"Error creating vector store: {e}")
        raise

# Инициализация RedisStorage
async def init_redis(redis_url: str) -> Redis:
    """Инициализирует и проверяет подключение к Redis."""
    try:
        if not redis_url:
            raise ValueError("REDIS_URL is not set in environment variables")
        logger.info(f"Attempting to connect to Redis with URL: {redis_url[:15]}...")  # Частичное логирование
        redis = Redis.from_url(redis_url, decode_responses=True)
        await redis.ping()
        logger.info("Successfully connected to Redis")
        return redis
    except Exception as e:
        logger.error(f"Failed to connect to Redis with URL {redis_url[:15]}...: {e}")
        raise

# Инициализация бота
try:
    redis = asyncio.run(init_redis(config.REDIS_URL))
except Exception as e:
    logger.critical(f"Cannot start bot: Redis initialization failed: {e}")
    raise
storage = RedisStorage(redis=redis)
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Инициализация базы данных
engine, async_session = init_db(config.DATABASE_URL)

# Инициализация сервиса OpenAI
openai_service = OpenAIService(config.OPENAI_API_KEY, config.AMPLITUDE_API_KEY)

async def main():
    try:
        # Создание таблиц базы данных
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Проверка или создание ассистента
        assistant_id = await openai_service.verify_or_create_assistant(config.ASSISTANT_ID)
        if assistant_id != config.ASSISTANT_ID:
            logger.info(f"Обновлён ASSISTANT_ID с {config.ASSISTANT_ID} на {assistant_id}")

        # Загрузка файла и создание vector_store
        file_id = sync_upload_file("Anxiety.docx", config.OPENAI_API_KEY)
        vector_store_id = sync_create_vector_store(file_id, config.OPENAI_API_KEY)
        openai_service.vector_store_id = vector_store_id
        await openai_service.update_assistant_with_file_search(assistant_id)

        # Регистрация обработчиков
        register_handlers(dp, bot, openai_service, assistant_id, async_session)

        # Запуск бота
        logger.info("Starting bot polling")
        await dp.start_polling(bot, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise
    finally:
        await redis.aclose()

if __name__ == "__main__":
    asyncio.run(main())
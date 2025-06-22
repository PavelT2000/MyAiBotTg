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

def sync_create_vector_store(file_path: str, api_key: str) -> str:
    """Создаёт векторное хранилище через HTTP-запрос к OpenAI API."""
    try:
        logger.info(f"OpenAI library version: {openai.__version__}, httpx version: {httpx.__version__}")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found")
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError(f"File {file_path} is empty")
        logger.debug(f"File {file_path} size: {file_size} bytes")
        
        url = "https://api.openai.com/v1/vector_stores"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "assistants=v2"
        }
        with open(file_path, "rb") as file:
            files = {
                "file": (os.path.basename(file_path), file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            }
            data = {"name": "Anxiety Document Store"}
            response = requests.post(url, headers=headers, files=files, data=data)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error: {e}, Response body: {response.text}")
                raise
            vector_store = response.json()
        vector_store_id = vector_store["id"]
        logger.info(f"Vector store created with ID: {vector_store_id}")
        return vector_store_id
    except Exception as e:
        logger.error(f"Error creating vector store: {e}")
        raise

# Инициализация RedisStorage
redis = Redis.from_url(config.REDIS_URL)
storage = RedisStorage(redis=redis)

# Инициализация бота
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

        # Создание vector_store
        vector_store_id = sync_create_vector_store("Anxiety.docx", config.OPENAI_API_KEY)
        openai_service.vector_store_id = vector_store_id
        await openai_service.update_assistant_with_file_search()

        # Регистрация обработчиков
        register_handlers(dp, bot, openai_service, assistant_id, async_session)

        # Запуск бота
        logger.info("Starting bot polling")
        await dp.start_polling(bot, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise
    finally:
        await redis.close()

if __name__ == "__main__":
    asyncio.run(main())
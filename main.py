import logging
import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from database import create_async_session
from services import OpenAIService
from handlers import router
from config import Config
from openai import OpenAI
import openai
import inspect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_create_vector_store(file_path: str, api_key: str) -> str:
    """Создаёт векторное хранилище с использованием синхронного клиента OpenAI."""
    try:
        logger.info(f"OpenAI library version: {openai.__version__}")
        client = OpenAI(api_key=api_key)
        logger.debug(f"Client beta attributes: {dir(client.beta)}")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found")
        with open(file_path, "rb") as file:
            vector_store = client.beta.vector_stores.create(
                name="Anxiety Document Store",
                file_streams=[file]
            )
        logger.info(f"Vector store created with ID: {vector_store.id}")
        return vector_store.id
    except AttributeError as e:
        logger.error(f"AttributeError in sync_create_vector_store: {e}")
        raise
    except Exception as e:
        logger.error(f"Error creating vector store with sync client: {e}")
        raise

async def main():
    try:
        config = Config()
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        storage = RedisStorage(redis=Redis.from_url(config.REDIS_URL))
        dp = Dispatcher(bot=bot, storage=storage)
        dp.include_router(router)

        async_session = create_async_session(config.DATABASE_URL)
        openai_service = OpenAIService(api_key=config.OPENAI_API_KEY, assistant_id=config.ASSISTANT_ID)

        # Создание vector_store с помощью синхронного клиента
        logger.debug("Initializing vector store and assistant")
        vector_store_id = sync_create_vector_store("Anxiety.docx", config.OPENAI_API_KEY)
        openai_service.vector_store_id = vector_store_id
        await openai_service.update_assistant()

        # Передача зависимостей в handlers
        dp["async_session"] = async_session
        dp["openai_service"] = openai_service

        logger.info("Starting bot polling")
        await dp.start_polling()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
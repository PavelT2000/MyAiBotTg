import logging
import asyncio
import os
import requests
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from database import create_async_session
from services import OpenAIService
from handlers import router
from config import Config
import openai
import httpx

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
        logger.error(f"Error creating vector store with HTTP request: {e}")
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

        # Создание vector_store через HTTP-запрос
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
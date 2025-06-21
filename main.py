import logging
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from database import create_async_session
from services import OpenAIService
from handlers import router
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    try:
        config = Config()
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        storage = RedisStorage(redis=Redis.from_url(config.REDIS_URL))
        dp = Dispatcher(bot=bot, storage=storage)
        dp.include_router(router)

        async_session = create_async_session(config.DATABASE_URL)
        openai_service = OpenAIService(api_key=config.OPENAI_API_KEY, assistant_id=config.ASSISTANT_ID)

        # Инициализация vector_store и ассистента
        logger.debug("Initializing vector store and assistant")
        vector_store_id = await openai_service.create_vector_store("Anxiety.docx")
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
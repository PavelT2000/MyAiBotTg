import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from config import config
from database import create_async_session
from services import OpenAIService
from handlers import register_handlers

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    redis = Redis.from_url(config.REDIS_URL)
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    openai_service = OpenAIService(config.OPENAI_API_KEY, config.AMPLITUDE_API_KEY)
    async_session = create_async_session(config.DATABASE_URL)

    # Создание vector_store и обновление ассистента
    try:
        vector_store_id = await openai_service.create_vector_store("Anxiety.docx")
        await openai_service.update_assistant(config.ASSISTANT_ID, vector_store_id)
    except Exception as e:
        logger.error(f"Failed to initialize vector store or assistant: {e}")
        return

    register_handlers(dp, bot, openai_service, config.ASSISTANT_ID, async_session)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await redis.close()

if __name__ == "__main__":
    asyncio.run(main())
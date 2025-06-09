import logging
import asyncio

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from database import init_db, Base
from services import OpenAIService
from handlers import register_handlers

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
engine, async_session = init_db(config.DATABASE_URL)

# Инициализация сервиса OpenAI
openai_service = OpenAIService(config.OPENAI_API_KEY, config.AMPLITUDE_API_KEY)

async def main():
    # Создание таблиц базы данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Проверка или создание ассистента
    assistant_id = await openai_service.verify_or_create_assistant(config.ASSISTANT_ID)
    if assistant_id != config.ASSISTANT_ID:
        logger.info(f"Обновлён ASSISTANT_ID с {config.ASSISTANT_ID} на {assistant_id}")

    # Регистрация обработчиков
    register_handlers(dp, bot, openai_service, assistant_id, async_session)  # Добавлен async_session

    # Запуск бота
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
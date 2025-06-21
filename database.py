import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
from models import Base, UserValue

logger = logging.getLogger(__name__)

def create_async_engine(database_url: str):
    """Создаёт асинхронный движок SQLAlchemy."""
    try:
        engine = create_async_engine(
            database_url,
            pool_pre_ping=True
        )
        logger.info(f"Async engine created for database: {database_url}")
        return engine
    except Exception as e:
        logger.error(f"Error creating async engine: {e}")
        raise

def create_async_session(database_url: str) -> sessionmaker:
    """Создаёт фабрику асинхронных сессий SQLAlchemy."""
    engine = create_async_engine(database_url)
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    logger.info("Async session factory created")
    return async_session

async def get_user_values(session: AsyncSession, user_id: int) -> list[str]:
    """Получает список ценностей пользователя из базы данных."""
    try:
        result = await session.execute(
            select(UserValue.value).where(UserValue.user_id == user_id)
        )
        values = [row[0] for row in result.all()]
        return values
    except Exception as e:
        logger.error(f"Error retrieving values for user {user_id}: {e}")
        raise

async def save_value_to_db(session: AsyncSession, user_id: int, value: str):
    """Сохраняет ценность пользователя в базу данных."""
    try:
        new_value = UserValue(user_id=user_id, value=value)
        session.add(new_value)
        await session.commit()
        logger.info(f"Value '{value}' saved for user {user_id}")
    except Exception as e:
        logger.error(f"Error saving value for user {user_id}: {e}")
        await session.rollback()
        raise
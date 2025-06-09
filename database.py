from sqlalchemy import Column, BigInteger, String, DateTime, select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from datetime import datetime
from models import UserValue

Base = declarative_base()

# Инициализация движка и сессии
def init_db(database_url: str):
    engine = create_async_engine(
        database_url,
        echo=True,
        pool_pre_ping=True,  # Добавлено
        connect_args={"server_settings": {"application_name": "voice_values_bot"}}
    )
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, async_session

async def save_value_to_db(session: AsyncSession, user_id: int, value: str) -> tuple[bool, str]:
    try:
        new_value = UserValue(user_id=user_id, value=value)
        session.add(new_value)
        await session.commit()
        return True, "Ценность успешно сохранена!"
    except Exception as e:
        await session.rollback()
        return False, f"Ошибка при сохранении ценности: {e}"

async def get_user_values(session: AsyncSession, user_id: int) -> list[str]:
    try:
        result = await session.execute(
            select(UserValue.value).where(UserValue.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]
    except Exception as e:
        raise Exception(f"Ошибка при извлечении ценностей: {e}")
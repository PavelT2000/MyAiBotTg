from sqlalchemy import Column, BigInteger, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from datetime import datetime

Base = declarative_base()

class UserValue(Base):
    __tablename__ = "user_values"
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    value = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Инициализация движка и сессии
def init_db(database_url: str):
    engine = create_async_engine(database_url, echo=True, pool_pre_ping=True, connect_args={"server_settings": {"application_name": "voice_values_bot"}})
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
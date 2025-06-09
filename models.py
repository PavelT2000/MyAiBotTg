from sqlalchemy import Column, BigInteger, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class UserValue(Base):
    __tablename__ = "user_values"
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    value = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
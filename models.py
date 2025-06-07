from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import mapped_column
from datetime import datetime

Base = declarative_base()

class UserValue(Base):
    __tablename__ = "user_values"
    
    id = mapped_column(Integer, primary_key=True)
    user_id = mapped_column(Integer, nullable=False)
    value = mapped_column(String(255), nullable=False)
    created_at = mapped_column(DateTime, default=datetime.utcnow)
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ASSISTANT_ID = os.getenv("ASSISTANT_ID")
    DATABASE_URL = os.getenv("DATABASE_URL")
    AMPLITUDE_API_KEY = os.getenv("AMPLITUDE_API_KEY")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

config = Config()
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str
    TELEGRAM_BOT_TOKEN: str
    ASSISTANT_ID: str
    DATABASE_URL: str
    AMPLITUDE_API_KEY: str  # Новый ключ для Amplitude
    
    class Config:
        env_file = ".env"

config = Settings()
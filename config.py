from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str
    TELEGRAM_BOT_TOKEN: str
    ASSISTANT_ID: str
    
    class Config:
        env_file = ".env"

config = Settings()
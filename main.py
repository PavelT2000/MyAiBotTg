import os
import logging
import asyncio
from io import BytesIO
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from pydantic_settings import BaseSettings

import openai

# Конфигурация через Pydantic (строго по ТЗ)
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    TELEGRAM_BOT_TOKEN: str
    ASSISTANT_ID: str
    
    class Config:
        env_file = ".env"

config = Settings()

# Инициализация клиента OpenAI (асинхронный, как требуется)
client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# Инициализация бота
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Клавиатура
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Помощь")
    builder.button(text="О боте")
    return builder.as_markup(resize_keyboard=True)

# Обработчики сообщений
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "Привет! Отправь голосовое сообщение, и я отвечу голосом!",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text)
async def text_handler(message: Message):
    if message.text.lower() == "помощь":
        await message.answer("Просто отправь голосовое сообщение с вопросом")
    elif message.text.lower() == "о боте":
        await message.answer("Я голосовой ассистент на OpenAI API")
    else:
        await message.answer("Используй голосовые сообщения")

@dp.message(F.voice)
async def voice_handler(message: Message):
    try:
        # 1. Конвертация голоса в текст (Whisper API)
        voice_file = await bot.get_file(message.voice.file_id)
        voice_data = await bot.download_file(voice_file.file_path)
        
        transcript = await client.audio.transcriptions.create(
            file=("voice.ogg", BytesIO(voice_data.read()), "audio/ogg"),
            model="whisper-1"
        )
        user_question = transcript.text
        await message.answer(f"🎤 Ваш вопрос: {user_question}")

        # 2. Получение ответа через Assistant API
        thread = await client.beta.threads.create()
        await client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_question
        )
        
        run = await client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=config.ASSISTANT_ID
        )
        
        while True:
            run_status = await client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            if run_status.status == "completed":
                break
            await asyncio.sleep(1)
        
        messages = await client.beta.threads.messages.list(thread_id=thread.id)
        assistant_response = next(
            m.content[0].text.value 
            for m in messages.data 
            if m.role == "assistant"
        )

        # 3. Озвучка ответа (TTS API)
        speech = await client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=assistant_response
        )
        
        await message.answer_voice(
            types.BufferedInputFile(
                (await speech.aread()),
                filename="response.mp3"
            )
        )
        await message.answer(f"🤖 Ответ: {assistant_response}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.answer("Ошибка обработки запроса")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
import os
import logging
import asyncio
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder

import openai
from config import config

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Настройка OpenAI клиента
client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# Клавиатура с основными командами
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Помощь")
    builder.button(text="О боте")
    return builder.as_markup(resize_keyboard=True)

# Обработчик команды /start
@dp.message(Command("start"))
async def start_handler(message: Message):
    welcome_text = (
        "Привет! Я голосовой ассистент. Отправь мне голосовое сообщение, "
        "и я постараюсь на него ответить!"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

# Обработчик текстовых сообщений (только текст)
@dp.message(F.text)
async def text_handler(message: Message):
    text = message.text.lower()
    if text == "помощь":
        help_text = (
            "Просто отправь мне голосовое сообщение с вопросом, "
            "и я постараюсь на него ответить!"
        )
        await message.answer(help_text)
    elif text == "о боте":
        about_text = (
            "Я - голосовой ассистент на базе OpenAI.\n"
            "Могу отвечать на вопросы и озвучивать ответы."
        )
        await message.answer(about_text)
    else:
        await message.answer("Пожалуйста, используйте голосовые сообщения для вопросов.")

# Обработчик голосовых сообщений
@dp.message(F.voice)
async def voice_handler(message: Message):
    try:
        # Скачиваем голосовое сообщение
        voice_file = await bot.get_file(message.voice.file_id)
        voice_data = await bot.download_file(voice_file.file_path)
        
        # Конвертируем в формат, который понимает Whisper
        voice_bytes = BytesIO()
        voice_bytes.write(voice_data.read())
        voice_bytes.seek(0)
        
        # Отправляем в Whisper для распознавания
        transcript = await client.audio.transcriptions.create(
            file=("voice.ogg", voice_bytes, "audio/ogg"),
            model="whisper-1"
        )
        user_question = transcript.text
        
        await message.answer(f"🎤 Ваш вопрос: {user_question}")
        
        # Получаем ответ от ассистента
        assistant_response = await get_assistant_response(user_question)
        
        # Озвучиваем ответ
        speech_response = await client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=assistant_response
        )
        
        # Сохраняем аудио во временный файл и отправляем пользователю
        speech_bytes = BytesIO(await speech_response.aread())
        await message.answer_voice(
            types.BufferedInputFile(
                speech_bytes.getvalue(), 
                filename="response.mp3"
            )
        )
        
        # Также отправляем текстовый ответ
        await message.answer(f"🤖 Ответ: {assistant_response}")
        
    except Exception as e:
        logger.error(f"Error processing voice message: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке вашего сообщения. Попробуйте позже.")

async def get_assistant_response(question: str) -> str:
    # Создаем тред для общения с ассистентом
    thread = await client.beta.threads.create()
    
    # Отправляем сообщение в тред
    await client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=question
    )
    
    # Запускаем ассистента
    run = await client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=config.ASSISTANT_ID
    )
    
    # Ждем завершения работы ассистента
    while True:
        run_status = await client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        if run_status.status == "completed":
            break
        await asyncio.sleep(1)
    
    # Получаем ответы ассистента
    messages = await client.beta.threads.messages.list(thread_id=thread.id)
    assistant_messages = [msg for msg in messages.data if msg.role == "assistant"]
    
    return assistant_messages[0].content[0].text.value if assistant_messages else "Извините, не удалось получить ответ."

# Обработчик всех остальных типов сообщений
@dp.message()
async def other_types_handler(message: Message):
    await message.answer("Я работаю только с текстовыми и голосовыми сообщениями")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
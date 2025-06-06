import os
import logging
import asyncio
from io import BytesIO
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import openai

from config import config  # Импорт конфигурации из config.py

# Инициализация клиента OpenAI
client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# Инициализация бота
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Функция для создания ассистента
async def create_assistant():
    try:
        assistant = await client.beta.assistants.create(
            name="Voice Assistant",
            instructions="Вы полезный голосовой ассистент, отвечающий на вопросы пользователей кратко и по делу.",
            model="gpt-4o",
            tools=[{"type": "code_interpreter"}]  # Опционально
        )
        logger.info(f"Создан новый ассистент с ID: {assistant.id}")
        print(f"!!! ВАЖНО: Добавьте в .env следующий ASSISTANT_ID: {assistant.id}")
        return assistant.id
    except Exception as e:
        logger.error(f"Ошибка при создании ассистента: {e}")
        raise

# Проверка и создание ассистента, если ID недействителен
async def verify_or_create_assistant():
    try:
        assistant = await client.beta.assistants.retrieve(config.ASSISTANT_ID)
        logger.info(f"Ассистент найден: {assistant.name}")
        return config.ASSISTANT_ID
    except openai.NotFoundError:
        logger.warning(f"Ассистент с ID {config.ASSISTANT_ID} не найден. Создаём новый...")
        new_assistant_id = await create_assistant()
        # Обновляем config.ASSISTANT_ID (но .env нужно обновить вручную)
        config.ASSISTANT_ID = new_assistant_id
        logger.info(f"Используется новый ASSISTANT_ID: {new_assistant_id}")
        return new_assistant_id
    except Exception as e:
        logger.error(f"Ошибка при проверке ассистента: {e}")
        raise

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
        logger.error(f"Ошибка: {e}", exc_info=True)
        await message.answer("Ошибка обработки запроса")

async def main():
    # Проверяем или создаём ассистента перед запуском бота
    await verify_or_create_assistant()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
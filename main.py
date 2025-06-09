import logging
import asyncio
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.sql import text

from config import config
from database import init_db, save_value_to_db
from services import OpenAIService

# Инициализация бота
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация базы данных
engine, async_session = init_db(config.DATABASE_URL)

# Инициализация сервиса OpenAI
openai_service = OpenAIService(config.OPENAI_API_KEY, config.AMPLITUDE_API_KEY)

# Клавиатура
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Помощь")
    builder.button(text="О боте")
    builder.button(text="Мои ценности")
    builder.button(text="Моё настроение")  # Новая кнопка
    return builder.as_markup(resize_keyboard=True)

# Состояния для диалога о ценностях
class ValuesState(StatesGroup):
    waiting_for_value = State()

# Обработчики сообщений
@dp.message(Command("start"))
async def start_handler(message: Message):
    logger.info("start handler used")
    openai_service.send_amplitude_event("start_command", str(message.from_user.id))
    await message.answer(
        "Привет! Отправь голосовое сообщение, и я отвечу голосом! Используй /values для ценностей или /mood для анализа настроения по фото.",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("mood"))
async def mood_handler(message: Message):
    logger.info("mood handler used")
    openai_service.send_amplitude_event("mood_command", str(message.from_user.id))
    await message.answer("Отправь фото своего лица, и я определю твоё настроение!")

@dp.message(F.photo)
async def photo_handler(message: Message):
    logger.info("photo handler used")
    try:
        photo = message.photo[-1]  # Берём фото с максимальным разрешением
        file = await bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file.file_path}"
        
        mood = await openai_service.analyze_mood(file_url, message.from_user.id)
        openai_service.send_amplitude_event("photo_processed", str(message.from_user.id), {"mood": mood})

        # Озвучиваем ответ
        speech = await openai_service.client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=f"Ваше настроение: {mood}"
        )
        await message.answer_voice(
            types.BufferedInputFile((await speech.aread()), filename="mood_response.mp3")
        )
        await message.answer(f"🤖 Ваше настроение: {mood}")
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}", exc_info=True)
        openai_service.send_amplitude_event("photo_error", str(message.from_user.id), {"error": str(e)})
        await message.answer("Ошибка обработки фото. Попробуйте снова.")

@dp.message(Command("values"))
async def values_handler(message: Message, state: FSMContext):
    logger.info("values handler used")
    openai_service.send_amplitude_event("values_command", str(message.from_user.id))
    await state.set_state(ValuesState.waiting_for_value)
    thread = await openai_service.client.beta.threads.create()
    await state.update_data(thread_id=thread.id)
    await message.answer("Что для тебя наиболее важно в жизни? Назови одну ценность или опиши, что ты ценишь.")

@dp.message(ValuesState.waiting_for_value, F.text | F.voice)
async def process_value(message: Message, state: FSMContext, assistant_id: str):
    try:
        user_question = ""
        event_properties = {}
        if message.voice:
            voice_file = await bot.get_file(message.voice.file_id)
            voice_data = await bot.download_file(voice_file.file_path)
            transcript = await openai_service.client.audio.transcriptions.create(
                file=("voice.ogg", BytesIO(voice_data.read()), "audio/ogg"),
                model="whisper-1"
            )
            user_question = transcript.text
            logger.info(f"Транскрипция голосового сообщения: {user_question}")
            await message.answer(f"🎤 Ваш ответ: {user_question}")
            event_properties["transcript"] = user_question
        else:
            user_question = message.text
            event_properties["text"] = user_question

        openai_service.send_amplitude_event("value_input", str(message.from_user.id), event_properties)

        data = await state.get_data()
        thread_id = data.get("thread_id")

        await openai_service.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_question
        )

        run = await openai_service.client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id
        )

        if run.status == "requires_action" and run.required_action and run.required_action.submit_tool_outputs:
            logger.info(f"Статус requires_action, tool_calls: {run.required_action.submit_tool_outputs.tool_calls}")
            value, error = await openai_service.handle_tool_outputs(thread_id, run)
            if value:
                async with async_session() as session:
                    success, response = await save_value_to_db(session, message.from_user.id, value)
                    await openai_service.submit_tool_output(thread_id, run.id, run.required_action.submit_tool_outputs.tool_calls[0].id, success, response)
                    await message.answer(response)
                    openai_service.send_amplitude_event("value_saved", str(message.from_user.id), {"value": value, "success": success})
                    if success:
                        await state.clear()
            elif error:
                await message.answer(error)
                openai_service.send_amplitude_event("value_error", str(message.from_user.id), {"error": error})
                await state.clear()

        elif run.status != "completed":
            raise Exception(f"Run завершился с ошибкой, статус: {run.status}")

        messages = await openai_service.client.beta.threads.messages.list(thread_id=thread_id)
        for msg in messages.data:
            if msg.role == "assistant" and msg.content[0].type == "text":
                assistant_response = msg.content[0].text.value
                logger.info(f"Ответ ассистента: {assistant_response}")
                await message.answer(assistant_response)
                openai_service.send_amplitude_event("assistant_response", str(message.from_user.id), {"response": assistant_response})

        await message.answer("Пожалуйста, уточните вашу ценность.")

    except Exception as e:
        logger.error(f"Ошибка обработки ценности: {e}", exc_info=True)
        openai_service.send_amplitude_event("value_processing_error", str(message.from_user.id), {"error": str(e)})
        await message.answer("Ошибка обработки. Попробуйте снова.")
        await state.clear()

@dp.message(F.text)
async def text_handler(message: Message, state: FSMContext):
    logger.info("text handler used")
    event_properties = {"text": message.text.lower()}
    openai_service.send_amplitude_event("text_message", str(message.from_user.id), event_properties)
    if message.text.lower() == "помощь":
        await message.answer("Отправь голосовое сообщение, используй /values для ценностей или /mood для настроения.")
    elif message.text.lower() == "о боте":
        await message.answer("Я голосовой ассистент на OpenAI API с функцией определения ценностей и настроения.")
    elif message.text.lower() == "мои ценности":
        async with async_session() as session:
            try:
                logger.info(f"Попытка загрузки ценностей для user_id: {message.from_user.id}")
                result = await session.execute(
                    text("SELECT value FROM user_values WHERE user_id = :user_id"),
                    {"user_id": message.from_user.id}
                )
                values = result.fetchall()
                logger.info(f"Полученные ценности для user_id {message.from_user.id}: {values}")
                if values:
                    values_list = [row[0] for row in values]
                    await message.answer(f"Ваши сохранённые ценности: {', '.join(values_list)}")
                    openai_service.send_amplitude_event("values_viewed", str(message.from_user.id), {"values": values_list})
                else:
                    await message.answer("У вас пока нет сохранённых ценностей. Используйте /values, чтобы определить их.")
                    openai_service.send_amplitude_event("values_viewed", str(message.from_user.id), {"values": []})
            except Exception as e:
                logger.error(f"Ошибка при извлечении ценностей для user_id {message.from_user.id}: {e}", exc_info=True)
                openai_service.send_amplitude_event("values_error", str(message.from_user.id), {"error": str(e)})
                await message.answer("Ошибка при загрузке ваших ценностей. Попробуйте позже.")
    elif message.text.lower() == "моё настроение":
        await mood_handler(message)
    else:
        await message.answer("Используй голосовые сообщения, /values или /mood.")

@dp.message(F.voice)
async def voice_handler(message: Message, assistant_id: str):
    logger.info("voice handler used")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_data = await bot.download_file(voice_file.file_path)
        
        transcript = await openai_service.client.audio.transcriptions.create(
            file=("voice.ogg", BytesIO(voice_data.read()), "audio/ogg"),
            model="whisper-1"
        )
        user_question = transcript.text
        await message.answer(f"🎤 Ваш вопрос: {user_question}")
        openai_service.send_amplitude_event("voice_message", str(message.from_user.id), {"transcript": user_question})

        thread = await openai_service.client.beta.threads.create()
        await openai_service.client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_question
        )
        
        run = await openai_service.client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=assistant_id
        )
        
        if run.status == "requires_action" and run.required_action and run.required_action.submit_tool_outputs:
            logger.info(f"Статус requires_action, tool_calls: {run.required_action.submit_tool_outputs.tool_calls}")
            value, error = await openai_service.handle_tool_outputs(thread.id, run)
            if value:
                async with async_session() as session:
                    success, response = await save_value_to_db(session, message.from_user.id, value)
                    await openai_service.submit_tool_output(thread.id, run.id, run.required_action.submit_tool_outputs.tool_calls[0].id, success, response)
                    await message.answer(response)
                    openai_service.send_amplitude_event("value_saved", str(message.from_user.id), {"value": value, "success": success})
            elif error:
                await message.answer(error)
                openai_service.send_amplitude_event("value_error", str(message.from_user.id), {"error": error})

        elif run.status != "completed":
            raise Exception(f"Run завершился с ошибкой, статус: {run.status}")
        
        messages = await openai_service.client.beta.threads.messages.list(thread_id=thread.id)
        assistant_response = next(m.content[0].text.value for m in messages.data if m.role == "assistant")

        speech = await openai_service.client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=assistant_response
        )
        
        await message.answer_voice(
            types.BufferedInputFile((await speech.aread()), filename="response.mp3")
        )
        await message.answer(f"🤖 Ответ: {assistant_response}")
        openai_service.send_amplitude_event("assistant_response", str(message.from_user.id), {"response": assistant_response})

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        openai_service.send_amplitude_event("voice_error", str(message.from_user.id), {"error": str(e)})
        await message.answer("Ошибка обработки запроса")

async def main():
    global openai_service
    assistant_id = await openai_service.verify_or_create_assistant(config.ASSISTANT_ID)
    if assistant_id != config.ASSISTANT_ID:
        logger.info(f"Обновлён ASSISTANT_ID с {config.ASSISTANT_ID} на {assistant_id}")
    # Передаём assistant_id в обработчики
    dp.message.register(lambda message: process_value(message, state=message.state, assistant_id=assistant_id), ValuesState.waiting_for_value, F.text | F.voice)
    dp.message.register(lambda message: voice_handler(message, assistant_id=assistant_id), F.voice)
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
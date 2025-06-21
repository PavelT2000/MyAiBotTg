
import logging
from aiogram import Router, F
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services import OpenAIService, save_value_to_db
from config import Config

logger = logging.getLogger(__name__)
router = Router()

class ValuesState(StatesGroup):
    waiting_for_value = State()

@router.message(commands=["start"])
async def start_handler(message: Message):
    await message.answer(
        "Привет! Я бот, который помогает справляться с тревожностью.\n"
        "Команды:\n/values - назвать ценность\n/mood - загрузить фото\n"
        "Задай вопрос о тревожности или отправь голосовое сообщение!"
    )

@router.message(commands=["values"])
async def values_handler(message: Message, state: FSMContext, async_session):
    await state.set_state(ValuesState.waiting_for_value)
    await message.answer("Назови свою ценность (текстом или голосом).")

@router.message(ValuesState.waiting_for_value, F.text)
async def value_text_handler(message: Message, state: FSMContext, async_session):
    value = message.text
    try:
        await save_value_to_db(async_session, message.from_user.id, value)
        await message.answer(f"Ценность '{value}' сохранена!")
        await state.clear()
    except Exception as e:
        logger.error(f"Error saving value: {e}")
        await message.answer("Ошибка при сохранении ценности.")

@router.message(ValuesState.waiting_for_value, F.voice)
async def value_voice_handler(message: Message, state: FSMContext, async_session, openai_service: OpenAIService):
    file_path = f"audio_{message.message_id}.ogg"
    try:
        await message.bot.download(message.voice.file_id, file_path)
        transcription = await openai_service.transcribe_audio(file_path)
        await save_value_to_db(async_session, message.from_user.id, transcription)
        await message.answer(f"Ценность '{transcription}' сохранена!")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing voice: {e}")
        await message.answer("Ошибка при обработке голосового сообщения.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@router.message(commands=["mood"])
async def mood_handler(message: Message):
    await message.answer("Отправь фото, чтобы я проанализировал настроение.")

@router.message(F.photo)
async def photo_handler(message: Message, openai_service: OpenAIService):
    file_path = f"photo_{message.message_id}.jpg"
    try:
        await message.bot.download(message.photo[-1].file_id, file_path)
        mood = await openai_service.process_image(file_path)
        await message.answer(f"Настроение на фото: {mood}")
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await message.answer("Ошибка при анализе фото.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@router.message(F.voice)
async def voice_handler(message: Message, state: FSMContext, openai_service: OpenAIService):
    file_path = f"audio_{message.message_id}.ogg"
    try:
        current_state = await state.get_state()
        if current_state == ValuesState.waiting_for_value:
            await value_voice_handler(message, state, openai_service)
            return
        await message.bot.download(message.voice.file_id, file_path)
        transcription = await openai_service.transcribe_audio(file_path)
        thread_id = (await state.get_data()).get("thread_id")
        if not thread_id:
            thread = await openai_service.client.beta.threads.create()
            thread_id = thread.id
            await state.update_data(thread_id=thread_id)
        response = await openai_service.process_message(thread_id, transcription)
        await message.answer(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error processing voice: {e}")
        await message.answer("Ошибка при обработке голосового сообщения.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@router.message(F.text)
async def text_handler(message: Message, state: FSMContext, openai_service: OpenAIService):
    try:
        current_state = await state.get_state()
        if current_state == ValuesState.waiting_for_value:
            await value_text_handler(message, state, openai_service)
            return
        thread_id = (await state.get_data()).get("thread_id")
        if not thread_id:
            thread = await openai_service.client.beta.threads.create()
            thread_id = thread.id
            await state.update_data(thread_id=thread_id)
        response = await openai_service.process_message(thread_id, message.text)
        await message.answer(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error processing text: {e}")
        await message.answer("Ошибка при обработке сообщения.")
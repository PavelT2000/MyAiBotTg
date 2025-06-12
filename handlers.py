import logging
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import config
from database import get_user_values, AsyncSession
from services import OpenAIService

logger = logging.getLogger(__name__)

# Описание функций бота
BOT_FUNCTIONS = """
🤖 **О моих возможностях**:

1. **Голосовой помощник**: Отправь голосовое сообщение, и я преобразую его в текст, отвечу на твой вопрос и озвучу ответ! Использую передовые технологии OpenAI для распознавания речи и генерации голоса.
2. **Определение ценностей**: Используй команду `/values`, чтобы обсудить, что для тебя важно в жизни (например, семья, свобода, успех). Я сохраню твои ценности в базе данных после проверки их корректности.
3. **Анализ настроения**: Отправь фото своего лица с командой `/mood`, и я определю твоё настроение (радость, грусть, спокойствие и т.д.) с помощью анализа изображения.
4. **Мои ценности**: Нажми кнопку "Мои ценности", чтобы посмотреть список сохранённых ценностей.

Попробуй все функции! Если нужна помощь, напиши "Помощь" или используй команду `/start`.
"""

# Клавиатура
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Помощь")
    builder.button(text="О боте")
    builder.button(text="Мои ценности")
    builder.button(text="Моё настроение")
    return builder.as_markup(resize_keyboard=True)

# Состояния для диалога
class ValuesState(StatesGroup):
    waiting_for_value = State()

def register_handlers(dp: Dispatcher, bot: Bot, openai_service: OpenAIService, assistant_id: str, async_session):
    @dp.message(Command("start"))
    async def start_handler(message: Message):
        logger.info("start handler used")
        openai_service.send_amplitude_event("start_command", str(message.from_user.id))
        await message.answer(
            f"Привет! Я твой умный голосовой ассистент. 😊\n\n{BOT_FUNCTIONS}",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
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
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            file_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file.file_path}"
            
            mood = await openai_service.analyze_mood(file_url, message.from_user.id)
            openai_service.send_amplitude_event("photo_processed", str(message.from_user.id), {"mood": mood})

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
        await message.answer("Что для тебя наиболее важное в жизни? Назови одну ценность или опиши, что ты ценишь.")

    @dp.message(F.voice | (F.text & state==ValuesState.waiting_for_value))
    async def message_handler(message: Message, state: FSMContext):
        logger.info("message handler used")
        try:
            user_question = ""
            event_properties = {}
            is_values_context = await state.get_state() == ValuesState.waiting_for_value

            # Обработка голосового или текстового сообщения
            if message.voice:
                voice_file = await bot.get_file(message.voice.file_id)
                voice_data = await bot.download_file(voice_file.file_path)
                transcript = await openai_service.client.audio.transcriptions.create(
                    file=("voice.ogg", BytesIO(voice_data.read()), "audio/ogg"),
                    model="whisper-1"
                )
                user_question = transcript.text
                logger.info(f"Транскрипция голосового сообщения: {user_question}")
                await message.answer(f"🎤 Ваш вопрос: {user_question}")
                event_properties["transcript"] = user_question
            else:
                user_question = message.text
                event_properties["text"] = user_question

            # Отправка события Amplitude
            event_type = "value_input" if is_values_context else "voice_message"
            openai_service.send_amplitude_event(event_type, str(message.from_user.id), event_properties)

            # Получение или создание треда
            data = await state.get_data()
            thread_id = data.get("thread_id")
            if not thread_id:
                thread = await openai_service.client.beta.threads.create()
                await state.update_data(thread_id=thread.id)
                thread_id = thread.id

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
                async with async_session() as session:
                    response, success = await openai_service.process_tool_call(thread_id, run, session, message.from_user.id)
                    await message.answer(response)
                    openai_service.send_amplitude_event(
                        "value_saved" if success else "value_error",
                        str(message.from_user.id),
                        {"value": response, "success": success} if success else {"error": response}
                    )
                    if success:
                        await state.clear()
                    return
            elif run.status != "completed":
                raise Exception(f"Run завершился с ошибкой, статус: {run.status}")

            messages = await openai_service.client.beta.threads.messages.list(thread_id=thread_id)
            assistant_response = next(m.content[0].text.value for m in messages.data if m.role == "assistant")

            # TTS и ответ для голосового контекста
            if not is_values_context:
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

            # Запрос уточнения для контекста ценностей
            if is_values_context:
                await message.answer("Пожалуйста, уточните вашу ценность.")

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)
            event_error_type = "value_processing_error" if is_values_context else "voice_error"
            openai_service.send_amplitude_event(event_error_type, str(message.from_user.id), {"error": str(e)})
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
            await message.answer(BOT_FUNCTIONS, parse_mode="Markdown")
        elif message.text.lower() == "мои ценности":
            async with async_session() as session:
                try:
                    logger.info(f"Попытка загрузки ценностей для user_id: {message.from_user.id}")
                    values = await get_user_values(session, message.from_user.id)
                    logger.info(f"Полученные ценности для user_id {message.from_user.id}: {values}")
                    if values:
                        await message.answer(f"Ваши сохранённые ценности: {', '.join(values)}")
                        openai_service.send_amplitude_event("values_viewed", str(message.from_user.id), {"values": values})
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
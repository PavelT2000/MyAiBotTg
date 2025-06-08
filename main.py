import os
import logging
import asyncio
from io import BytesIO
from typing import Optional
from functools import lru_cache

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import openai
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from config import config
from models import Base, UserValue

# Инициализация клиента OpenAI
client = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# Инициализация бота
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация базы данных
engine = create_async_engine(config.DATABASE_URL, echo=True, connect_args={"server_settings": {"application_name": "voice_values_bot"}})
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Функция для создания ассистента
async def create_assistant():
    logger.info("create assistant used")
    try:
        assistant = await client.beta.assistants.create(
            name="Voice and Values Assistant",
            instructions="""
            Вы полезный голосовой ассистент. Ваша задача — помогать пользователю определять его ключевые ценности через диалог.
            Начните с вопроса: 'Что для вас наиболее важно в жизни? Назови одну ценность (например, семья, свобода, успех).'
            Если пользователь даёт неясный или не относящийся к делу ответ (например, 'привет', 'пока', 'не знаю'), продолжайте задавать уточняющие вопросы, такие как: 'Пожалуйста, назовите конкретную ценность, которая для вас важна.'
            Когда пользователь называет чёткую ценность (например, 'семья', 'свобода', 'успех'), немедленно вызывайте функцию save_value с аргументом value, содержащим эту ценность.
            Не вызывайте save_value, если ответ не является валидной ценностью.
            Для голосовых сообщений преобразуйте текст в ответы, используя TTS.
            """,
            model="gpt-4o",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "save_value",
                        "description": "Сохранить определённую ценность пользователя в базе данных",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "value": {
                                    "type": "string",
                                    "description": "Ценность пользователя (например, 'семья', 'свобода', 'успех')"
                                }
                            },
                            "required": ["value"]
                        }
                    }
                }
            ]
        )
        logger.info(f"Создан новый ассистент с ID: {assistant.id}")
        print(f"!!! ВАЖНО: Добавьте в .env следующий ASSISTANT_ID: {assistant.id}")
        return assistant.id
    except Exception as e:
        logger.error(f"Ошибка при создании ассистента: {e}")
        raise

# Проверка и создание ассистента
async def verify_or_create_assistant():
    logger.info("verify or create assistant handler used")
    try:
        assistant = await client.beta.assistants.retrieve(config.ASSISTANT_ID)
        logger.info(f"Ассистент найден: {assistant.name}")
        return config.ASSISTANT_ID
    except openai.NotFoundError:
        logger.warning(f"Ассистент с ID {config.ASSISTANT_ID} не найден. Создаём новый...")
        new_assistant_id = await create_assistant()
        config.ASSISTANT_ID = new_assistant_id
        logger.info(f"Используется новый ASSISTANT_ID: {new_assistant_id}")
        return new_assistant_id
    except Exception as e:
        logger.error(f"Ошибка при проверке ассистента: {e}")
        raise

# Валидация ценности через Completions API с functools
@lru_cache(maxsize=100)
async def validate_value_cached(value: str) -> bool:
    logger.info("validate value used")
    try:
        if not value or not isinstance(value, str) or len(value.strip()) == 0:
            return False
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Вы валидатор ценностей. Верните 'true' для корректных ценностей (например, 'семья', 'свобода', 'успех'), и 'false' для некорректных (пустые, бессмысленные или бред). Ответьте только 'true' или 'false'."},
                {"role": "user", "content": value}
            ],
            max_tokens=1
        )
        is_valid = response.choices[0].message.content.strip().lower() == "true"
        logger.info(f"Валидация ценности '{value}': {is_valid}")
        return is_valid
    except Exception as e:
        logger.error(f"Ошибка валидации ценности: {e}")
        return False

async def save_value(user_id: int, value: str):
    logger.info("save value used")
    async with async_session() as session:
        async with session.begin():
            try:
                is_valid = await validate_value_cached(value)  # Ожидаем результат асинхронной функции
                if not is_valid:
                    logger.warning(f"Некорректная ценность: {value}")
                    return False, "Ценность некорректна. Пожалуйста, уточните, что вы имеете в виду."
                
                new_value = UserValue(user_id=user_id, value=value)
                session.add(new_value)
                await session.commit()
                logger.info(f"Ценность '{value}' сохранена для пользователя {user_id}")
                return True, "Ценность успешно сохранена!"
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка сохранения ценности: {e}")
                return False, "Ошибка при сохранении ценности."

# Клавиатура
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Помощь")
    builder.button(text="О боте")
    builder.button(text="Мои ценности")
    return builder.as_markup(resize_keyboard=True)

# Состояния для диалога о ценностях
class ValuesState(StatesGroup):
    waiting_for_value = State()

# Обработчики сообщений
@dp.message(Command("start"))
async def start_handler(message: Message):
    logger.info("start handler used")
    await message.answer(
        "Привет! Отправь голосовое сообщение, и я отвечу голосом! Используй /values, чтобы обсудить твои ценности.",
        reply_markup=get_main_keyboard()
    )
@dp.message(Command("values"))
async def values_handler(message: Message, state: FSMContext):
    logger.info("values handler used")
    await state.set_state(ValuesState.waiting_for_value)
    thread = await client.beta.threads.create()
    await state.update_data(thread_id=thread.id)
    await message.answer("Что для тебя наиболее важно в жизни? Назови одну ценность или опиши, что ты ценишь.")

@dp.message(ValuesState.waiting_for_value, F.text | F.voice)
async def process_value(message: Message, state: FSMContext):
    try:
        user_question = ""
        if message.voice:
            voice_file = await bot.get_file(message.voice.file_id)
            voice_data = await bot.download_file(voice_file.file_path)
            transcript = await client.audio.transcriptions.create(
                file=("voice.ogg", BytesIO(voice_data.read()), "audio/ogg"),
                model="whisper-1"
            )
            user_question = transcript.text
            logger.info(f"Транскрипция голосового сообщения: {user_question}")
            await message.answer(f"🎤 Ваш ответ: {user_question}")
        else:
            user_question = message.text

        data = await state.get_data()
        thread_id = data.get("thread_id")

        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_question
        )

        run = await client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=config.ASSISTANT_ID
        )

        if run.status == "requires_action" and run.required_action and run.required_action.submit_tool_outputs:
            logger.info(f"Статус requires_action, tool_calls: {run.required_action.submit_tool_outputs.tool_calls}")
            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                if tool_call.function.name == "save_value":
                    logger.info(f"Вызов save_value с аргументами: {tool_call.function.arguments}")
                    import json
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                        value = arguments.get("value")
                        if not value or not isinstance(value, str) or not value.strip():
                            logger.warning(f"Некорректное значение value: {value}")
                            await message.answer("Ценность не определена. Пожалуйста, уточните.")
                            return
                        logger.info(f"Извлечённая ценность: {value}")
                        success, response = await save_value(message.from_user.id, value)
                        logger.info(f"Результат save_value: success={success}, response={response}")
                        await client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run.id,
                            tool_outputs=[{"tool_call_id": tool_call.id, "output": json.dumps({"success": success, "message": response})}]
                        )
                        await message.answer(response)
                        if success:
                            await state.clear()
                        return
                    except json.JSONDecodeError as e:
                        logger.error(f"Ошибка декодирования аргументов: {e}")
                        await message.answer("Ошибка обработки. Попробуйте снова.")
                        await state.clear()
                        return
                    except Exception as e:
                        logger.error(f"Ошибка при обработке tool_call: {e}", exc_info=True)
                        await message.answer("Ошибка обработки. Попробуйте снова.")
                        await state.clear()
                        return
        elif run.status != "completed":
            raise Exception(f"Run завершился с ошибкой, статус: {run.status}")

        messages = await client.beta.threads.messages.list(thread_id=thread_id)
        for msg in messages.data:
            if msg.role == "assistant" and msg.content[0].type == "text":
                assistant_response = msg.content[0].text.value
                logger.info(f"Ответ ассистента: {assistant_response}")
                await message.answer(assistant_response)

        await message.answer("Пожалуйста, уточните вашу ценность.")

    except Exception as e:
        logger.error(f"Ошибка обработки ценности: {e}", exc_info=True)
        await message.answer("Ошибка обработки. Попробуйте снова.")
        await state.clear()



@dp.message(F.text)
async def text_handler(message: Message, state: FSMContext):
    logger.info("text handler used")
    if message.text.lower() == "помощь":
        await message.answer("Отправь голосовое сообщение или используй /values для определения ценностей.")
    elif message.text.lower() == "о боте":
        await message.answer("Я голосовой ассистент на OpenAI API с функцией определения ценностей.")
    elif message.text.lower() == "мои ценности":
        async with async_session() as session:
            result = await session.execute(
                "SELECT value FROM user_values WHERE user_id = :user_id",
                {"user_id": message.from_user.id}
            )
            values = result.fetchall()
            if values:
                values_list = [row[0] for row in values]
                await message.answer(f"Ваши сохранённые ценности: {', '.join(values_list)}")
            else:
                await message.answer("У вас пока нет сохранённых ценностей. Используйте /values, чтобы определить их.")
    else:
        await message.answer("Используй голосовые сообщения или /values.")

@dp.message(F.voice)
async def voice_handler(message: Message):
    logger.info("voice handler used")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_data = await bot.download_file(voice_file.file_path)
        
        transcript = await client.audio.transcriptions.create(
            file=("voice.ogg", BytesIO(voice_data.read()), "audio/ogg"),
            model="whisper-1"
        )
        user_question = transcript.text
        await message.answer(f"🎤 Ваш вопрос: {user_question}")

        thread = await client.beta.threads.create()
        await client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_question
        )
        
        run = await client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=config.ASSISTANT_ID
        )
        
        if run.status == "requires_action" and run.required_action and run.required_action.submit_tool_outputs:
            logger.info(f"Статус requires_action, tool_calls: {run.required_action.submit_tool_outputs.tool_calls}")
            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                if tool_call.function.name == "save_value":
                    logger.info(f"Вызов save_value с аргументами: {tool_call.function.arguments}")
                    import json
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                        value = arguments.get("value")
                        if not value or not isinstance(value, str) or not value.strip():
                            logger.warning(f"Некорректное значение value: {value}")
                            await message.answer("Ценность не определена. Пожалуйста, уточните.")
                            return
                        logger.info(f"Извлечённая ценность: {value}")
                        success, response = await save_value(message.from_user.id, value)
                        logger.info(f"Результат save_value: success={success}, response={response}")
                        await client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread.id,
                            run_id=run.id,
                            tool_outputs=[{"tool_call_id": tool_call.id, "output": json.dumps({"success": success, "message": response})}]
                        )
                        await message.answer(response)
                        return
                    except json.JSONDecodeError as e:
                        logger.error(f"Ошибка декодирования аргументов: {e}")
                        await message.answer("Ошибка обработки. Попробуйте снова.")
                        return
                    except Exception as e:
                        logger.error(f"Ошибка при обработке tool_call: {e}", exc_info=True)
                        await message.answer("Ошибка обработки. Попробуйте снова.")
                        return
        elif run.status != "completed":
            raise Exception(f"Run завершился с ошибкой, статус: {run.status}")
        
        messages = await client.beta.threads.messages.list(thread_id=thread.id)
        assistant_response = next(m.content[0].text.value for m in messages.data if m.role == "assistant")

        speech = await client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=assistant_response
        )
        
        await message.answer_voice(
            types.BufferedInputFile((await speech.aread()), filename="response.mp3")
        )
        await message.answer(f"🤖 Ответ: {assistant_response}")

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await message.answer("Ошибка обработки запроса")


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await verify_or_create_assistant()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
import aiohttp
import logging
import amplitude
from openai import AsyncOpenAI
from database import save_value_to_db

logger = logging.getLogger(__name__)

class BaseEvent:
    def __init__(self, event_type: str, user_id: str, event_properties: dict = None):
        self.event_type = event_type
        self.user_id = user_id
        self.event_properties = event_properties or {}

class OpenAIService:
    def __init__(self, api_key: str, amplitude_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.amplitude_client = amplitude.Amplitude(amplitude_key)

    def send_amplitude_event(self, event_type: str, user_id: str, event_properties: dict = None):
        event = BaseEvent(event_type, user_id, event_properties)
        try:
            self.amplitude_client.track(amplitude.Event(
                event_type=event.event_type,
                user_id=event.user_id,
                event_properties=event.event_properties
            ))
            logger.info(f"Amplitude event sent: {event_type}, user_id: {user_id}, properties: {event_properties}")
        except Exception as e:
            logger.error(f"Failed to send Amplitude event: {e}")

    async def analyze_mood(self, image_url: str, user_id: str) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    image_data = await response.read()
            response = await self.client.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze the mood of the person in this image."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data.decode('base64')}"}}
                        ]
                    }
                ],
                max_tokens=100
            )
            mood = response.choices[0].message.content.strip()
            return mood
        except Exception as e:
            logger.error(f"Error analyzing mood for user {user_id}: {e}")
            raise

    async def process_tool_call(self, thread_id: str, run: dict, session, user_id: str):
        try:
            tool_outputs = []
            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                if tool_call.function.name == "save_value_to_db":
                    arguments = json.loads(tool_call.function.arguments)
                    value = arguments.get("value")
                    if value:
                        await save_value_to_db(session, user_id, value)
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": f"Value '{value}' saved successfully."
                        })
                        return f"Value '{value}' saved to database!", True
                    else:
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": "No value provided."
                        })
                        return "Please provide a valid value.", False
            await self.client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            return "Tool processed.", False
        except Exception as e:
            logger.error(f"Error processing tool call: {e}")
            return f"Error processing tool call: {str(e)}", False

    async def create_vector_store(self, file_path: str) -> str:
        """Создаёт vector_store и загружает файл."""
        try:
            vector_store = await self.client.beta.vector_stores.create(name="Anxiety_Document_Store")
            with open(file_path, "rb") as file:
                await self.client.beta.vector_stores.files.upload(
                    vector_store_id=vector_store.id,
                    file=file
                )
            logger.info(f"Vector store created with ID: {vector_store.id}")
            return vector_store.id
        except Exception as e:
            logger.error(f"Error creating vector store: {e}")
            raise

    async def update_assistant(self, assistant_id: str, vector_store_id: str):
        """Обновляет ассистента, добавляя file_search и vector_store."""
        try:
            await self.client.beta.assistants.update(
                assistant_id=assistant_id,
                tools=[{"type": "file_search"}],
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}
            )
            logger.info(f"Assistant {assistant_id} updated with vector store {vector_store_id}")
        except Exception as e:
            logger.error(f"Error updating assistant: {e}")
            raise
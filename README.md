# MyAiBotTg

A production-ready Telegram bot powered by OpenAI's Assistants API (v2), featuring integrated vector search, asynchronous PostgreSQL persistence, Redis state management, and Amplitude analytics. Designed to process domain-specific documents and maintain persistent user interactions.

---

## 📖 Overview

`MyAiBotTg` bridges conversational AI with structured data persistence. On startup, it automatically ingests a reference document (`Anxiety.docx`), creates an OpenAI Vector Store for semantic search, verifies or provisions an AI Assistant, and begins polling for Telegram messages. User interactions and extracted values are stored in PostgreSQL, while session states are managed via Redis.

---

## ✨ Key Features

- 🔍 **OpenAI Assistants API v2**: Native integration with File Search & Vector Stores for context-aware responses.
- 🤖 **Asynchronous Telegram Bot**: Built on `aiogram 3.x` with Redis-backed FSM storage.
- 🗄️ **Persistent Storage**: PostgreSQL via `SQLAlchemy 2.0` (async) for user data and value tracking.
- 📊 **Analytics**: Amplitude integration for event tracking and user behavior insights.
- 🐳 **Containerized Deployment**: Ready-to-run `docker-compose` stack with PostgreSQL & Redis.
- 🔄 **Database Migrations**: Alembic configured for schema versioning and production deployments.

---

## 🛠️ Tech Stack

| Component       | Technology                          |
|-----------------|-------------------------------------|
| Language        | Python 3.12                         |
| Bot Framework   | `aiogram` 3.20.0                    |
| AI/LLM          | OpenAI API (`openai` 1.84.0)        |
| Database        | PostgreSQL + `asyncpg` + SQLAlchemy |
| Cache/State     | Redis 7                             |
| Analytics       | Amplitude                           |
| Migrations      | Alembic                             |
| Containerization| Docker & Docker Compose             |

---

## ⚙️ Environment Configuration

Create a `.env` file in the project root with the following variables:

| Variable              | Description                                      | Example                                  |
|-----------------------|--------------------------------------------------|------------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | Telegram Bot API token                           | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `OPENAI_API_KEY`      | OpenAI API key with Assistants API access        | `sk-proj-...`                            |
| `ASSISTANT_ID`        | Existing OpenAI Assistant ID (auto-created if missing) | `asst_...`                          |
| `DATABASE_URL`        | Async PostgreSQL connection string               | `postgresql+asyncpg://user:pass@postgres:5432/voice_values_db` |
| `REDIS_URL`           | Redis connection string                          | `redis://redis:6379/0`                   |
| `AMPLITUDE_API_KEY`   | Amplitude project API key                        | `amp_...`                                |

> 🔒 **Security Note**: Never commit `.env` to version control. The `.gitignore` and `.aiignore` files are preconfigured to exclude it.

---

## 🚀 Installation & Deployment

### Option 1: Docker Compose (Recommended)

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd MyAiBotTg
   ```

2. **Prepare environment**
   ```bash
   cp .env.example .env  # If available, otherwise create manually
   # Edit .env with your credentials
   ```

3. **Rename Dockerfile** (if still named `Dockerfile.txt`)
   ```bash
   mv Dockerfile.txt Dockerfile
   ```

4. **Start the stack**
   ```bash
   docker compose up -d --build
   ```

5. **View logs**
   ```bash
   docker compose logs -f bot
   ```

### Option 2: Local Development

1. **Create virtual environment & install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Ensure services are running**
   - PostgreSQL & Redis must be accessible locally or via Docker.
   - Update `DATABASE_URL` and `REDIS_URL` in `.env` accordingly.

3. **Run the bot**
   ```bash
   python main.py
   ```

---

## 📁 Project Structure

```
├── .aiignore              # AI context exclusion rules
├── .gitignore             # Git exclusion rules
├── Anxiety.docx           # Reference document for OpenAI File Search
├── Dockerfile             # Container build instructions
├── alembic/               # Database migration configuration
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── initial_migration.py
├── config.py              # Pydantic settings & .env loader
├── database.py            # Async SQLAlchemy engine & session helpers
├── docker-compose.yaml    # Multi-container orchestration
├── handlers.py            # Telegram command/message handlers
├── main.py                # Application entrypoint & startup sequence
├── models.py              # SQLAlchemy ORM models
├── requirements.txt       # Python dependencies
└── services.py            # OpenAI & Amplitude business logic
```

---

## 🗄️ Database & Migrations

- **Development**: Tables are automatically created on startup via `Base.metadata.create_all`.
- **Production**: Use Alembic for controlled schema migrations:
  ```bash
  alembic revision --autogenerate -m "initial migration"
  alembic upgrade head
  ```
- **Schema**: `user_values` table stores `user_id`, `value`, and `created_at` timestamps.

---

## 📝 Startup Workflow

1. Validates and logs environment variables (truncated for security).
2. Establishes Redis connection & initializes `RedisStorage` for FSM.
3. Creates/verifies PostgreSQL tables.
4. Verifies or creates the OpenAI Assistant.
5. Uploads `Anxiety.docx` to OpenAI Files API.
6. Creates a Vector Store and attaches the uploaded file.
7. Updates the Assistant with File Search capabilities.
8. Registers Telegram handlers and starts polling.
9. Gracefully closes Redis on shutdown.

---

## 🔒 Notes & Best Practices

- ⚠️ **Synchronous Upload**: File upload and vector store creation run synchronously during startup. This is intentional for initialization but may briefly block the event loop. For high-availability deployments, consider moving this to a background task or pre-provisioning the vector store.
- 📄 **Document Requirement**: `Anxiety.docx` must exist in the project root at startup. Missing or empty files will raise a `FileNotFoundError` or `ValueError`.
- 🔄 **Assistant ID**: If `ASSISTANT_ID` is invalid or missing, the bot will auto-create a new assistant and log the updated ID. Update your `.env` accordingly for subsequent runs.
- 🐳 **Port Exposure**: `docker-compose.yaml` exposes `5432` (PostgreSQL) and `6379` (Redis) to the host for development. Remove `ports:` in production to restrict external access.

---

## 📄 License

This project is proprietary/internal. All rights reserved.

---

> 💡 **Need Help?**  
> Check bot logs for detailed error traces. Ensure all API keys are valid and services are reachable before deployment. For architecture or integration questions, refer to `services.py` and `handlers.py`.
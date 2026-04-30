# Ukiyo

Ukiyo eliminates the hop between LLM provider websites by automatically routing each user prompt to the best-matched model, with manual override always available to the user.

Currently we categorize the user's prompts intent into three buckets for the initial scope.
Three buckets, one model each:
- **coding** → `claude-sonnet-4-6`
- **design** → `gpt-4o`
- **research** → `gemini-2.5-pro`

Routing is embedding k-NN over hand-curated bucket exemplars, with hysteresis to avoid mid-conversation thrash. A side-drawer **design canvas** turns the design bucket into an HTML+Tailwind builder with sandboxed iframe preview, click-to-edit, and one-way export to Figma via a companion plugin.

## Project structure

```
ukiyo/
├── app.py                      # uvicorn entry; re-exports the FastAPI app
├── pyproject.toml              # backend deps (Python 3.12)
├── Dockerfile                  # builds the backend service image
├── docker-compose.yml          # Postgres with pgvector extension + backend service
├── alembic/                    # DB migrations
├── backend/
│   └── ukiyo_service/src/ukiyo_service/
│       ├── application/        # FastAPI: main, routes, deps
│       ├── domain/             # business logic, no I/O (routing classifier, etc.)
│       └── infrastructure/     # all I/O lives here
│           ├── db/             # SQLAlchemy async engine, models, session
│           ├── llm/            # provider-agnostic streaming (OpenAI / Anthropic / Google)
│           └── embeddings/     # OpenAI text-embedding-3-small wrapper
├── frontend/                   # Next.js 16 + React 19 chat UI
├── data/
│   └── bucket_exemplars.json   # hand-curated prompts used to define each bucket's region in embedding space
└── scripts/
    └── seed_buckets.py         # script to embed exemplars and insert them into bucket_exemplars
```

## Major components

- **Backend service** (`backend/ukiyo_service/`) — FastAPI monolith. Async SQLAlchemy + Postgres + pgvector. Three layers:
  - `application/` — HTTP shape: routes, dependencies, FastAPI lifespan.
  - `domain/` — pure business logic (routing classifier and selector). No HTTP, no I/O.
  - `infrastructure/` — all external I/O: DB session, provider-agnostic LLM streaming (`get_provider(model).stream(...)` yields normalized `Chunk` objects regardless of which SDK is underneath), and the OpenAI embeddings client.
- **Frontend** (`frontend/`) — Next.js 16 + React 19 + Tailwind 4. Uses the Vercel AI SDK (`ai`) for streaming, Streamdown for markdown, Radix UI for primitives, plus motion / GSAP / Lenis for the marketing surface.
- **Database** — Postgres 16 with the `pgvector` extension. The `bucket_exemplars` table is the vector store the routing classifier reads against; the index is HNSW with cosine ops.

## Tech stack

**Backend (Python 3.12)**
- FastAPI + Uvicorn
- SQLAlchemy 2.x async + asyncpg + Alembic
- pgvector (Postgres extension + Python bindings)
- pydantic-settings (env loading)
- Official `openai`, `anthropic`, `google-genai` SDKs

**Frontend (Node 20+)**
- Next.js 16, React 19
- Tailwind CSS 4
- Vercel AI SDK (`ai`), Streamdown
- Radix UI, Lucide, cmdk
- Motion, GSAP, Lenis (marketing surface animations)

**Infrastructure**
- Docker + docker-compose
- Postgres 16 with pgvector

## Configuration

Copy `.env.example` to `.env` and fill in the API keys you have. Compose injects `DATABASE_URL` automatically when running via `docker compose`; the value in `.env` is used when running the service outside compose.

```bash
cp .env.example .env
```

Required for full functionality:
- `OPENAI_API_KEY` — embeddings (mandatory; the seed script and classifier both need it)
- `ANTHROPIC_API_KEY` — default generalist model is `claude-sonnet-4-6`, so this is needed for chat to work end-to-end
- `GOOGLE_API_KEY` — only needed once routing sends a prompt to Gemini

Other settings (with sensible defaults in `Settings`): `JWT_SECRET`, `DAILY_TOKEN_CAP`, `GENERALIST_MODEL`, `BUCKET_MODEL_MAP`.

## Running the backend

### With Docker (recommended)

```bash
docker compose up
```

This brings up Postgres (with pgvector) and the FastAPI service. `alembic upgrade head` runs automatically at container start. The service is at `http://localhost:8000`; `GET /health` returns ok once it's up.

After first boot, populate the bucket exemplars table (one-shot, idempotent — safe to re-run after editing the JSON):

```bash
docker compose exec ukiyo_service python scripts/seed_buckets.py
```

### Locally (without Docker for the service)

You still need a Postgres-with-pgvector reachable; the simplest option is to run just the database via compose:

```bash
docker compose up postgres
```

Then in another shell:

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn app:app --reload
```

Populate exemplars (with `.env` pointing at `localhost:5432`):

```bash
python scripts/seed_buckets.py
```

## Running the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend dev server runs at `http://localhost:3000`. It's a separate process from the backend; both should be running for the full chat flow.

# SignalFlow

Multi-Agent AI Marketing Platform — find relevant social opportunities, score them with a transparent relevance engine, and draft helpful replies. All posting is manual; nothing is auto-posted.

## Quick Start

### Prerequisites

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 20+** and npm
- A free **[Supabase](https://supabase.com)** project (takes ~2 minutes)
- A **Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey) (free tier available)

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/social-ai-reply.git
cd social-ai-reply

# Create environment files
cp .env.example .env
cp web/.env.local.example web/.env.local
```

Edit **`.env`** — fill in your Supabase credentials and Gemini API key:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=your-service-role-key
SUPABASE_PUBLISHABLE_KEY=your-anon-key
SUPABASE_JWT_SECRET=your-jwt-secret
GEMINI_API_KEY=your-gemini-api-key
```

Edit **`web/.env.local`** — fill in the same Supabase URL and anon key:

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-anon-key
```

> **Where to find these values:**
> Go to your [Supabase Dashboard](https://supabase.com/dashboard) → Select your project → **Settings** → **API**.
> - `SUPABASE_URL` = Project URL
> - `SUPABASE_PUBLISHABLE_KEY` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` = `anon` `public` key
> - `SUPABASE_SECRET_KEY` = `service_role` `secret` key
> - `SUPABASE_JWT_SECRET` = JWT Secret (under Settings → API → JWT Settings)

### 2. Set Up the Database

Open your Supabase Dashboard → **SQL Editor** → paste the contents of [`supabase/migrations/00000000000000_initial_schema.sql`](supabase/migrations/00000000000000_initial_schema.sql) → click **Run**.

This creates all required tables. It's idempotent — safe to run multiple times.

### 3. Install & Run

```bash
# Backend
uv sync --extra dev
uv run uvicorn app.main:app --reload      # → http://localhost:8000

# Frontend (new terminal)
cd web && npm install
npm run dev                                # → http://localhost:3000
```

### 4. Register & Go

Open [http://localhost:3000](http://localhost:3000), register an account, and you're in.

### One-Command Alternative

```bash
./scripts/setup.sh
```

This checks prerequisites, creates env files, and installs all dependencies.

---

## Architecture

### Agents
| # | Agent | What it does |
|---|-------|-------------|
| 1 | **Brand Brain** | Analyzes your website, extracts product intelligence, builds keyword universe |
| 2 | **Reddit Agent** | Finds relevant Reddit posts using free public feeds |
| 3 | **Hacker News Agent** | Monitors HN for technical/product discussions |
| 4 | **SEO Agent** | Crawls your site, finds SEO issues + keyword gaps |
| 5 | **GEO Agent** | Scores AI search visibility readiness |
| 6 | **Articles Agent** | Generates SEO article briefs from real gaps |
| 7 | **X/Twitter Agent** | Manual mode: generates content ideas and search queries |
| 8 | **LinkedIn Agent** | Manual mode: generates professional post ideas |
| 9 | **UGC Agent** | Creates short video briefs from pain points |
| 10 | **Technical SEO Agent** | Code-level website audit with fix suggestions |

### Core Services
- **Relevance Engine v2** — Weighted scoring: keywords (25%) + semantic similarity (30%) + intent (20%) + pain points (10%) + source fit (10%) + freshness (5%)
- **Embedding Service** — Local TF-IDF embeddings (default) or optional sentence-transformers
- **LLM Service** — Gemini (default), OpenAI, Claude, Perplexity, or Ollama (local)
- **Scheduler** — Manual, daily, or cron-based agent execution
- **Feedback Loop** — Learns from approve/reject actions to tune keyword weights

### Tech Stack
- **Backend:** FastAPI + Python 3.11 + Supabase Postgres
- **Frontend:** Next.js 16 + React 19 + Tailwind CSS v4 + shadcn/ui
- **Auth:** Supabase Auth with JWT
- **Embeddings:** scikit-learn TF-IDF (default) + optional sentence-transformers
- **LLM:** Modular provider system (Gemini, OpenAI, Claude, Perplexity, Ollama)

---

## Environment Variables

### Backend (`.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | **Yes** | — | Your Supabase project URL |
| `SUPABASE_SECRET_KEY` | **Yes** | — | Service role key |
| `SUPABASE_PUBLISHABLE_KEY` | **Yes** | — | Anon/public key |
| `SUPABASE_JWT_SECRET` | **Yes** | — | JWT secret for token verification |
| `GEMINI_API_KEY` | Recommended | — | Required for AI features (free tier available) |
| `FRONTEND_URL` | No | `http://localhost:3000` | Frontend URL for CORS |
| `LLM_PROVIDER` | No | `gemini` | `gemini`, `openai`, `claude`, `perplexity` |
| `OPENAI_API_KEY` | No | — | Only if `LLM_PROVIDER=openai` |
| `ANTHROPIC_API_KEY` | No | — | Only if `LLM_PROVIDER=claude` |
| `OLLAMA_BASE_URL` | No | — | For local LLM via Ollama |
| `ENCRYPTION_KEY` | Prod only | — | Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

See [`.env.example`](.env.example) for the complete list.

### Frontend (`web/.env.local`)

| Variable | Required | Default |
|----------|----------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | No | `http://localhost:8000` |
| `NEXT_PUBLIC_SUPABASE_URL` | **Yes** | — |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | **Yes** | — |

---

## Development

### Commands

```bash
# Backend
uv run uvicorn app.main:app --reload      # Dev server at :8000
uv run pytest -q                           # Run all tests
uv run ruff check app/ tests/              # Lint
uv run ruff check --fix app/ tests/        # Auto-fix lint

# Frontend
cd web && npm run dev                      # Dev server at :3000
npm run build                              # Type-check + production build
```

### Running Agents

```bash
# From the dashboard
# Go to Agent Runs page → click "Run All" or run individual agents

# CLI
python -m app.services.infrastructure.scheduler.cli --company-id 1 --run-all
python -m app.services.infrastructure.scheduler.cli --company-id 1 --agent reddit
```

### How the Relevance Engine Works

```
base_score = keyword_score × 0.25
           + semantic_similarity × 0.30
           + intent_score × 0.20
           + pain_point_score × 0.10
           + source_fit_score × 0.10
           + freshness_score × 0.05
           − penalties
```

A post is **kept** only if:
- `relevance_score >= 70` and `semantic_similarity >= 0.45`
- At least 2 keyword matches OR strong semantic match
- Intent is not spam/unsafe/irrelevant
- Post is not a job listing or too old (>180 days)

---

## Database Migrations

The initial schema file (`supabase/migrations/00000000000000_initial_schema.sql`) creates everything from scratch.

Subsequent migrations in `app/db/migrations/` are incremental patches. If you already ran the initial schema, these are optional — they add columns that already exist in the initial schema.

To apply a migration manually:
1. Open Supabase Dashboard → SQL Editor
2. Paste the migration SQL
3. Click Run

---

## Deployment

### Backend → Railway

Configured via `railway.toml` and `nixpacks.toml`. Set these env vars in the Railway dashboard:
- All `SUPABASE_*` variables
- `GEMINI_API_KEY`
- `ENVIRONMENT=production`
- `FRONTEND_URL` (Netlify URL)
- `CORS_ORIGINS_RAW` (Netlify URL)
- `ENCRYPTION_KEY`

### Frontend → Netlify

Configured via `netlify.toml`. Set these env vars in the Netlify dashboard:
- `NEXT_PUBLIC_API_BASE_URL` (Railway URL)
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

> **Important:** Do NOT add a root `package.json`. It would break the Railway build.

---

## Known Limitations

1. **X/Twitter and LinkedIn** require manual import — no live API fetching
2. **Semantic embeddings** default to TF-IDF; sentence-transformers gives better quality but requires ~50MB model download
3. **Reddit discovery** uses public JSON + DuckDuckGo fallback — no Reddit OAuth required for reading
4. **Scheduler** uses FastAPI BackgroundTasks — for production scale, consider Celery/RQ

## License

MIT

# Social AI Reply / RedditFlow

Multi-Agent AI Marketing Platform — find relevant social opportunities, generate safe drafts, and grow without spam.

## What Is This

A free/open-source-first AI CMO platform that finds highly relevant posts across Reddit, Hacker News, and more, scores them with a transparent relevance engine, and drafts helpful replies — without auto-posting or paid API dependencies.

## Architecture

### Agents
1. **Brand Brain** — Analyzes your website, extracts product intelligence, builds keyword universe
2. **Reddit Agent** — Finds relevant Reddit posts using free public API
3. **Hacker News Agent** — Monitors HN for technical/product discussions
4. **SEO Agent** — Crawls your site and finds SEO issues + keyword gaps
5. **GEO Agent** — Scores AI search visibility readiness and suggests content gaps
6. **Articles Agent** — Generates SEO article briefs from real gaps
7. **X/Twitter Agent** — Manual mode: generates content ideas and search queries
8. **LinkedIn Agent** — Manual mode: generates professional post ideas
9. **UGC Agent** — Creates short video briefs from pain points
10. **Technical SEO Agent** — Code-level website audit with fix suggestions

### Core Services
- **Relevance Engine v2** — Weighted scoring: keywords (25%) + semantic similarity (30%) + intent (20%) + pain points (10%) + source fit (10%) + freshness (5%). Hard reject for spam, jobs, unrelated content.
- **Embedding Service** — Local TF-IDF embeddings (default) with optional sentence-transformers. No paid API required.
- **LLM Service** — Supports Gemini (default), OpenAI, Claude, Perplexity, Ollama (local), and Template fallback (zero-cost).
- **Scheduler** — Runs agents manually, daily, or via cron. Tracks all runs.
- **Feedback Loop** — Learns from approve/reject actions. Auto-tunes keyword weights.

## Tech Stack
- Backend: FastAPI + Python 3.11 + Supabase Postgres
- Frontend: Next.js 16 + React 19 + Tailwind CSS v4 + shadcn/ui
- Auth: Supabase Auth with JWT
- Embeddings: scikit-learn TF-IDF (default) + optional sentence-transformers
- LLM: Modular provider system (Gemini, OpenAI, Claude, Perplexity, Ollama, Template)

## Setup

### Backend
```bash
cp .env.example .env
# Edit .env with your Supabase credentials
# Optional: add OLLAMA_BASE_URL for local LLM
# Optional: add GEMINI_API_KEY for better AI quality
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

### Frontend
```bash
cd web
npm install
npm run dev
```

### Database
Apply the migration:
```bash
# Run the SQL in app/db/migrations/001_multi_agent_platform.sql in your Supabase SQL Editor
```

## Environment Variables

Required:
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_SECRET`
- `ENCRYPTION_KEY`
- `FRONTEND_URL`, `CORS_ORIGINS_RAW`

Optional (for better AI quality):
- `GEMINI_API_KEY` — for Gemini LLM (default provider)
- `OPENAI_API_KEY` — for OpenAI alternative
- `OLLAMA_BASE_URL` — for local LLM via Ollama

Optional (for Reddit account connection):
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_REDIRECT_URI`

Configuration:
- `EMBEDDING_MODEL` — "tfidf" (default) or "sentence-transformers"
- `RELEVANCE_THRESHOLD` — 70 (default, 0-100)
- `SEMANTIC_THRESHOLD` — 0.45 (default, 0-1)
- `DEFAULT_LOOKBACK_DAYS` — 7 (default)

## How the Relevance Engine Works

The relevance engine uses a transparent weighted formula:
```
base_score = keyword_score * 0.25
           + semantic_similarity * 0.30
           + intent_score * 0.20
           + pain_point_score * 0.10
           + source_fit_score * 0.10
           + freshness_score * 0.05
           - penalties
```

A post is **kept** only if:
- relevance_score >= 70
- semantic_similarity >= 0.45
- At least 2 meaningful keyword matches OR strong semantic match
- Intent is not spam/unsafe/irrelevant
- Post is not a job posting (unless recruiting-related)
- Post is not too old (>180 days)

Every kept post shows a clear `reason_relevant`. Every rejected post shows a `rejection_reason` in debug mode.

## Running Agents

### Manual run (from dashboard)
Go to Agent Runs page → click "Run All" or run individual agents.

### Daily scheduler
```bash
# Run all agents for a company
python -m app.services.infrastructure.scheduler.cli --company-id 1 --run-all

# Run specific agent
python -m app.services.infrastructure.scheduler.cli --company-id 1 --agent reddit
```

## How to Test Relevance

Run the relevance tests:
```bash
uv run pytest tests/unit/test_relevance_v2.py -v
```

This validates:
- Real estate posts about broker fees score >= 70
- Gaming laptop posts score < 40
- Spam posts are rejected
- Job postings are hard rejected
- reason_relevant is always generated for kept posts
- rejection_reason is always generated for rejected posts

## Known Limitations

1. **X/Twitter and LinkedIn** require manual import or generated content ideas — no live API fetching (free APIs are unreliable).
2. **Semantic embeddings** default to TF-IDF. sentence-transformers can be enabled for better quality but requires ~50MB model download.
3. **LLM quality** with TemplateProvider is functional but less nuanced than real LLM. Configure Gemini or Ollama for best results.
4. **Scheduler** uses FastAPI BackgroundTasks — for production scale, consider migrating to Celery/RQ.
5. **Website crawling** respects robots.txt but some sites may still block automated requests.
6. **Reddit discovery** uses public JSON + DuckDuckGo fallback — no Reddit OAuth required for reading.

## License

[Your license here]

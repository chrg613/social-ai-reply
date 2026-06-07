# AGENTS.md

## Project Overview

RedditFlow is a hosted SaaS for finding relevant Reddit posts, scoring opportunities, and drafting helpful replies. All posting is manual — nothing is auto-posted to Reddit.

## Product Policy

- **Initial-phase usage policy:** RedditFlow does **not** enforce customer-facing query limits, scan quotas, generation caps, seat caps, or plan-based usage ceilings in the initial product phase.
- This is an explicit product and system-design decision by the team so early users can use the platform without artificial usage restrictions.
- Any technical rate limiting in middleware exists only for platform stability and abuse protection. It must not be treated as a commercial, entitlement, or pricing limit.

## Commands

### Backend
```bash
cp .env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload      # dev server at :8000
uv run pytest -q                           # all tests
uv run pytest tests/unit/test_security.py -q  # single file
uv run ruff check app/ tests/              # lint
uv run ruff check --fix app/ tests/        # auto-fix lint
```

### Frontend
```bash
cd web && npm install
npm run dev       # dev server at :3000
npm run build     # type-check + production build (serves as the test step)
```

## Architecture

### Backend (`app/`)

FastAPI + Supabase Postgres + Supabase Auth. Entry point: `app/main.py` — creates app, registers middleware (request tracing + rate limiting), mounts v1 routes.

**Layered structure:**
- **Routes** (`app/api/v1/routes/`) — domain modules (auth, projects, discovery, drafts, scans, billing, etc.). Aggregated in `__init__.py`. All live under `/v1`.
- **Dependencies** (`app/api/v1/deps.py`) — `get_current_user`, `get_current_workspace`, `get_project`, `get_active_project`, `ensure_default_prompts`. All authenticated endpoints use these.
- **Schemas** (`app/schemas/v1/`) — Pydantic v2 request/response models.
- **Database Layer** (`app/db/`):
  - `supabase_client.py` — Singleton Supabase client with `get_supabase()` dependency
  - `tables/*.py` — Typed helper functions for all table operations (users, workspaces, projects, discovery, content, visibility, analytics, other)
- **Services** (`app/services/`) — business logic:
  - `product/pipeline.py` — scan → opportunity → draft orchestration
  - `product/copilot.py` — LLM-driven reply/post generation
  - `product/scanner.py` — Reddit scraping and opportunity detection
  - `product/scoring.py` — opportunity fit scoring
  - `product/entitlements.py` — subscription and entitlement scaffolding for billing/workspace state; do not assume active customer-facing usage caps in the initial phase
  - `product/visibility.py` — AI visibility prompt sets and citation tracking
  - `product/reddit.py` — Reddit API interaction
  - `product/security.py` — JWT encode/decode, password hashing
  - `product/supabase_auth.py` — Supabase Auth HTTP client
  - `product/discovery.py` — Subreddit discovery and analysis
  - `infrastructure/llm/` — Modular LLM provider system (`LLMService` facade, per-provider modules in `providers/`). **Gemini is the default provider;** OpenAI, Perplexity, and Claude are supported alternatives but not required.
- **Core** (`app/core/`) — `config.py` (pydantic-settings), `exceptions.py` (custom hierarchy: `AppException` → `NotFoundError`, `ForbiddenError`, `ConflictError`, `AuthenticationError`, `BusinessRuleError`).

**Database:** Supabase Postgres via `supabase-py` client. All queries go through helpers in `app/db/tables/`.

### Frontend (`web/`)

Next.js 16 + React 19 + Tailwind CSS v4 + shadcn/ui (on `@base-ui/react`) + Zustand.

- **Routing:** App Router. Public: `web/app/page.tsx`, `login/`, `register/`, `reset-password/`. Authenticated: `web/app/app/` with shared layout wrapping `AppShell` + `ErrorBoundary`.
- **API client:** `web/lib/api.ts` — `apiRequest<T>()` helper + domain modules in `web/lib/api/`.
- **State:** Zustand stores in `web/stores/` (`auth-store`, `project-store`, `ui-store`). Auth state is managed via `useAuthStore` and consumed through the `useAuth` hook. `useSelectedProjectId` hook reads `project-store`.
- **Styles:** Tailwind v4 + CVA variants. Tokens/globals in `web/app/globals.css`. Legacy `web/styles/` plain CSS is being phased out.
- **Components:** `web/components/ui/` — shadcn primitives (`button`, `input`, `tabs`, `dialog`, ...). `web/components/` — `app-shell.tsx`, `auth/auth-provider.tsx`, `error-boundary.tsx` (class component for error boundaries), `toaster.tsx`.

**React 19 migration notes:**
- No breaking changes encountered — codebase was already using compatible patterns
- `createRoot` is used implicitly by Next.js 16
- Class components (ErrorBoundary) continue to work without modification
- No deprecated APIs (`getDefaultProps`, `propTypes`) were in use

## Key Conventions

- **Auth:** Supabase Auth with JWT Bearer tokens. Registration creates Supabase identity + local user + workspace + membership atomically. Token carries `sub` (Supabase user ID). Workspace resolved from membership.
- **Multi-tenancy:** Everything scoped by `workspace_id`. Projects belong to workspaces. Most routes require auth + workspace membership.
- **Database:** All queries use Supabase Python client via `app/db/tables/*` helpers. Example:
  ```python
  from app.db.supabase_client import get_supabase
  from app.db.tables.discovery import list_opportunities_for_project
  
  @router.get("/opps")
  def list_opps(supabase: Client = Depends(get_supabase)):
      opps = list_opportunities_for_project(supabase, project_id=1)
      return opps
  ```
- **LLM:** **Gemini is the default provider** (`LLM_PROVIDER=gemini`, set in `DEFAULT_LLM_PROVIDER`). Only `GEMINI_API_KEY` is required; `OPENAI_API_KEY` and other provider keys can be left unset. Switch to `openai` / `perplexity` / `claude` via `LLM_PROVIDER` if you need an alternative (OpenAI supports `OPENAI_BASE_URL` for Azure/Ollama/LM Studio/Together AI). Always use a real LLM with a valid API key — never use mock or simulated data.
- **Usage limits policy:** There are currently no customer-facing product usage limits. Do not describe the platform as quota-based or capped in the initial phase unless the product policy changes.
- **Rate limiting:** In-memory in `app/middleware.py` — scan: 5/60s, generate: 10/60s, auth: 10/300s, default: 60/60s. These are operational safeguards, not plan limits.
- **Testing:** Supabase local dev or test Supabase project. `conftest.py` fixtures: `client`, `authed_client`, `authed_headers`.
- **Linting:** Ruff, `target-version = "py311"`, `line-length = 120`. Rules: E, F, W, I, N, UP, B, SIM, TCH. E501 ignored.

## Environment Variables

Key vars (see `.env.example` for full list): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_SECRET`, `LLM_PROVIDER` (default: `gemini`), `GEMINI_API_KEY` (required for default LLM), `FRONTEND_URL`, `CORS_ORIGINS_RAW`, `REDDIT_USER_AGENT`. `OPENAI_API_KEY` / `PERPLEXITY_API_KEY` / `ANTHROPIC_API_KEY` are optional — only needed if you switch `LLM_PROVIDER` away from Gemini.

## Deployment

Monorepo with two deploy targets:

- **Backend** → **Railway** from repo root. Configs: `railway.toml` (Nixpacks, `pip install uv && uv sync --no-dev`, `uvicorn app.main:app`, healthcheck `/health`) + `nixpacks.toml` (pins `providers = ["python"]`).
- **Frontend** (`web/`) → **Netlify**. Config: `netlify.toml` with `base = "web/"`, `publish = ".next"`, `@netlify/plugin-nextjs`, Node 20.

**Do NOT add a root `package.json`.** Nixpacks will see it and pick the Node.js provider instead of Python, breaking the backend build with `pip: command not found`. All JS/Node config must live under `web/`.

**Railway env vars** (set in dashboard): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_SECRET`, `ENVIRONMENT=production`, `FRONTEND_URL`, `CORS_ORIGINS_RAW`, `GEMINI_API_KEY` (required — Gemini is the default LLM provider). Optional: `LLM_PROVIDER` (defaults to `gemini`, set to `openai`/`perplexity`/`claude` only if switching), `ENCRYPTION_KEY`, `STRIPE_*`, `SMTP_*`, `OPENAI_API_KEY` / `PERPLEXITY_API_KEY` / `ANTHROPIC_API_KEY` (only if using an alternative provider).

**Netlify env vars** (set in dashboard): `NEXT_PUBLIC_API_BASE_URL` (Railway URL, consumed by `web/lib/api.ts:1`), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.

**Cross-origin wiring:** after first deploys, set Netlify's `NEXT_PUBLIC_API_BASE_URL` to the Railway URL and Railway's `FRONTEND_URL` / `CORS_ORIGINS_RAW` to the Netlify URL, then redeploy both sides.

## Migration Status

### SQLAlchemy → Supabase (Completed)

The project migrated from SQLAlchemy to Supabase Python SDK. Key changes:
- All database queries now use `supabase-py` via `app/db/tables/*` helpers
- `app/db/supabase_client.py` provides the singleton client
- Route files updated to use `supabase: Client = Depends(get_supabase)` instead of `db: Session = Depends(get_db)`
- Services updated to use Supabase client

### React 18 → React 19 (Completed - 2026-04-11)

Upgraded frontend to React 19 to resolve peer dependency conflicts with vite@8. Changes:
- `react` and `react-dom`: `18.3.1` → `^19.0.0`
- `@types/react` and `@types/react-dom`: `18.x` → `^19.0.0`
- `@types/node`: `22.10.5` → `22.15.0` (required by vite@8)
- No code changes required — existing patterns were already React 19 compatible

---

## Quick Reference: Supabase SDK Patterns

**Always use these patterns — copy and adapt:**

### Basic Queries
```python
from supabase import Client

# Get single record by ID
result = db.table("projects").select("*").eq("id", project_id).execute()
project = result.data[0] if result.data else None

# List with filter
result = db.table("opportunities").select("*").eq("project_id", pid).eq("status", "new").execute()
items = list(result.data)

# List with ordering
result = (
    db.table("personas")
    .select("*")
    .eq("project_id", pid)
    .order("created_at", desc=True)
    .execute()
)

# Pagination
result = db.table("keywords").select("*").eq("project_id", pid).range(0, 19).execute()  # 20 items
```

### Inserts and Updates
```python
# Single insert
result = db.table("projects").insert({
    "workspace_id": workspace_id,
    "name": "My Project",
    "slug": "my-project",
}).execute()
project = result.data[0]

# Bulk insert
result = db.table("opportunities").insert(list_of_opportunity_dicts).execute()

# Update
result = db.table("workspaces").update({"name": "New Name"}).eq("id", workspace_id).execute()
updated = result.data[0] if result.data else None
```

### Deletes
```python
# Single delete
db.table("invitations").delete().eq("id", invitation_id).execute()

# Conditional delete
db.table("keywords").delete().eq("project_id", project_id).eq("is_active", False).execute()
```

### Advanced Queries
```python
# IN clause
workspace_ids = [m["workspace_id"] for m in memberships]
result = db.table("workspaces").select("*").in_("id", workspace_ids).execute()

# Count (exact)
result = db.table("opportunities").select("id", count="exact").eq("project_id", pid).execute()
count = result.count if result.count else 0

# Multiple filters
result = (
    db.table("opportunities")
    .select("*")
    .eq("project_id", pid)
    .eq("status", "new")
    .gte("score", 50)
    .execute()
)

# Like / ilike
result = db.table("keywords").select("*").eq("project_id", pid).ilike("keyword", "%search%").execute()
```

### Type Hints for Table Operations
```python
from typing import Any

def get_entity_by_id(db: Client, entity_id: int) -> dict[str, Any] | None:
    """Get single record or None."""
    result = db.table("entities").select("*").eq("id", entity_id).execute()
    return result.data[0] if result.data else None

def list_entities(db: Client, project_id: int) -> list[dict[str, Any]]:
    """List records."""
    result = db.table("entities").select("*").eq("project_id", project_id).execute()
    return list(result.data)

def create_entity(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create and return the new record."""
    result = db.table("entities").insert(data).execute()
    return result.data[0]
```

---

## Quick Reference: Pydantic v2 Patterns

**Always use these patterns — copy and adapt:**

### Response Models (from database)
```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # Required for .model_validate()
    
    id: int
    project_id: int
    reddit_post_id: str
    subreddit_name: str
    title: str
    permalink: str
    score: int
    status: str
    created_at: datetime
    updated_at: datetime
```

### Request Models (from JSON)
```python
class OpportunityCreateRequest(BaseModel):
    reddit_post_id: str
    subreddit_name: str = Field(min_length=2, max_length=255)
    title: str = Field(min_length=2, max_length=500)
    score: int = Field(default=0, ge=0, le=100)
    status: str = Field(default="new", pattern="^(new|saved|drafting|posted|ignored)$")
```

### Field Validation Constraints
```python
# String constraints
name: str = Field(min_length=1, max_length=255)
description: str | None = Field(default=None, max_length=4000)

# Numeric constraints
score: int = Field(default=50, ge=0, le=100)  # >= 0, <= 100
priority: int = Field(default=1, gt=0)  # > 0

# Pattern (regex)
status: str = Field(pattern="^(active|archived)$")

# With description
name: str = Field(min_length=2, max_length=255, description="Project name")
```

### Model Validator (v2)
```python
from pydantic import model_validator

class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_secret_key: str = ""
    
    @model_validator(mode="after")
    def validate_prod(self) -> "Settings":
        if self.environment == "production" and not self.supabase_url:
            raise ValueError("SUPABASE_URL required")
        return self
```

### Usage in Routes
```python
# Single record
@router.get("/projects/{project_id}")
def get_project(project_id: int, supabase: Client = Depends(get_supabase)) -> ProjectResponse:
    project = get_project_by_id(supabase, project_id)
    return ProjectResponse.model_validate(project)

# List
@router.get("/projects")
def list_projects(supabase: Client = Depends(get_supabase)) -> list[ProjectResponse]:
    projects = list_projects_for_workspace(supabase, workspace_id)
    return [ProjectResponse.model_validate(p) for p in projects]

# Create
@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreateRequest, supabase: Client = Depends(get_supabase)) -> ProjectResponse:
    project = create_project(supabase, {"name": payload.name, ...})
    return ProjectResponse.model_validate(project)
```

---

## Quick Reference: Route Handler Template

```python
from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client
from app.api.v1.deps import get_current_user, get_current_workspace, ensure_workspace_membership
from app.db.supabase_client import get_supabase
from app.db.tables.<domain> import <list_entities>, <create_entity>, <get_entity_by_id>
from app.schemas.v1.<domain> import <EntityResponse>, <EntityCreateRequest>

router = APIRouter(prefix="/v1/<domain>", tags=["<domain>"])

@router.get("/entities", response_model=list[<EntityResponse>])
def list_entities_endpoint(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[<EntityResponse>]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    entities = <list_entities>(supabase, workspace["id"])
    return [<EntityResponse>.model_validate(e) for e in entities]

@router.post("/entities", response_model=<EntityResponse>, status_code=status.HTTP_201_CREATED)
def create_entity_endpoint(
    payload: <EntityCreateRequest>,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> <EntityResponse>:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    entity_data = payload.model_dump()
    entity = <create_entity>(supabase, entity_data)
    return <EntityResponse>.model_validate(entity)
```

---

## Multi-Agent Platform (Added 2026-06)

### New Services
- `app/services/agents/` — All agent implementations
- `app/services/product/brand_brain.py` — Website analysis and intelligence extraction
- `app/services/product/keyword_expansion.py` — Keyword universe generation
- `app/services/product/relevance_v2.py` — Composite relevance scoring engine
- `app/services/product/intent_classifier.py` — Heuristic intent classification
- `app/services/infrastructure/embeddings/` — Local embedding service (TF-IDF + optional sentence-transformers)
- `app/services/infrastructure/scheduler/` — Agent scheduler and orchestration
- `app/services/product/feedback_loop.py` — Learning from user feedback

### New Routes
- `/v1/company/*` — Company profile and Brand Brain
- `/v1/sources/*` — Source management
- `/v1/agents/*` — Agent runs and scheduling
- `/v1/feed/*` — Central opportunity feed
- `/v1/seo/*` — SEO agent
- `/v1/geo/*` — GEO agent
- `/v1/articles/*` — Articles agent
- `/v1/ugc/*` — UGC brief agent
- `/v1/technical-seo/*` — Technical SEO agent
- `/v1/manual-import/*` — X/LinkedIn manual import
- `/v1/analytics/v2/*` — Enhanced analytics
- `/v1/feedback/*` — Feedback submission

### New Frontend Pages
- `/app/company` — Company setup
- `/app/brand-brain` — Brand intelligence and keyword universe
- `/app/agents` — Central opportunity feed
- `/app/agent-runs` — Agent run logs and controls
- `/app/seo-geo` — SEO audit and GEO visibility
- `/app/content-studio` — Article briefs, X posts, LinkedIn posts, UGC briefs

## Critical Reference Files

**Study these for correct patterns:**

| File | Purpose |
|------|---------|
| `app/db/supabase_client.py` | Singleton client + `get_supabase()` dependency |
| `app/db/tables/discovery.py` | Table operations: personas, keywords, subreddits, opportunities |
| `app/db/tables/workspaces.py` | Workspaces, memberships, invitations, subscriptions |
| `app/db/tables/projects.py` | Projects, brand profiles, prompt templates |
| `app/schemas/v1/projects.py` | Clean Pydantic v2 request/response models |
| `app/schemas/v1/discovery.py` | Field validation, response models |
| `app/core/config.py` | Settings with `model_validator` |
| `app/api/v1/routes/projects.py` | Complete CRUD route patterns |
| `app/api/v1/deps.py` | Auth, workspace, and project helpers |
| `app/services/infrastructure/llm/service.py` | `LLMService` + `VisibilityRunner` facades |
| `app/services/infrastructure/llm/providers/openai_provider.py` | OpenAI provider pattern (reference for adding new providers) |

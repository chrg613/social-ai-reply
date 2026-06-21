#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# SignalFlow — One-Command Setup
# Usage: ./scripts/setup.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

info()  { echo -e "${BLUE}ℹ${NC}  $1"; }
ok()    { echo -e "${GREEN}✓${NC}  $1"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
fail()  { echo -e "${RED}✗${NC}  $1"; }

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  SignalFlow — Project Setup${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Detect project root ──────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── 1. Check prerequisites ──────────────────────────────────
echo -e "${BOLD}Step 1/5: Checking prerequisites${NC}"
MISSING=0

if command -v uv &>/dev/null; then
    ok "uv $(uv --version 2>/dev/null | head -1)"
else
    fail "uv not found — install from https://docs.astral.sh/uv/getting-started/installation/"
    MISSING=1
fi

if command -v node &>/dev/null; then
    ok "Node.js $(node --version)"
else
    fail "Node.js not found — install Node 20+ from https://nodejs.org/"
    MISSING=1
fi

if command -v npm &>/dev/null; then
    ok "npm $(npm --version)"
else
    fail "npm not found — comes with Node.js"
    MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
    echo ""
    fail "Install missing prerequisites and re-run this script."
    exit 1
fi
echo ""

# ── 2. Backend .env ──────────────────────────────────────────
echo -e "${BOLD}Step 2/5: Setting up environment files${NC}"

if [ -f .env ]; then
    ok "Backend .env already exists"
else
    cp .env.example .env
    ok "Created .env from .env.example"
    warn "Edit .env with your Supabase credentials before starting the server"
fi

# Frontend .env.local
if [ -f web/.env.local ]; then
    ok "Frontend web/.env.local already exists"
else
    cp web/.env.local.example web/.env.local
    ok "Created web/.env.local from web/.env.local.example"
    warn "Edit web/.env.local with your Supabase URL and publishable key"
fi
echo ""

# ── 3. Install backend dependencies ─────────────────────────
echo -e "${BOLD}Step 3/5: Installing backend dependencies${NC}"
uv sync --extra dev
ok "Backend dependencies installed"
echo ""

# ── 4. Install frontend dependencies ────────────────────────
echo -e "${BOLD}Step 4/5: Installing frontend dependencies${NC}"
(cd web && npm install)
ok "Frontend dependencies installed"
echo ""

# ── 5. Database schema ──────────────────────────────────────
echo -e "${BOLD}Step 5/5: Database setup${NC}"
echo ""
info "You need to run the initial schema SQL against your Supabase database."
info "The schema file is: ${BOLD}supabase/migrations/00000000000000_initial_schema.sql${NC}"
echo ""
info "Option A: ${BOLD}Supabase Dashboard${NC} (easiest)"
info "  1. Go to your Supabase project → SQL Editor"
info "  2. Paste the contents of the schema file"
info "  3. Click Run"
echo ""
info "Option B: ${BOLD}Supabase CLI${NC} (if you have Docker)"
info "  supabase db push"
echo ""

# ── Done ─────────────────────────────────────────────────────
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  Setup complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit .env and web/.env.local with your Supabase credentials"
echo "     (Get them from https://supabase.com/dashboard → your project → Settings → API)"
echo ""
echo "  2. Run the database schema (see above)"
echo ""
echo "  3. Start the servers:"
echo "     ${BOLD}Backend:${NC}  uv run uvicorn app.main:app --reload"
echo "     ${BOLD}Frontend:${NC} cd web && npm run dev"
echo ""
echo "  4. Open http://localhost:3000 and register an account"
echo ""

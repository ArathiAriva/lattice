# Lattice — Agent Guide

A curiosity-driven learning app. You explore topics with an AI tutor, promote ideas worth keeping into a personal knowledge graph of atomic **cards**, link them with typed edges, annotate with scratch notes, and retain them through free-form active recall scheduled by **FSRS**. Learning project — prototype quality is fine; keep the agent-loop and learning-science patterns clean, they're the point. Sibling of `../constellation`.

## Architecture

- `backend/` — FastAPI + SQLite (async SQLAlchemy). Agent loop calls OpenRouter (OpenAI-compatible) with tool calling. Port **8020**.
- `frontend/` — Next.js + D3 force graph. Three surfaces: chat (streams NDJSON), lattice graph, review mode. Port **3020**.
- `mcp-server/` — FastMCP stdio server, keyless lookups (Wikipedia, Semantic Scholar, DuckDuckGo). Spawned as a backend subprocess.

Ports are coordinated with siblings: voyager 8000/3000, constellation 8010/3010, **lattice 8020/3020**. Don't change them.

## Data model (`backend/app/models.py`)

`topics`, `cards` (atomic idea: title/body/kind/confidence/source_url + FSRS state + `due`), `links` (typed edges: builds_on|example_of|contradicts|related, with a `reason`), `notes` (scratch thoughts on a card or topic — never quiz material), `reviews` (retrieval log), `conversations`, `messages`. Topic clusters are computed on read, not stored.

## Learning science

- **FSRS** (`app/scheduler.py`) is the only place touching the `fsrs` package. Cards store state as a JSON blob + denormalized `due` for cheap queue queries.
- **Free-form recall** (`app/review.py`): LLM generates a question, grades the user's own-words answer, maps it to an FSRS rating the user can override (`/api/review/answer` grades but doesn't commit; `/api/review/commit` applies).
- **Daily cap** (`LATTICE_REVIEW_CAP`, default 20) so reviews never become homework.
- **Inline retrieval**: the `quiz_card` tool lets the agent quiz a *due* card mid-conversation; a graded answer counts as a review (interleaving in fresh context).
- **Confidence** on every card: verified (source-checked, has source_url) | heard (podcast-level) | unsure.

## Agent (`app/agent.py`, `app/tools.py`)

Same streaming generator + propose/confirm pattern as constellation. `propose_card` never writes — it emits a UI chip; `/api/cards/confirm` does the write (user can edit first). Tools: get_graph, get_card, propose_card, link_cards, update_card, add_note, quiz_card, plus MCP lookups. Events: status / token / proposal / question / done.

## Running

```bash
# backend (from backend/): create venv, pip install -r requirements.txt, put OPENROUTER_API_KEY in .env
python seed.py            # optional neuroscience starter graph
bash scripts/run.sh       # port 8020; kills stale process on the port
# frontend (from frontend/)
npm install && npm run dev # port 3020
```

## Verify before declaring done

- `cd backend && python -m pytest` — covers FSRS scheduling, confirm-write path, review grade/commit contract, links/notes CRUD (LLM + MCP stubbed, runs offline).
- `cd frontend && npx tsc --noEmit` — type-check.
- Note: SQLite over a mounted/networked FS can throw "disk I/O error"; run tests against a local-disk DB path.

## Conventions

- Keep deps minimal; external integrations stay keyless.
- Card = one atomic idea. Richness lives in the body, links, and notes — not in bloated titles (keeps recall grading crisp).
- Confidence set honestly; the agent verifies `heard` claims via MCP when it matters.

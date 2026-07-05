# Lattice

A curiosity-driven learning app. You explore topics with an AI tutor, promote ideas worth keeping into a personal knowledge graph of atomic **cards**, link them with typed edges, annotate with scratch notes, and retain them through free-form active recall scheduled by **FSRS**.

## Architecture

- `backend/` — FastAPI + SQLite (async SQLAlchemy). Agent loop calls OpenRouter (OpenAI-compatible) with tool calling. Port **8020**.
- `frontend/` — Next.js + D3 force graph. Three surfaces: chat (streams NDJSON), lattice graph, review mode. Port **3020**.
- `mcp-server/` — FastMCP stdio server, keyless lookups (Wikipedia, Semantic Scholar, DuckDuckGo). Spawned as a backend subprocess.

## Data model

`topics`, `cards` (atomic idea: title/body/kind/confidence/source_url + FSRS state + `due`), `links` (typed edges: builds_on|example_of|contradicts|related, with a `reason`), `notes` (scratch thoughts on a card or topic — never quiz material), `reviews` (retrieval log), `conversations`, `messages`.

## Learning science

- **FSRS** schedules retrieval; cards store state as a JSON blob plus a denormalized `due` for cheap queue queries.
- **Free-form recall**: the LLM generates a question, grades your own-words answer, and maps it to an FSRS rating you can override.
- **Daily cap** (`LATTICE_REVIEW_CAP`, default 20) so reviews never become homework.
- **Inline retrieval**: the agent can quiz a due card mid-conversation; a graded answer counts as a review.
- **Confidence** on every card: verified (source-checked) | heard (podcast-level) | unsure.

## Running

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your OPENROUTER_API_KEY
python seed.py         # optional neuroscience starter graph
bash scripts/run.sh    # http://localhost:8020

# frontend
cd frontend
npm install && npm run dev   # http://localhost:3020
```

## Testing

```bash
cd backend && python -m pytest
cd frontend && npx tsc --noEmit
```

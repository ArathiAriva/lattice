# Lattice — Spec

A curiosity-driven learning companion. You explore topics in conversation with an AI tutor, promote ideas worth keeping into a personal knowledge graph of atomic **cards**, link them with typed edges, annotate them with scratch notes, and retain them through free-form active recall scheduled by FSRS.

Sibling of `../constellation` — same architecture, adapted.

## Architecture

- `backend/` — FastAPI + SQLite (async SQLAlchemy). Agent loop with tool calling via OpenRouter (OpenAI-compatible client). Port **8020**.
- `frontend/` — Next.js + D3 force graph. Chat pane streams NDJSON; graph pane renders cards/links/topic clusters; review pane for recall sessions. Port **3020**.
- `mcp-server/` — FastMCP stdio server, spawned as backend subprocess, keyless lookups:
  - `wikipedia_summary(title)` — REST API summary + extract
  - `wikipedia_search(query)`
  - `semantic_scholar_search(query)` — paper titles/abstracts/links for going deeper
  - `web_lookup(query)` — DuckDuckGo instant-answer style fallback for credible sources

Ports 8000/3000 (voyager) and 8010/3010 (constellation) are taken — lattice uses **8020/3020**.

## Learning-science commitments

- **Active recall, free-form**: reviews present a question; the user answers in their own words; the LLM grades (correct / partially / missed), explains what was missed, and maps the grade to an FSRS rating (again/hard/good/easy). User can override the rating.
- **Spaced repetition via FSRS**: use the `fsrs` PyPI package. Each card stores FSRS state (stability, difficulty, due, state, last_review as JSON). Daily review queue = cards with `due <= now`, capped (default 20) so reviews never become homework.
- **Interleaving / retrieval in context**: when a due card's topic comes up during exploration, the agent may quiz it inline (`quiz_card` tool); a graded inline answer counts as a review.
- **Elaboration**: scratch notes and user-authored links are first-class — connecting new ideas to old ones is itself encoded learning.
- **Verification**: cards carry `confidence`: `verified` (checked against a source; store `source_url`) | `heard` (podcast-level) | `unsure`. The agent encourages verifying `heard` cards via MCP lookups.

## Data model (`backend/app/models.py`)

All tables use 12-hex-char string ids and ISO timestamp strings (constellation convention).

- **topics** — id, name (unique, case-insensitive lookup), description, created_at. Lightweight grouping; a card belongs to one topic; topics can emerge mid-conversation.
- **cards** — id, topic_id FK, title (the atomic idea, one sentence-ish), body (fuller explanation, markdown), kind (`fact` | `concept` | `mechanism` | `question`), confidence (`verified` | `heard` | `unsure`), source_url, fsrs_state (JSON text), due (ISO, indexed), created_at.
- **links** — id, from_id FK, to_id FK, kind (`builds_on` | `example_of` | `contradicts` | `related`), reason (text — why they're linked), created_at.
- **notes** — id, card_id FK nullable, topic_id FK nullable, content (markdown), created_at, updated_at. Scratch thoughts; exactly one of card_id/topic_id set.
- **reviews** — id, card_id FK, question, user_answer, grade (`again`|`hard`|`good`|`easy`), feedback (LLM's gap analysis), mode (`session` | `inline`), created_at. Review log; FSRS state on the card is updated per review.
- **conversations**, **messages** — as in constellation.

Clusters are not stored: the graph view groups by topic and by connected components, computed on read.

## Agent (`backend/app/agent.py`)

Same streaming generator pattern as constellation: events `status`, `token`, `proposal`, `question` (inline quiz), `done` (with `graph_changed`).

Persona: a curious tutor and fellow explorer, not a lecturer. Behaviors baked into the system prompt:

- Explain topics at the user's level; always surface 2–3 *specific* adjacent concepts as threads to pull ("this connects to reward prediction error, which is where neuroscience meets reinforcement learning").
- When an idea seems worth keeping, call `propose_card` — emits a UI chip (title, body, kind, topic, suggested links with reasons); **never writes**. `/api/cards/confirm` does the write, mirroring constellation's propose/confirm pattern. The user can edit the card text in the chip before confirming.
- Propose links only with a specific reason; a card with zero links seeding a new area is fine and said so.
- For factual claims, verify via MCP tools when unsure; set `confidence` honestly and include `source_url` when verified.
- Call `get_graph` early in a conversation; mention due-card count gently ("3 cards from synaptic plasticity are due — want a quick pass, or keep exploring?").
- When conversation touches a due card, use `quiz_card` for an inline retrieval attempt.

### Tools (`backend/app/tools.py`)

| tool | writes? | purpose |
|---|---|---|
| `get_graph` | no | topics, cards (title/kind/due), links — the agent's map |
| `get_card` | no | full card incl. body, notes, review history |
| `propose_card` | no | emit confirmation chip (card + suggested links) |
| `link_cards` | yes | typed edge with reason |
| `update_card` | yes | body/kind/confidence/source_url edits agreed in chat |
| `add_note` | yes | scratch note on card/topic when user muses |
| `quiz_card` | no | emit inline `question` event for a due card |
| `wikipedia_search` / `wikipedia_summary` / `semantic_scholar_search` / `web_lookup` | no | MCP lookups |

## API (`backend/app/main.py`)

- `POST /api/chat` — NDJSON stream (conversation_id, message)
- `GET /api/graph` — full graph for D3 (nodes: cards colored by topic, sized by FSRS stability; edges: links)
- `POST /api/cards/confirm` — write proposed card + links (the only agent-mutation confirm path)
- `GET/PATCH/DELETE /api/cards/{id}`; `GET /api/cards?topic=`
- `POST/PATCH/DELETE /api/links`, `/api/notes`
- `GET /api/review/queue` — due cards (capped)
- `POST /api/review/answer` — {card_id, question, answer} → LLM grades → returns feedback + suggested FSRS rating
- `POST /api/review/commit` — {card_id, rating} → update FSRS state (rating may be user-overridden)
- `GET/POST /api/conversations`, `GET /api/topics`

## Frontend (Next.js, port 3020)

Three-pane single page, matching constellation's chat+graph layout plus a review surface:

1. **Chat pane** — streaming conversation; proposal chips (editable card preview → Confirm/Dismiss); inline quiz cards (question → textarea → graded feedback).
2. **Graph pane** — D3 force graph. Nodes = cards, colored by topic, halo/pulse when due; edge styles by link kind. Click node → card drawer: body, confidence badge, source link, scratch notes (inline editable), review history, manual "quiz me now".
3. **Review mode** — toggle/route showing today's queue: question → free-form answer → LLM feedback with gaps highlighted → accept/override rating → next. Shows streak and remaining count.

## Conventions

- Keep deps minimal; external integrations keyless.
- `.env` with `OPENROUTER_API_KEY`; `scripts/run.sh` mirrors constellation (venv activation, port cleanup).
- Tests: pytest with stubbed LLM (constellation's pattern); cover FSRS scheduling, confirm-write path, review grading endpoint contract.
- Seed script with a small neuroscience starter graph (optional).

## Build order

1. Backend skeleton: models, db, FSRS integration, CRUD + review endpoints, tests
2. MCP server (wikipedia/semantic scholar/web lookup)
3. Agent loop + tools + propose/confirm
4. Frontend: chat + chips, graph, card drawer, review mode
5. Seed data, run scripts, smoke test end-to-end

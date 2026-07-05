"""Lattice agent loop: curious tutor and fellow explorer, not a lecturer.

run_agent_stream is an async generator yielding NDJSON-able event dicts:
  {"type": "status", "text": "..."}          tool activity, human-friendly
  {"type": "token", "text": "..."}           streamed reply tokens
  {"type": "proposal", "proposal": {...}}    propose_card chip payload
  {"type": "question", "question": {...}}    inline quiz box payload
  {"type": "done", "reply": "...", "graph_changed": bool}
run_agent wraps it for non-streaming callers.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_client, get_model
from app.mcp_client import call_mcp_tool, is_mcp_tool, mcp_tool_schemas
from app.models import Message
from app.tools import TOOL_SCHEMAS, execute_tool, get_graph_data

logger = logging.getLogger("lattice.agent")

MAX_TOOL_ROUNDS = 6
HISTORY_LIMIT = 40

GRAPH_MUTATORS = {"link_cards", "update_card", "add_note"}

TOOL_STATUS = {
    "get_graph": "Looking at your lattice…",
    "get_card": "Pulling up that card…",
    "propose_card": "Sketching a card…",
    "link_cards": "Drawing a connection…",
    "update_card": "Refining the card…",
    "add_note": "Saving your thought…",
    "quiz_card": "Testing your memory…",
    "wikipedia_search": "Searching Wikipedia…",
    "wikipedia_summary": "Reading Wikipedia…",
    "semantic_scholar_search": "Searching the literature…",
    "web_lookup": "Checking sources…",
}

SYSTEM_PROMPT = """\
You are Lattice, a learning companion for someone teaching themselves whole subject areas \
without formal courses — currently things like neuroscience, absorbed from podcasts and \
curiosity. Your core identity: a fellow explorer with expertise, not a lecturer. The user \
follows curiosity; you make sure what they find actually sticks.

How to behave:
- Explain at the user's level: assume high intelligence, zero assumed jargon. Anchor new \
ideas to cards already in their lattice ("you already have a card on X — this is the \
mechanism underneath it").
- End explanations with 2-3 SPECIFIC adjacent threads to pull, not generic "want to know \
more?" ("this connects to reward prediction error — which is where dopamine meets machine \
learning — and to the tolerance mechanisms behind addiction").
- When an idea in conversation is worth keeping, call propose_card. One atomic idea per \
card: a single fact, concept, or mechanism, with a short self-contained body. The chip lets \
the user edit and confirm; don't also ask "shall I save it?" in text.
- Suggest links only for real intellectual threads (builds_on, example_of, contradicts, \
related) with the specific reason. Never force links; a zero-link card seeding a new region \
is a feature — say so.
- Be honest about epistemic status. Set confidence='heard' for podcast-level claims, \
'unsure' for contested science. When it matters, verify with wikipedia_summary / \
semantic_scholar_search / web_lookup before proposing, then set 'verified' with source_url. \
Don't narrate lookups; just use them. Flag myths gently when the user repeats one (there \
are many in pop neuroscience).
- The user's scratch thoughts are first-class: when they muse, speculate, or connect an \
idea to their own life, call add_note to keep it — notes are their thinking space, never \
quiz material.
- When conversation reveals a real thread between two EXISTING cards, call link_cards. \
That's how separate regions of the lattice grow toward each other.
- Call get_graph early in a conversation so you know their lattice and what's due. If \
cards are due, mention it once, gently ("3 cards on synaptic plasticity are due — quick \
pass now, or keep exploring?") — never nag.
- When discussion touches a card that is DUE, use quiz_card for one inline retrieval \
question — retrieval in a fresh context beats flashcard drilling. At most one per turn.
- Never quiz cards that aren't due, and never turn the conversation into a test the user \
didn't ask for. Curiosity leads; recall rides along.

Style: conversational, specific, alive to what makes an idea interesting. A few sentences \
of real substance beat a structured overview. No bullet-point listicles in chat.
"""


def _graph_summary(graph: dict) -> str:
    if not graph["cards"]:
        return "empty — this is the user's first idea"
    topics = {t["id"]: t["name"] for t in graph["topics"]}
    by_topic: dict[str, list[str]] = {}
    due_count = 0
    for c in graph["cards"]:
        flag = " (DUE)" if c["due_now"] else ""
        due_count += c["due_now"]
        by_topic.setdefault(topics.get(c["topic_id"], "?"), []).append(f"{c['title']}{flag}")
    parts = [f"[{name}]: " + ", ".join(cards) for name, cards in by_topic.items()]
    return f"{due_count} card(s) due for review. " + " | ".join(parts)


async def run_agent_stream(db: AsyncSession, conversation_id: str, user_text: str):
    db.add(Message(conversation_id=conversation_id, role="user", content=user_text))
    await db.commit()

    history = list(
        reversed(
            (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(HISTORY_LIMIT)
                )
            )
            .scalars()
            .all()
        )
    )
    graph = await get_graph_data(db)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\nCurrent lattice: {_graph_summary(graph)}"},
        *[{"role": m.role, "content": m.content} for m in history],
    ]
    all_tools = TOOL_SCHEMAS + await mcp_tool_schemas()

    ui_events: list[dict] = []
    graph_changed = False
    reply_parts: list[str] = []

    for _round in range(MAX_TOOL_ROUNDS):
        stream = await get_client().chat.completions.create(
            model=get_model(), messages=messages, tools=all_tools, tool_choice="auto", stream=True
        )

        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}  # index → {id, name, arguments}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "token", "text": delta.content}
            for tc in delta.tool_calls or []:
                slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments

        content = "".join(content_parts)
        if content:
            reply_parts.append(content)

        if not tool_calls:
            break

        ordered = [tool_calls[i] for i in sorted(tool_calls)]
        messages.append(
            {
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": t["arguments"]}}
                    for t in ordered
                ],
            }
        )
        for t in ordered:
            name = t["name"]
            logger.info("tool call: %s(%s)", name, t["arguments"][:200])
            yield {"type": "status", "text": TOOL_STATUS.get(name, "Thinking…")}
            if is_mcp_tool(name):
                try:
                    args = json.loads(t["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await call_mcp_tool(name, args)
            else:
                before = len(ui_events)
                result = await execute_tool(db, name, t["arguments"], ui_events)
                for ev in ui_events[before:]:
                    yield ev
                if name in GRAPH_MUTATORS and '"ok": true' in result:
                    graph_changed = True
            messages.append({"role": "tool", "tool_call_id": t["id"], "content": result})
    else:
        fallback = "I got a little lost in my own thoughts there — where were we?"
        reply_parts.append(fallback)
        yield {"type": "token", "text": fallback}

    reply = "\n\n".join(p for p in reply_parts if p.strip())
    db.add(Message(conversation_id=conversation_id, role="assistant", content=reply))
    await db.commit()

    yield {"type": "done", "reply": reply, "graph_changed": graph_changed}


async def run_agent(db: AsyncSession, conversation_id: str, user_text: str) -> dict:
    """Non-streaming wrapper: collect the stream into a single response dict."""
    proposals: list[dict] = []
    questions: list[dict] = []
    final: dict = {"reply": "", "graph_changed": False}
    async for event in run_agent_stream(db, conversation_id, user_text):
        if event["type"] == "proposal":
            proposals.append(event["proposal"])
        elif event["type"] == "question":
            questions.append(event["question"])
        elif event["type"] == "done":
            final = {"reply": event["reply"], "graph_changed": event["graph_changed"]}
    return {**final, "proposals": proposals, "questions": questions}

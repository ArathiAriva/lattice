"""Tool schemas + executors for the Lattice agent.

Two kinds of effects:
  - DB mutations (link_cards, update_card, add_note)
  - UI events (propose_card → confirmation chip; quiz_card → inline question)
propose_card never writes: /api/cards/confirm does, after the user accepts.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, Link, Note, Review, Topic
from app.scheduler import new_card_state, stability

logger = logging.getLogger("lattice.tools")

CARD_KINDS = ["fact", "concept", "mechanism", "question"]
LINK_KINDS = ["builds_on", "example_of", "contradicts", "related"]
CONFIDENCES = ["verified", "heard", "unsure"]

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_graph",
            "description": (
                "Fetch the user's full lattice: every topic, every card (with kind, confidence, "
                "and whether it's due for review), and every link between cards. Call this early "
                "in a conversation so proposals connect to what actually exists and you know "
                "which cards are due."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_card",
            "description": "Fetch one card in full: body, source, scratch notes, and review history. Identify by exact title or id.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "card_id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_card",
            "description": (
                "Propose adding an atomic idea to the user's lattice. Shows a confirmation chip in "
                "the UI (the user can edit before accepting); nothing is saved until they confirm. "
                "Use when an idea in conversation seems worth keeping. Keep the title to ONE idea — "
                "a single fact, concept, or mechanism — and the body a short, self-contained "
                "explanation. Suggest links to existing cards only with a specific reason (the actual "
                "intellectual thread, not 'same topic'). Zero links is fine — it seeds a new region. "
                "Set confidence honestly: 'verified' only if checked against a source this "
                "conversation (include source_url), 'heard' for podcast-level knowledge, 'unsure' "
                "if contested or fuzzy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The atomic idea, one sentence."},
                    "body": {"type": "string", "description": "Short self-contained explanation, markdown ok."},
                    "kind": {"type": "string", "enum": CARD_KINDS},
                    "topic": {"type": "string", "description": "Topic name; created if new."},
                    "confidence": {"type": "string", "enum": CONFIDENCES},
                    "source_url": {"type": "string"},
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "to_title": {"type": "string", "description": "Exact title of an existing card."},
                                "kind": {"type": "string", "enum": LINK_KINDS},
                                "reason": {"type": "string", "description": "The specific thread, one sentence."},
                            },
                            "required": ["to_title", "kind", "reason"],
                        },
                    },
                },
                "required": ["title", "body", "kind", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_cards",
            "description": (
                "Draw a typed edge between two existing cards when conversation reveals a real "
                "thread between them. Kinds: builds_on, example_of, contradicts, related. Always "
                "give the specific reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_title": {"type": "string"},
                    "to_title": {"type": "string"},
                    "kind": {"type": "string", "enum": LINK_KINDS},
                    "reason": {"type": "string"},
                },
                "required": ["from_title", "to_title", "kind", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_card",
            "description": (
                "Update an existing card after agreeing with the user in chat — refine the body, "
                "correct the kind, or upgrade confidence after verifying against a source "
                "(then include source_url)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Exact title of the card to update."},
                    "body": {"type": "string"},
                    "kind": {"type": "string", "enum": CARD_KINDS},
                    "confidence": {"type": "string", "enum": CONFIDENCES},
                    "source_url": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": (
                "Save the user's own musing or hunch as a scratch note on a card or topic — when "
                "they wonder aloud, connect something to their own life, or disagree with a claim. "
                "Notes are the user's thinking space, never quiz material. Attach to a card by "
                "exact title, or to a topic by name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The note, in the user's spirit."},
                    "card_title": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quiz_card",
            "description": (
                "When conversation touches a card that is DUE for review (get_graph shows due "
                "flags), pose an inline retrieval question about it. Shows a quiz box in the UI; "
                "the user's graded answer counts as a review. Use sparingly — at most one per "
                "conversation turn, only when genuinely adjacent to the discussion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_title": {"type": "string", "description": "Exact title of the due card."},
                    "question": {
                        "type": "string",
                        "description": "An open question requiring genuine retrieval — not yes/no.",
                    },
                },
                "required": ["card_title", "question"],
            },
        },
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _find_card(db: AsyncSession, title: str) -> Card | None:
    return (
        await db.execute(select(Card).where(func.lower(Card.title) == title.lower()))
    ).scalar_one_or_none()


async def _find_or_create_topic(db: AsyncSession, name: str) -> Topic:
    topic = (
        await db.execute(select(Topic).where(func.lower(Topic.name) == name.lower()))
    ).scalar_one_or_none()
    if topic is None:
        topic = Topic(name=name)
        db.add(topic)
        await db.flush()
    return topic


async def get_graph_data(db: AsyncSession) -> dict:
    topics = (await db.execute(select(Topic))).scalars().all()
    cards = (await db.execute(select(Card))).scalars().all()
    links = (await db.execute(select(Link))).scalars().all()
    now = _now()
    return {
        "topics": [t.to_dict() for t in topics],
        "cards": [
            {**c.to_dict(), "due_now": c.due <= now, "stability": stability(c.fsrs_state)}
            for c in cards
        ],
        "links": [l.to_dict() for l in links],
    }


async def add_card_with_links(db: AsyncSession, data: dict) -> dict:
    """The confirm path: user accepted a propose_card chip (possibly edited)."""
    title = data["title"].strip()
    if not title:
        return {"error": "Card title is empty"}
    if await _find_card(db, title):
        return {"error": f"A card titled '{title}' already exists"}
    topic = await _find_or_create_topic(db, data.get("topic", "Misc").strip() or "Misc")
    state, due = new_card_state()
    card = Card(
        topic_id=topic.id,
        title=title,
        body=data.get("body", ""),
        kind=data.get("kind", "fact"),
        confidence=data.get("confidence", "heard"),
        source_url=data.get("source_url", ""),
        fsrs_state=state,
        due=due,
    )
    db.add(card)
    await db.flush()
    made_links, skipped = [], []
    for spec in data.get("links", []):
        target = await _find_card(db, spec.get("to_title", ""))
        if target is None:
            skipped.append(spec.get("to_title", "?"))
            continue
        link = Link(
            from_id=card.id,
            to_id=target.id,
            kind=spec.get("kind", "related"),
            reason=spec.get("reason", ""),
        )
        db.add(link)
        made_links.append(spec["to_title"])
    await db.commit()
    return {"ok": True, "card": card.to_dict(), "linked_to": made_links, "skipped": skipped}


async def execute_tool(db: AsyncSession, name: str, arguments: str, events: list[dict]) -> str:
    """Run a native tool; UI events (proposals/questions) are appended to `events`."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid tool arguments"})

    if name == "get_graph":
        return json.dumps(await get_graph_data(db))

    if name == "get_card":
        card = None
        if args.get("card_id"):
            card = (
                await db.execute(select(Card).where(Card.id == args["card_id"]))
            ).scalar_one_or_none()
        if card is None and args.get("title"):
            card = await _find_card(db, args["title"])
        if card is None:
            return json.dumps({"error": "Card not found"})
        notes = (
            (await db.execute(select(Note).where(Note.card_id == card.id))).scalars().all()
        )
        reviews = (
            (
                await db.execute(
                    select(Review)
                    .where(Review.card_id == card.id)
                    .order_by(Review.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        return json.dumps(
            {
                **card.to_dict(),
                "notes": [n.to_dict() for n in notes],
                "recent_reviews": [r.to_dict() for r in reviews],
            }
        )

    if name == "propose_card":
        proposal = {
            "title": args.get("title", ""),
            "body": args.get("body", ""),
            "kind": args.get("kind", "fact"),
            "topic": args.get("topic", "Misc"),
            "confidence": args.get("confidence", "heard"),
            "source_url": args.get("source_url", ""),
            "links": args.get("links", []),
        }
        events.append({"type": "proposal", "proposal": proposal})
        return json.dumps({"ok": True, "shown": "Confirmation chip shown; do not also ask in text."})

    if name == "link_cards":
        a = await _find_card(db, args.get("from_title", ""))
        b = await _find_card(db, args.get("to_title", ""))
        if a is None or b is None:
            return json.dumps({"error": "One or both cards not found"})
        if a.id == b.id:
            return json.dumps({"error": "Cannot link a card to itself"})
        db.add(Link(from_id=a.id, to_id=b.id, kind=args.get("kind", "related"), reason=args.get("reason", "")))
        await db.commit()
        return json.dumps({"ok": True})

    if name == "update_card":
        card = await _find_card(db, args.get("title", ""))
        if card is None:
            return json.dumps({"error": "Card not found"})
        for field in ("body", "kind", "confidence", "source_url"):
            if field in args and args[field]:
                setattr(card, field, args[field])
        await db.commit()
        return json.dumps({"ok": True, "card": card.to_dict()})

    if name == "add_note":
        note = Note(content=args.get("content", ""))
        if args.get("card_title"):
            card = await _find_card(db, args["card_title"])
            if card is None:
                return json.dumps({"error": "Card not found"})
            note.card_id = card.id
        elif args.get("topic"):
            topic = await _find_or_create_topic(db, args["topic"])
            note.topic_id = topic.id
        else:
            return json.dumps({"error": "Provide card_title or topic"})
        db.add(note)
        await db.commit()
        return json.dumps({"ok": True, "note": note.to_dict()})

    if name == "quiz_card":
        card = await _find_card(db, args.get("card_title", ""))
        if card is None:
            return json.dumps({"error": "Card not found"})
        events.append(
            {
                "type": "question",
                "question": {"card_id": card.id, "card_title": card.title, "question": args.get("question", "")},
            }
        )
        return json.dumps({"ok": True, "shown": "Quiz box shown; continue the conversation naturally."})

    return json.dumps({"error": f"Unknown tool: {name}"})

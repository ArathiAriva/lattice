from dotenv import load_dotenv

load_dotenv()

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import json  # noqa: E402
import os  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

import app.models  # noqa: F401, E402 — register ORM models
from app.agent import run_agent, run_agent_stream  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Card, Conversation, Link, Message, Note, Review, Topic  # noqa: E402
from app.review import generate_question, grade_answer  # noqa: E402
from app.scheduler import review_card  # noqa: E402
from app.tools import add_card_with_links, get_graph_data  # noqa: E402

REVIEW_DAILY_CAP = int(os.environ.get("LATTICE_REVIEW_CAP", "20"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Lattice API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3020"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


class ConfirmIn(BaseModel):
    title: str
    body: str = ""
    kind: str = "fact"
    topic: str = "Misc"
    confidence: str = "heard"
    source_url: str = ""
    links: list[dict] = []


class LinkIn(BaseModel):
    from_id: str
    to_id: str
    kind: str = "related"
    reason: str = ""


class NoteIn(BaseModel):
    content: str
    card_id: str | None = None
    topic_id: str | None = None


class AnswerIn(BaseModel):
    card_id: str
    question: str
    answer: str
    mode: str = "session"


class CommitIn(BaseModel):
    card_id: str
    rating: str
    question: str = ""
    answer: str = ""
    feedback: str = ""
    mode: str = "session"


# ---------- chat ----------


@app.post("/api/chat")
async def chat(body: ChatIn):
    async with SessionLocal() as db:
        conv_id = body.conversation_id
        if conv_id is None:
            conv = Conversation(title=body.message[:60])
            db.add(conv)
            await db.commit()
            conv_id = conv.id
        result = await run_agent(db, conv_id, body.message)
    return {**result, "conversation_id": conv_id}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn):
    """NDJSON stream of agent events: status / token / proposal / question / done."""

    async def gen():
        async with SessionLocal() as db:
            conv_id = body.conversation_id
            if conv_id is None:
                conv = Conversation(title=body.message[:60])
                db.add(conv)
                await db.commit()
                conv_id = conv.id
            yield json.dumps({"type": "conversation", "conversation_id": conv_id}) + "\n"
            try:
                async for event in run_agent_stream(db, conv_id, body.message):
                    yield json.dumps(event) + "\n"
            except Exception as exc:
                yield json.dumps({"type": "error", "text": str(exc)}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/api/conversations")
async def list_conversations():
    async with SessionLocal() as db:
        rows = (
            (await db.execute(select(Conversation).order_by(Conversation.created_at.desc())))
            .scalars()
            .all()
        )
        return [c.to_dict() for c in rows]


@app.get("/api/conversations/{conv_id}/messages")
async def conversation_messages(conv_id: str):
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [m.to_dict() for m in rows]


# ---------- graph / topics ----------


@app.get("/api/graph")
async def graph():
    async with SessionLocal() as db:
        return await get_graph_data(db)


@app.get("/api/topics")
async def list_topics():
    async with SessionLocal() as db:
        rows = (await db.execute(select(Topic).order_by(Topic.name))).scalars().all()
        return [t.to_dict() for t in rows]


# ---------- cards ----------


@app.post("/api/cards/confirm")
async def confirm_card(body: ConfirmIn):
    """User accepted (and possibly edited) a propose_card chip — actually save it."""
    async with SessionLocal() as db:
        result = await add_card_with_links(db, body.model_dump())
        if "error" in result:
            raise HTTPException(status_code=409, detail=result["error"])
        return result


@app.get("/api/cards/{card_id}")
async def get_card(card_id: str):
    async with SessionLocal() as db:
        card = (await db.execute(select(Card).where(Card.id == card_id))).scalar_one_or_none()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        notes = (await db.execute(select(Note).where(Note.card_id == card_id))).scalars().all()
        reviews = (
            (
                await db.execute(
                    select(Review).where(Review.card_id == card_id).order_by(Review.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return {
            **card.to_dict(),
            "notes": [n.to_dict() for n in notes],
            "reviews": [r.to_dict() for r in reviews],
        }


@app.patch("/api/cards/{card_id}")
async def patch_card(card_id: str, body: dict):
    async with SessionLocal() as db:
        card = (await db.execute(select(Card).where(Card.id == card_id))).scalar_one_or_none()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        for field in ("title", "body", "kind", "confidence", "source_url"):
            if field in body:
                setattr(card, field, body[field])
        await db.commit()
        return card.to_dict()


@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: str):
    async with SessionLocal() as db:
        await db.execute(delete(Link).where((Link.from_id == card_id) | (Link.to_id == card_id)))
        await db.execute(delete(Note).where(Note.card_id == card_id))
        await db.execute(delete(Review).where(Review.card_id == card_id))
        await db.execute(delete(Card).where(Card.id == card_id))
        await db.commit()
        return {"ok": True}


# ---------- links / notes ----------


@app.post("/api/links")
async def create_link(body: LinkIn):
    async with SessionLocal() as db:
        for cid in (body.from_id, body.to_id):
            if not (await db.execute(select(Card).where(Card.id == cid))).scalar_one_or_none():
                raise HTTPException(status_code=404, detail=f"Card {cid} not found")
        link = Link(**body.model_dump())
        db.add(link)
        await db.commit()
        return link.to_dict()


@app.delete("/api/links/{link_id}")
async def delete_link(link_id: str):
    async with SessionLocal() as db:
        await db.execute(delete(Link).where(Link.id == link_id))
        await db.commit()
        return {"ok": True}


@app.post("/api/notes")
async def create_note(body: NoteIn):
    if not (body.card_id or body.topic_id):
        raise HTTPException(status_code=422, detail="Provide card_id or topic_id")
    async with SessionLocal() as db:
        note = Note(**body.model_dump())
        db.add(note)
        await db.commit()
        return note.to_dict()


@app.patch("/api/notes/{note_id}")
async def patch_note(note_id: str, body: dict):
    async with SessionLocal() as db:
        note = (await db.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if "content" in body:
            note.content = body["content"]
            note.updated_at = _now()
        await db.commit()
        return note.to_dict()


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    async with SessionLocal() as db:
        await db.execute(delete(Note).where(Note.id == note_id))
        await db.commit()
        return {"ok": True}


# ---------- review ----------


@app.get("/api/review/queue")
async def review_queue():
    """Due cards, oldest first, capped so reviews never become homework."""
    async with SessionLocal() as db:
        now = _now()
        rows = (
            (
                await db.execute(
                    select(Card).where(Card.due <= now).order_by(Card.due).limit(REVIEW_DAILY_CAP)
                )
            )
            .scalars()
            .all()
        )
        total_due = len(
            (await db.execute(select(Card.id).where(Card.due <= now))).scalars().all()
        )
        return {"cards": [c.to_dict() for c in rows], "total_due": total_due, "cap": REVIEW_DAILY_CAP}


@app.get("/api/review/question/{card_id}")
async def review_question(card_id: str):
    async with SessionLocal() as db:
        card = (await db.execute(select(Card).where(Card.id == card_id))).scalar_one_or_none()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
    question = await generate_question(card.title, card.body, card.kind)
    return {"card_id": card_id, "question": question}


@app.post("/api/review/answer")
async def review_answer(body: AnswerIn):
    """Grade a free-form answer. Returns feedback + suggested rating; does NOT commit."""
    async with SessionLocal() as db:
        card = (await db.execute(select(Card).where(Card.id == body.card_id))).scalar_one_or_none()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
    graded = await grade_answer(card.title, card.body, body.question, body.answer)
    return {"card_id": body.card_id, **graded}


@app.post("/api/review/commit")
async def review_commit(body: CommitIn):
    """Apply a (possibly user-overridden) rating: update FSRS state, log the review."""
    async with SessionLocal() as db:
        card = (await db.execute(select(Card).where(Card.id == body.card_id))).scalar_one_or_none()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        try:
            card.fsrs_state, card.due = review_card(card.fsrs_state, body.rating)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        db.add(
            Review(
                card_id=card.id,
                question=body.question,
                user_answer=body.answer,
                grade=body.rating,
                feedback=body.feedback,
                mode=body.mode,
            )
        )
        await db.commit()
        return {"ok": True, "card": card.to_dict()}

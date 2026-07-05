import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
        }


class Card(Base):
    """An atomic idea worth keeping: one fact, concept, or mechanism."""

    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), index=True)
    title: Mapped[str] = mapped_column(String, index=True)  # the idea, one sentence-ish
    body: Mapped[str] = mapped_column(Text, default="")  # fuller explanation, markdown
    kind: Mapped[str] = mapped_column(String, default="fact")  # fact|concept|mechanism|question
    # verified (checked against a source) | heard (podcast-level) | unsure
    confidence: Mapped[str] = mapped_column(String, default="heard")
    source_url: Mapped[str] = mapped_column(String, default="")
    fsrs_state: Mapped[str] = mapped_column(Text, default="")  # JSON blob of FSRS card state
    due: Mapped[str] = mapped_column(String, default=_now, index=True)  # ISO timestamp
    created_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "title": self.title,
            "body": self.body,
            "kind": self.kind,
            "confidence": self.confidence,
            "source_url": self.source_url,
            "due": self.due,
            "created_at": self.created_at,
        }


class Link(Base):
    """Typed edge between two cards, with the reason they're linked."""

    __tablename__ = "links"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    from_id: Mapped[str] = mapped_column(String, ForeignKey("cards.id"), index=True)
    to_id: Mapped[str] = mapped_column(String, ForeignKey("cards.id"), index=True)
    kind: Mapped[str] = mapped_column(String, default="related")  # builds_on|example_of|contradicts|related
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "kind": self.kind,
            "reason": self.reason,
        }


class Note(Base):
    """Scratch thoughts — the user's own musings, attached to a card or a topic.
    Never quiz material."""

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    card_id: Mapped[str | None] = mapped_column(String, ForeignKey("cards.id"), nullable=True, index=True)
    topic_id: Mapped[str | None] = mapped_column(String, ForeignKey("topics.id"), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=_now)
    updated_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "card_id": self.card_id,
            "topic_id": self.topic_id,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Review(Base):
    """Log of one retrieval attempt (review session or inline quiz)."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    card_id: Mapped[str] = mapped_column(String, ForeignKey("cards.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    user_answer: Mapped[str] = mapped_column(Text, default="")
    grade: Mapped[str] = mapped_column(String)  # again|hard|good|easy
    feedback: Mapped[str] = mapped_column(Text, default="")  # LLM gap analysis
    mode: Mapped[str] = mapped_column(String, default="session")  # session|inline
    created_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "card_id": self.card_id,
            "question": self.question,
            "user_answer": self.user_answer,
            "grade": self.grade,
            "feedback": self.feedback,
            "mode": self.mode,
            "created_at": self.created_at,
        }


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    title: Mapped[str] = mapped_column(String, default="New exploration")
    created_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "created_at": self.created_at}


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }

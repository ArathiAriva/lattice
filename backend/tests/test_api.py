"""Lattice backend tests. LLM and MCP are stubbed so tests run offline.

Covers: FSRS scheduling, the propose→confirm write path, review grade/commit
contract, and links/notes CRUD.
"""

import os
import sys

import pytest
import pytest_asyncio

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ["LATTICE_DB"] = "sqlite+aiosqlite:///./test_lattice.db"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_card(client, title="Reward prediction error", topic="Neuroscience", links=None):
    resp = await client.post(
        "/api/cards/confirm",
        json={
            "title": title,
            "body": "Dopamine encodes the difference between expected and actual reward.",
            "kind": "mechanism",
            "topic": topic,
            "confidence": "heard",
            "links": links or [],
        },
    )
    return resp


# ---------- FSRS scheduler unit ----------


def test_fsrs_scheduling_pushes_due_forward():
    from app.scheduler import new_card_state, review_card

    state, due0 = new_card_state()
    state2, due_good = review_card(state, "good")
    _state3, due_easy = review_card(state, "easy")
    # A successful review schedules the next review strictly after creation.
    assert due_good > due0
    # "easy" should schedule no sooner than "good".
    assert due_easy >= due_good


def test_fsrs_invalid_rating():
    from app.scheduler import new_card_state, review_card

    state, _ = new_card_state()
    with pytest.raises(ValueError):
        review_card(state, "brilliant")


# ---------- confirm write path ----------


async def test_confirm_creates_card_and_topic(client):
    resp = await _make_card(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["card"]["title"] == "Reward prediction error"

    graph = (await client.get("/api/graph")).json()
    assert len(graph["cards"]) == 1
    assert len(graph["topics"]) == 1
    assert graph["cards"][0]["due_now"] is True  # brand-new cards are due immediately


async def test_confirm_rejects_duplicate_title(client):
    await _make_card(client)
    dup = await _make_card(client)
    assert dup.status_code == 409


async def test_confirm_with_link(client):
    await _make_card(client, title="Dopamine")
    resp = await _make_card(
        client,
        title="Temporal difference learning",
        topic="Machine learning",
        links=[{"to_title": "Dopamine", "kind": "related", "reason": "RPE is a TD error signal"}],
    )
    assert resp.status_code == 200
    assert resp.json()["linked_to"] == ["Dopamine"]
    graph = (await client.get("/api/graph")).json()
    assert len(graph["links"]) == 1
    assert graph["links"][0]["kind"] == "related"


# ---------- links / notes ----------


async def test_link_and_note_crud(client):
    a = (await _make_card(client, title="A")).json()["card"]["id"]
    b = (await _make_card(client, title="B")).json()["card"]["id"]

    link = await client.post("/api/links", json={"from_id": a, "to_id": b, "kind": "builds_on", "reason": "x"})
    assert link.status_code == 200

    note = await client.post("/api/notes", json={"card_id": a, "content": "my hunch"})
    assert note.status_code == 200
    note_id = note.json()["id"]

    card = (await client.get(f"/api/cards/{a}")).json()
    assert len(card["notes"]) == 1

    patched = await client.patch(f"/api/notes/{note_id}", json={"content": "revised hunch"})
    assert patched.json()["content"] == "revised hunch"


async def test_note_requires_target(client):
    resp = await client.post("/api/notes", json={"content": "orphan"})
    assert resp.status_code == 422


# ---------- review flow (grading stubbed) ----------


async def test_review_queue_and_commit(client, monkeypatch):
    card_id = (await _make_card(client)).json()["card"]["id"]

    queue = (await client.get("/api/review/queue")).json()
    assert queue["total_due"] == 1
    assert queue["cards"][0]["id"] == card_id

    async def fake_grade(title, body, question, answer):
        return {"rating": "good", "feedback": "Nailed the core idea; you omitted the sign."}

    monkeypatch.setattr("app.main.grade_answer", fake_grade)

    graded = await client.post(
        "/api/review/answer",
        json={"card_id": card_id, "question": "What does RPE encode?", "answer": "the surprise"},
    )
    assert graded.status_code == 200
    assert graded.json()["rating"] == "good"

    commit = await client.post(
        "/api/review/commit",
        json={"card_id": card_id, "rating": "good", "question": "q", "answer": "a", "feedback": "f"},
    )
    assert commit.status_code == 200

    # After a successful review the card is no longer due now.
    queue2 = (await client.get("/api/review/queue")).json()
    assert queue2["total_due"] == 0

    card = (await client.get(f"/api/cards/{card_id}")).json()
    assert len(card["reviews"]) == 1
    assert card["reviews"][0]["grade"] == "good"


async def test_review_commit_rejects_bad_rating(client):
    card_id = (await _make_card(client)).json()["card"]["id"]
    resp = await client.post("/api/review/commit", json={"card_id": card_id, "rating": "nope"})
    assert resp.status_code == 422

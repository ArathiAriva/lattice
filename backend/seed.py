"""Seed a small neuroscience starter lattice so the graph isn't empty on first run.

Usage (from backend/, venv active): python seed.py
Idempotent-ish: skips cards whose title already exists.
"""

import asyncio

from app.db import Base, SessionLocal, engine
from app.models import Card, Link, Topic
from app.scheduler import new_card_state
from app.tools import _find_card, _find_or_create_topic  # reuse helpers

CARDS = [
    ("Neuroscience", "Reward prediction error", "mechanism", "heard",
     "Dopamine neurons fire not in proportion to reward itself but to the difference between "
     "received and expected reward. A fully predicted reward produces no dopamine burst; an "
     "unexpected one does. This is a teaching signal, not a pleasure signal."),
    ("Neuroscience", "Dopamine is about motivation, not pleasure", "concept", "heard",
     "Popular framing calls dopamine the 'pleasure chemical', but evidence points to it driving "
     "wanting and pursuit (incentive salience) more than the hedonic experience of liking, which "
     "leans on opioid and endocannabinoid systems."),
    ("Neuroscience", "Long-term potentiation (LTP)", "mechanism", "heard",
     "Repeated, coincident firing of two connected neurons strengthens their synapse — a cellular "
     "basis for learning. Depends on NMDA receptors detecting simultaneous pre- and post-synaptic "
     "activity, letting calcium in to trigger lasting change."),
    ("Neuroscience", "Hebbian plasticity", "concept", "heard",
     "'Neurons that fire together wire together.' Synapses that repeatedly participate in firing "
     "the post-synaptic cell are strengthened — the principle underneath LTP."),
    ("Machine learning", "Temporal difference learning", "mechanism", "heard",
     "A reinforcement-learning method that updates value estimates from the difference between "
     "successive predictions rather than waiting for the final outcome. Its error term closely "
     "mirrors the dopamine reward-prediction-error signal."),
]

LINKS = [
    ("Hebbian plasticity", "Long-term potentiation (LTP)", "example_of",
     "LTP is the cellular mechanism that implements the Hebbian 'fire together, wire together' rule."),
    ("Temporal difference learning", "Reward prediction error", "related",
     "The TD error term is mathematically the same shape as the dopamine reward-prediction-error signal."),
    ("Dopamine is about motivation, not pleasure", "Reward prediction error", "builds_on",
     "Reframing dopamine as a learning/motivation signal follows directly from the RPE finding."),
]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        for topic, title, kind, conf, body in CARDS:
            if await _find_card(db, title):
                continue
            t: Topic = await _find_or_create_topic(db, topic)
            state, due = new_card_state()
            db.add(Card(topic_id=t.id, title=title, body=body, kind=kind, confidence=conf,
                        fsrs_state=state, due=due))
        await db.commit()
        for from_t, to_t, kind, reason in LINKS:
            a = await _find_card(db, from_t)
            b = await _find_card(db, to_t)
            if a and b:
                db.add(Link(from_id=a.id, to_id=b.id, kind=kind, reason=reason))
        await db.commit()
    print(f"Seeded {len(CARDS)} cards and {len(LINKS)} links.")


if __name__ == "__main__":
    asyncio.run(main())

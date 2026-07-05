"""FSRS scheduling wrapper.

Cards store their FSRS state as a JSON blob (Card.fsrs_state) plus a denormalized
`due` ISO timestamp for cheap queue queries. This module is the only place that
touches the fsrs package.
"""

import json
from datetime import datetime, timezone

from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler

RATINGS = {
    "again": Rating.Again,
    "hard": Rating.Hard,
    "good": Rating.Good,
    "easy": Rating.Easy,
}

_scheduler = Scheduler()


def new_card_state() -> tuple[str, str]:
    """State + due for a brand-new card (due immediately — first review encodes it)."""
    card = FsrsCard()
    return json.dumps(card.to_dict()), card.due.isoformat()


def review_card(fsrs_state: str, rating: str) -> tuple[str, str]:
    """Apply a review with the given rating. Returns (new_state_json, new_due_iso)."""
    if rating not in RATINGS:
        raise ValueError(f"Invalid rating: {rating}")
    card = FsrsCard.from_dict(json.loads(fsrs_state)) if fsrs_state else FsrsCard()
    card, _log = _scheduler.review_card(card, RATINGS[rating])
    return json.dumps(card.to_dict()), card.due.isoformat()


def stability(fsrs_state: str) -> float:
    """Current stability (days), 0.0 for unreviewed cards. Used for node sizing."""
    if not fsrs_state:
        return 0.0
    try:
        return float(json.loads(fsrs_state).get("stability") or 0.0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

"""Active-recall grading and question generation via the LLM.

Free-form answers are graded against the card body; the grade maps to an FSRS
rating (again/hard/good/easy) that the user can override before committing.
"""

import json
import logging

from app.llm import llm_call

logger = logging.getLogger("lattice.review")

QUESTION_PROMPT = """\
You write one active-recall question for a learner's knowledge card. The question must
require genuine retrieval of the card's core idea — never yes/no, never answerable from
the question itself. Vary the angle (mechanism, implication, example, contrast) so
repeated reviews aren't rote. Reply with ONLY the question text.

Card title: {title}
Card body: {body}
Kind: {kind}"""

GRADE_PROMPT = """\
You grade a learner's free-form answer to an active-recall question, against the card
that is the source of truth. Be encouraging but honest — the learning value is in the
gaps you point out.

Card title: {title}
Card body: {body}
Question: {question}
Learner's answer: {answer}

Reply with ONLY a JSON object:
{{"rating": "again"|"hard"|"good"|"easy", "feedback": "2-4 sentences: what they nailed, what they missed or got wrong, stated plainly."}}

Rating guide: "again" = missed the core idea; "hard" = core idea present but effortful or
partly wrong; "good" = solid recall with minor gaps; "easy" = complete, confident, precise."""


async def generate_question(title: str, body: str, kind: str) -> str:
    resp = await llm_call(
        [{"role": "user", "content": QUESTION_PROMPT.format(title=title, body=body, kind=kind)}]
    )
    return (resp.choices[0].message.content or "").strip() or f"Explain: {title}"


async def grade_answer(title: str, body: str, question: str, answer: str) -> dict:
    resp = await llm_call(
        [
            {
                "role": "user",
                "content": GRADE_PROMPT.format(title=title, body=body, question=question, answer=answer),
            }
        ]
    )
    text = (resp.choices[0].message.content or "").strip()
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        data = json.loads(text[start:end])
        rating = data.get("rating", "hard")
        if rating not in ("again", "hard", "good", "easy"):
            rating = "hard"
        return {"rating": rating, "feedback": str(data.get("feedback", ""))}
    except (ValueError, json.JSONDecodeError):
        logger.warning("Ungradeable LLM response: %r", text[:200])
        return {"rating": "hard", "feedback": text or "Could not grade — defaulted to 'hard'."}

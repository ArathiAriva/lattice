"use client";

import { useCallback, useEffect, useState } from "react";
import type { Card } from "@/lib/types";

interface Props {
  onDone: () => void;
  onDiscuss: (prompt: string) => void;
}

type Phase = "loading" | "answering" | "graded" | "empty" | "complete";

export default function Review({ onDone, onDiscuss }: Props) {
  const [queue, setQueue] = useState<Card[]>([]);
  const [totalDue, setTotalDue] = useState(0);
  const [reviewedCount, setReviewedCount] = useState(0);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("loading");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<{ rating: string; feedback: string } | null>(null);

  const card = queue[idx];

  const loadQueue = useCallback(() => {
    setPhase("loading");
    fetch("/api/review/queue")
      .then((r) => r.json())
      .then((d: { cards: Card[]; total_due: number }) => {
        setQueue(d.cards);
        setTotalDue(d.total_due);
        setIdx(0);
        setReviewedCount(0);
        if (d.cards.length === 0) setPhase("empty");
      })
      .catch(() => setPhase("empty"));
  }, []);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const loadQuestion = useCallback((c: Card) => {
    setPhase("loading");
    setAnswer("");
    setResult(null);
    fetch(`/api/review/question/${c.id}`)
      .then((r) => r.json())
      .then((d: { question: string }) => {
        setQuestion(d.question);
        setPhase("answering");
      })
      .catch(() => setPhase("answering"));
  }, []);

  useEffect(() => {
    if (card && phase === "loading" && queue.length > 0 && !result) {
      loadQuestion(card);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card?.id]);

  const check = async () => {
    if (!card || !answer.trim()) return;
    setPhase("loading");
    const r = await fetch("/api/review/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: card.id, question, answer, mode: "session" }),
    });
    const d = await r.json();
    setResult({ rating: d.rating, feedback: d.feedback });
    setPhase("graded");
  };

  const commit = async (rating: string) => {
    if (!card) return;
    await fetch("/api/review/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_id: card.id,
        rating,
        question,
        answer,
        feedback: result?.feedback ?? "",
        mode: "session",
      }),
    });
    onDone();
    const nextReviewed = reviewedCount + 1;
    setReviewedCount(nextReviewed);
    if (idx + 1 < queue.length) {
      setIdx(idx + 1);
      setResult(null);
      setPhase("loading");
    } else {
      setPhase("complete");
    }
  };

  if (phase === "empty") {
    return (
      <div className="review-pane">
        <div className="review-empty">
          <div className="big">✓</div>
          <h3>Nothing due right now</h3>
          <p>Your recall queue is clear. Keep exploring — new cards you keep will surface here when they&apos;re ripe for review.</p>
        </div>
      </div>
    );
  }

  if (phase === "complete") {
    return (
      <div className="review-pane">
        <div className="review-empty">
          <div className="big">★</div>
          <h3>Session complete</h3>
          <p>You reviewed {reviewedCount} card{reviewedCount === 1 ? "" : "s"}. {totalDue > queue.length ? `${totalDue - queue.length} more are due beyond today's cap — they'll keep.` : "That clears your queue."}</p>
          <button className="accept" onClick={loadQueue}>Check again</button>
        </div>
      </div>
    );
  }

  return (
    <div className="review-pane">
      <div className="review-progress">
        <span>Card {Math.min(idx + 1, queue.length)} of {queue.length}</span>
        <span className="muted">{totalDue} due total</span>
      </div>

      {phase === "loading" && !result && <div className="typing">Preparing a question…</div>}

      {card && (phase === "answering" || phase === "graded" || (phase === "loading" && result)) && (
        <div className="review-card">
          <div className="rc-question">{question}</div>

          {phase === "answering" && (
            <>
              <textarea
                className="rc-answer"
                autoFocus
                placeholder="Answer from memory, in your own words…"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) check();
                }}
              />
              <button className="accept" disabled={!answer.trim()} onClick={check}>Check answer</button>
            </>
          )}

          {result && (
            <div className="rc-graded">
              <div className="rc-your-answer">{answer}</div>
              <div className="rc-feedback">{result.feedback}</div>
              <div className="rc-rating-row">
                <span className="muted">How did that feel? (grades the next interval)</span>
                <div className="rate-buttons">
                  {["again", "hard", "good", "easy"].map((rt) => (
                    <button
                      key={rt}
                      className={rt === result.rating ? "rate suggested" : "rate"}
                      onClick={() => commit(rt)}
                    >
                      {rt}
                    </button>
                  ))}
                </div>
                <div className="muted small">Suggested: <b>{result.rating}</b> — override if you disagree.</div>
              </div>
              <button
                className="link-btn"
                onClick={() => onDiscuss(`I want to understand "${card.title}" better — I just missed part of it in review. Re-explain it and show me what connects to it.`)}
              >
                Discuss this instead ↗
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

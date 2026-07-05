"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMsg, Proposal, ProposalLink, QuizPayload } from "@/lib/types";

interface FeedItem {
  kind: "msg" | "proposal" | "quiz";
  msg?: ChatMsg;
  proposal?: Proposal;
  quiz?: QuizPayload;
  resolved?: "accepted" | "dismissed";
}

interface Conversation {
  id: string;
  title: string;
  created_at: string;
}

interface Props {
  onGraphChanged: () => void;
  pendingPrompt: string | null;
  clearPendingPrompt: () => void;
}

const KIND_ICON: Record<string, string> = {
  fact: "•",
  concept: "◆",
  mechanism: "⚙",
  question: "?",
};

const CONF_LABEL: Record<string, string> = {
  verified: "verified",
  heard: "heard",
  unsure: "unsure",
};

export default function Chat({ onGraphChanged, pendingPrompt, clearPendingPrompt }: Props) {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  const loadConversations = () =>
    fetch("/api/conversations")
      .then((r) => r.json())
      .then((cs: Conversation[]) => {
        setConvs(cs);
        return cs;
      })
      .catch(() => [] as Conversation[]);

  const openConversation = (id: string) => {
    setConvId(id);
    fetch(`/api/conversations/${id}/messages`)
      .then((r) => r.json())
      .then((msgs: ChatMsg[]) => setFeed(msgs.map((m) => ({ kind: "msg" as const, msg: m }))))
      .catch(() => {});
  };

  useEffect(() => {
    loadConversations().then((cs) => {
      if (cs.length > 0) openConversation(cs[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [feed, busy]);

  const newChat = () => {
    setConvId(null);
    setFeed([]);
  };

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setInput("");
    setBusy(true);
    setStatusText(null);
    setFeed((f) => [...f, { kind: "msg", msg: { role: "user", content: trimmed } }]);

    let assistantIdx = -1;
    const appendToken = (tok: string) =>
      setFeed((f) => {
        if (assistantIdx === -1 || f[assistantIdx]?.kind !== "msg") {
          assistantIdx = f.length;
          return [...f, { kind: "msg" as const, msg: { role: "assistant" as const, content: tok } }];
        }
        return f.map((item, i) =>
          i === assistantIdx ? { ...item, msg: { ...item.msg!, content: item.msg!.content + tok } } : item
        );
      });

    try {
      const r = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, conversation_id: convId }),
      });
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          switch (event.type) {
            case "conversation":
              if (!convId) {
                setConvId(event.conversation_id);
                loadConversations();
              }
              break;
            case "status":
              setStatusText(event.text);
              break;
            case "token":
              setStatusText(null);
              appendToken(event.text);
              break;
            case "proposal":
              setFeed((f) => [...f, { kind: "proposal", proposal: event.proposal as Proposal }]);
              assistantIdx = -1;
              break;
            case "question":
              setFeed((f) => [...f, { kind: "quiz", quiz: event.question as QuizPayload }]);
              assistantIdx = -1;
              break;
            case "done":
              if (event.graph_changed) onGraphChanged();
              break;
            case "error":
              throw new Error(event.text);
          }
        }
      }
    } catch {
      setFeed((f) => [
        ...f,
        {
          kind: "msg",
          msg: {
            role: "assistant",
            content:
              "⚠️ Something went wrong reaching the backend. Is it running on port 8020, and is OPENROUTER_API_KEY set?",
          },
        },
      ]);
    } finally {
      setBusy(false);
      setStatusText(null);
    }
  };

  useEffect(() => {
    if (pendingPrompt) {
      clearPendingPrompt();
      send(pendingPrompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingPrompt]);

  const accept = async (idx: number, p: Proposal) => {
    const r = await fetch("/api/cards/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    });
    setFeed((f) => f.map((item, i) => (i === idx ? { ...item, resolved: r.ok ? "accepted" : "dismissed" } : item)));
    if (r.ok) onGraphChanged();
  };

  const editProposal = (idx: number, patch: Partial<Proposal>) =>
    setFeed((f) => f.map((item, i) => (i === idx ? { ...item, proposal: { ...item.proposal!, ...patch } } : item)));

  const dismiss = (idx: number) =>
    setFeed((f) => f.map((item, i) => (i === idx ? { ...item, resolved: "dismissed" } : item)));

  // inline quiz answer flow
  const [quizAnswers, setQuizAnswers] = useState<Record<number, string>>({});
  const [quizResult, setQuizResult] = useState<Record<number, { rating: string; feedback: string; committed?: boolean }>>({});

  const submitQuiz = async (idx: number, q: QuizPayload) => {
    const answer = quizAnswers[idx] ?? "";
    if (!answer.trim()) return;
    const r = await fetch("/api/review/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: q.card_id, question: q.question, answer, mode: "inline" }),
    });
    const data = await r.json();
    setQuizResult((s) => ({ ...s, [idx]: { rating: data.rating, feedback: data.feedback } }));
  };

  const commitQuiz = async (idx: number, q: QuizPayload, rating: string) => {
    const res = quizResult[idx];
    await fetch("/api/review/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_id: q.card_id,
        rating,
        question: q.question,
        answer: quizAnswers[idx] ?? "",
        feedback: res?.feedback ?? "",
        mode: "inline",
      }),
    });
    setQuizResult((s) => ({ ...s, [idx]: { ...(s[idx] ?? { rating, feedback: "" }), committed: true } }));
    onGraphChanged();
  };

  return (
    <div className="chat">
      <div className="chat-header">
        <div className="chat-header-row">
          <div>
            <span>▦</span> Lattice
            <small>learn anything, in depth</small>
          </div>
          <div className="chat-header-actions">
            {convs.length > 0 && (
              <select
                value={convId ?? ""}
                onChange={(e) => (e.target.value ? openConversation(e.target.value) : newChat())}
              >
                <option value="">— new exploration —</option>
                {convs.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            )}
            <button onClick={newChat} title="Start a new exploration">+ New</button>
          </div>
        </div>
      </div>
      <div className="chat-messages" ref={messagesRef}>
        {feed.length === 0 && (
          <div className="msg assistant">
            What are you curious about? Name a topic — a concept from a podcast, a term you keep hearing — and we&apos;ll
            explore it. Ideas worth keeping become cards you can link and remember.
          </div>
        )}
        {feed.map((item, i) =>
          item.kind === "msg" ? (
            <div key={i} className={`msg ${item.msg!.role}`}>
              {item.msg!.role === "assistant" ? <ReactMarkdown>{item.msg!.content}</ReactMarkdown> : item.msg!.content}
            </div>
          ) : item.kind === "proposal" ? (
            <div key={i} className="proposal">
              <div className="p-head">
                <span className="p-kind">{KIND_ICON[item.proposal!.kind] ?? "•"} {item.proposal!.kind}</span>
                <span className={`p-conf conf-${item.proposal!.confidence}`}>{CONF_LABEL[item.proposal!.confidence]}</span>
                <span className="p-topic">{item.proposal!.topic}</span>
              </div>
              {item.resolved ? (
                <>
                  <div className="p-title">{item.proposal!.title}</div>
                  <div className="p-body">{item.proposal!.body}</div>
                </>
              ) : (
                <>
                  <input
                    className="p-title-edit"
                    value={item.proposal!.title}
                    onChange={(e) => editProposal(i, { title: e.target.value })}
                  />
                  <textarea
                    className="p-body-edit"
                    value={item.proposal!.body}
                    onChange={(e) => editProposal(i, { body: e.target.value })}
                  />
                </>
              )}
              {item.proposal!.links?.length ? (
                item.proposal!.links.map((c: ProposalLink, j) => (
                  <div key={j} className="p-conn">
                    <b>{c.kind.replace("_", " ")} → {c.to_title}</b>: {c.reason}
                  </div>
                ))
              ) : (
                <div className="p-conn muted">Stands alone — the seed of a new region.</div>
              )}
              {item.proposal!.source_url && (
                <a className="p-src" href={item.proposal!.source_url} target="_blank" rel="noreferrer">
                  source ↗
                </a>
              )}
              <div className="p-actions">
                {item.resolved === "accepted" ? (
                  <span className="ok">✓ Added to your lattice</span>
                ) : item.resolved === "dismissed" ? (
                  <span className="muted">Dismissed</span>
                ) : (
                  <>
                    <button className="accept" onClick={() => accept(i, item.proposal!)}>Keep card</button>
                    <button onClick={() => dismiss(i)}>Not now</button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div key={i} className="quiz">
              <div className="q-tag">↻ Due card · quick recall</div>
              <div className="q-title">{item.quiz!.card_title}</div>
              <div className="q-question">{item.quiz!.question}</div>
              {quizResult[i]?.committed ? (
                <div className="q-feedback">{quizResult[i].feedback}<div className="ok">✓ Reviewed</div></div>
              ) : quizResult[i] ? (
                <div className="q-graded">
                  <div className="q-feedback">{quizResult[i].feedback}</div>
                  <div className="q-rating-row">
                    <span className="muted">Schedule as:</span>
                    {["again", "hard", "good", "easy"].map((rt) => (
                      <button
                        key={rt}
                        className={rt === quizResult[i].rating ? "rate suggested" : "rate"}
                        onClick={() => commitQuiz(i, item.quiz!, rt)}
                      >
                        {rt}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  <textarea
                    className="q-answer"
                    placeholder="Answer from memory…"
                    value={quizAnswers[i] ?? ""}
                    onChange={(e) => setQuizAnswers((s) => ({ ...s, [i]: e.target.value }))}
                  />
                  <button className="accept" onClick={() => submitQuiz(i, item.quiz!)}>Check</button>
                </>
              )}
            </div>
          )
        )}
        {busy && <div className="typing">{statusText ?? "Lattice is thinking…"}</div>}
        <div ref={bottomRef} />
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Ask about anything, or follow a thread…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <button disabled={busy || !input.trim()} onClick={() => send(input)}>Send</button>
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import Chat from "@/components/Chat";
import Graph from "@/components/Graph";
import Review from "@/components/Review";
import type { GraphData } from "@/lib/types";

const EMPTY: GraphData = { topics: [], cards: [], links: [] };

export default function Home() {
  const [graph, setGraph] = useState<GraphData>(EMPTY);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [rightPane, setRightPane] = useState<"graph" | "review">("graph");
  const [dueCount, setDueCount] = useState(0);

  const loadGraph = useCallback(() => {
    fetch("/api/graph")
      .then((r) => r.json())
      .then((g: GraphData) => {
        setGraph(g);
        setDueCount(g.cards.filter((c) => c.due_now).length);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const askAbout = (prompt: string) => {
    setRightPane("graph");
    setPendingPrompt(prompt);
  };

  return (
    <main className="layout">
      <Chat
        onGraphChanged={loadGraph}
        pendingPrompt={pendingPrompt}
        clearPendingPrompt={() => setPendingPrompt(null)}
      />
      <div className="right-pane">
        <div className="pane-tabs">
          <button className={rightPane === "graph" ? "on" : ""} onClick={() => setRightPane("graph")}>
            Lattice
          </button>
          <button className={rightPane === "review" ? "on" : ""} onClick={() => setRightPane("review")}>
            Review{dueCount > 0 && <span className="due-badge">{dueCount}</span>}
          </button>
        </div>
        {rightPane === "graph" ? (
          <Graph data={graph} onAskAbout={askAbout} onChanged={loadGraph} />
        ) : (
          <Review
            onDone={() => {
              loadGraph();
            }}
            onDiscuss={askAbout}
          />
        )}
      </div>
    </main>
  );
}

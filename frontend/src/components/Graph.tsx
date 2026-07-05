"use client";

import * as d3 from "d3";
import { useEffect, useRef, useState } from "react";
import type { GraphData, Card, Link, Note, Review } from "@/lib/types";

// palette assigned per topic, cycled
const TOPIC_COLORS = ["#7aa2ff", "#ffb86b", "#9ef0b8", "#ff9ecb", "#c3a6ff", "#6be3d8", "#ffd479"];
const LINK_STYLE: Record<string, { color: string; dash: string }> = {
  builds_on: { color: "#7aa2ff", dash: "" },
  example_of: { color: "#9ef0b8", dash: "4 3" },
  contradicts: { color: "#ff7a7a", dash: "1 4" },
  related: { color: "#5a6390", dash: "" },
};

interface Props {
  data: GraphData;
  onAskAbout: (prompt: string) => void;
  onChanged: () => void;
}

type SimNode = d3.SimulationNodeDatum & Card;

interface CardDetail extends Card {
  notes: Note[];
  reviews: Review[];
}

export default function Graph({ data, onAskAbout, onChanged }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [noteDraft, setNoteDraft] = useState("");

  const topicColor = new Map<string, string>();
  data.topics.forEach((t, i) => topicColor.set(t.id, TOPIC_COLORS[i % TOPIC_COLORS.length]));
  const topicName = new Map(data.topics.map((t) => [t.id, t.name]));

  const loadDetail = (id: string) => {
    setSelectedId(id);
    fetch(`/api/cards/${id}`)
      .then((r) => r.json())
      .then((d: CardDetail) => setDetail(d))
      .catch(() => {});
  };

  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    svg.selectAll("*").remove();
    const { width, height } = svgRef.current!.getBoundingClientRect();

    const g = svg.append("g");
    svg.call(
      d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 4]).on("zoom", (e) => g.attr("transform", e.transform))
    );

    const nodes: SimNode[] = data.cards.map((c) => ({ ...c }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links = data.links
      .filter((l) => byId.has(l.from_id) && byId.has(l.to_id))
      .map((l) => ({ ...l, source: l.from_id, target: l.to_id }));

    const sim = d3
      .forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d: any) => d.id).distance(120).strength(0.5))
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(44));

    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d: any) => (LINK_STYLE[d.kind] ?? LINK_STYLE.related).color)
      .attr("stroke-width", 1.4)
      .attr("stroke-opacity", 0.75)
      .attr("stroke-dasharray", (d: any) => (LINK_STYLE[d.kind] ?? LINK_STYLE.related).dash);
    link.append("title").text((d: any) => `${d.kind}: ${d.reason}`);

    const node = g
      .append("g")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes)
      .join("g")
      .style("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    // due pulse halo
    node
      .filter((d) => !!d.due_now)
      .append("circle")
      .attr("r", 16)
      .attr("fill", "none")
      .attr("stroke", "#ffd479")
      .attr("stroke-opacity", 0.7)
      .attr("stroke-width", 2)
      .append("animate")
      .attr("attributeName", "r")
      .attr("values", "14;19;14")
      .attr("dur", "2s")
      .attr("repeatCount", "indefinite");

    node
      .append("circle")
      .attr("r", (d) => 8 + Math.min(6, (d.stability ?? 0) / 4))
      .attr("fill", (d) => topicColor.get(d.topic_id) ?? "#ccc")
      .attr("fill-opacity", (d) => (d.confidence === "unsure" ? 0.4 : d.confidence === "heard" ? 0.7 : 1))
      .attr("stroke", (d) => topicColor.get(d.topic_id) ?? "#ccc")
      .attr("stroke-width", 1.5);

    node
      .append("text")
      .text((d) => (d.title.length > 32 ? d.title.slice(0, 30) + "…" : d.title))
      .attr("dy", 24)
      .attr("text-anchor", "middle")
      .attr("fill", "#e6e9f5")
      .attr("font-size", 11)
      .attr("paint-order", "stroke")
      .attr("stroke", "#0b0e1a")
      .attr("stroke-width", 3);

    node.on("click", (_, d) => loadDetail(d.id));

    sim.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    return () => { sim.stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const selectedLinks: Link[] = selectedId
    ? data.links.filter((l) => l.from_id === selectedId || l.to_id === selectedId)
    : [];
  const cardTitleById = new Map(data.cards.map((c) => [c.id, c.title]));

  const addNote = async () => {
    if (!detail || !noteDraft.trim()) return;
    await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: detail.id, content: noteDraft.trim() }),
    });
    setNoteDraft("");
    loadDetail(detail.id);
  };

  const close = () => {
    setSelectedId(null);
    setDetail(null);
  };

  return (
    <div className="graph-pane">
      <svg ref={svgRef} />
      <div className="legend">
        {data.topics.slice(0, 6).map((t) => (
          <span key={t.id}>
            <span className="dot" style={{ background: topicColor.get(t.id) }} /> {t.name}
          </span>
        ))}
        <span style={{ opacity: 0.7 }}>faded = less certain · glow = due · scroll to zoom</span>
      </div>
      {data.cards.length === 0 && (
        <div className="empty-hint">
          Your lattice is empty. Start a conversation about anything you&apos;re curious about — each idea worth keeping
          becomes a card here, linked to the ones around it.
        </div>
      )}
      {detail && (
        <div className="node-card">
          <button className="close" onClick={close}>×</button>
          <div className="nc-head">
            <span className="p-kind">{detail.kind}</span>
            <span className={`p-conf conf-${detail.confidence}`}>{detail.confidence}</span>
            <span className="p-topic">{topicName.get(detail.topic_id)}</span>
          </div>
          <h3>{detail.title}</h3>
          <div className="nc-body">{detail.body}</div>
          {detail.source_url && (
            <a className="p-src" href={detail.source_url} target="_blank" rel="noreferrer">source ↗</a>
          )}

          {selectedLinks.length > 0 && (
            <div className="conns">
              {selectedLinks.map((l) => {
                const otherId = l.from_id === detail.id ? l.to_id : l.from_id;
                const dir = l.from_id === detail.id ? "→" : "←";
                return (
                  <div key={l.id}>
                    <b>{l.kind.replace("_", " ")} {dir} {cardTitleById.get(otherId)}</b> — {l.reason}
                  </div>
                );
              })}
            </div>
          )}

          <div className="nc-section">
            <h4>Scratch notes</h4>
            {detail.notes.length === 0 && <div className="muted small">Your thoughts on this — hunches, links to your own life, doubts.</div>}
            {detail.notes.map((n) => (
              <div key={n.id} className="note">{n.content}</div>
            ))}
            <textarea
              className="note-input"
              placeholder="Add a thought…"
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addNote();
              }}
            />
            <button className="small-btn" onClick={addNote}>Add note</button>
          </div>

          {detail.reviews.length > 0 && (
            <div className="nc-section">
              <h4>Recall history</h4>
              {detail.reviews.slice(0, 5).map((r) => (
                <div key={r.id} className="review-line">
                  <span className={`grade grade-${r.grade}`}>{r.grade}</span>{" "}
                  <span className="muted small">{new Date(r.created_at).toLocaleDateString()}</span>
                </div>
              ))}
            </div>
          )}

          <div className="card-actions">
            <button
              className="primary"
              onClick={() => {
                onAskAbout(`Go deeper on "${detail.title}". What are the adjacent ideas I should explore next, and why do they connect?`);
                close();
              }}
            >
              Explore adjacent
            </button>
            <button
              onClick={() => {
                onAskAbout(`Quiz me on "${detail.title}" — ask me a question and grade my answer.`);
                close();
              }}
            >
              Quiz me
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

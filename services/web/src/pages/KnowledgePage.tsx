import { useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { KnowledgeGraphData, KnowledgeNodeType } from "../api/types";
import { Formatter } from "../formatter";
import { Knowledge3dView } from "../knowledge3dView";
import { type Cluster, type GraphNode, KnowledgeGraphView } from "../knowledgeGraphView";
import { HashRouter } from "../routing";

const typeLabels: Record<KnowledgeNodeType, string> = {
  report: "Reports",
  paper: "Papers",
  topic: "Topics",
  note: "Your notes",
};

export function KnowledgePage({ client }: { client: ApiClient }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<KnowledgeGraphView | null>(null);
  const spaceRef = useRef<HTMLDivElement>(null);
  const view3dRef = useRef<Knowledge3dView | null>(null);
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const [graph, setGraph] = useState<KnowledgeGraphData | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [hidden, setHidden] = useState<Set<KnowledgeNodeType>>(new Set());
  const [search, setSearch] = useState("");
  const [clusters, setClusters] = useState<Cluster[]>([]);

  useEffect(() => {
    client
      .knowledgeGraph()
      .then(setGraph)
      .catch(() => setError("The knowledge graph could not be loaded."));
  }, [client]);

  useEffect(() => {
    if (!canvasRef.current || !graph) return;
    const view = new KnowledgeGraphView(canvasRef.current, setSelected);
    view.load(graph.nodes, graph.edges);
    viewRef.current = view;
    setClusters(view.clusters());
    return () => view.destroy();
  }, [graph]);

  useEffect(() => {
    viewRef.current?.setHidden(hidden);
    view3dRef.current?.setHidden(hidden);
  }, [hidden]);

  useEffect(() => {
    const view = viewRef.current;
    if (mode !== "3d" || !spaceRef.current || !view || !graph) return;
    let cancelled = false;
    void Knowledge3dView.create(spaceRef.current, view.allNodes(), graph.edges, (id) => view.select(id)).then((space) => {
      if (cancelled) {
        space.destroy();
        return;
      }
      space.setHidden(hidden);
      view3dRef.current = space;
    });
    return () => {
      cancelled = true;
      view3dRef.current?.destroy();
      view3dRef.current = null;
    };
    // Built once per switch to 3D; filters reach it through the effect above, so hidden is left out on purpose.
  }, [mode, graph]);

  // Selecting from a list or chip moves both views to the note.
  const choose = (id: string | null) => {
    viewRef.current?.select(id);
    if (id) view3dRef.current?.focus(id);
  };

  const toggle = (type: KnowledgeNodeType) =>
    setHidden((previous) => {
      const next = new Set(previous);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });

  const counts = (type: KnowledgeNodeType) => graph?.nodes.filter((node) => node.type === type).length ?? 0;

  return (
    <section className="knowledgePage">
      <span className="eyebrow">Knowledge</span>
      <h1>Knowledge graph</h1>
      <p className="muted">
        Every finished report, the papers it cites and the topics it covers. The same notes are an Obsidian vault in{" "}
        <span className="mono">knowledge/</span>: open that folder in Obsidian, and notes you add there appear here too.
      </p>

      {error && <p className="errorText">{error}</p>}

      <div className="knowledgeToolbar">
        <input
          className="knowledgeSearch"
          placeholder="Search notes, papers and topics"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            viewRef.current?.setSearch(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") choose(viewRef.current?.setSearch(search)?.id ?? null);
          }}
        />
        <div className="modeSwitch" role="group" aria-label="View">
          {(["2d", "3d"] as const).map((option) => (
            <button key={option} className={mode === option ? "active" : ""} onClick={() => setMode(option)}>
              {option.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="legend">
          {(Object.keys(typeLabels) as KnowledgeNodeType[]).map((type) => (
            <button
              key={type}
              className={hidden.has(type) ? "legendItem off" : "legendItem"}
              onClick={() => toggle(type)}
              title={hidden.has(type) ? "Show" : "Hide"}
            >
              <span className={`shapeIcon shape-${type}`} aria-hidden="true" />
              {typeLabels[type]} <strong>{counts(type)}</strong>
            </button>
          ))}
        </div>
      </div>

      {clusters.length > 0 && (
        <div className="clusterRow">
          <span className="muted">Research areas</span>
          {clusters.slice(0, 10).map((cluster) => (
            <button key={cluster.anchorId} className="clusterChip" onClick={() => choose(cluster.anchorId)} title="Show this area">
              <span className="legendDot" style={{ background: cluster.color, boxShadow: `0 0 10px ${cluster.color}` }} />
              {cluster.name.length > 32 ? `${cluster.name.slice(0, 30)}…` : cluster.name} <span className="muted">{cluster.size}</span>
            </button>
          ))}
        </div>
      )}

      <div className="card knowledgeCard">
        <canvas ref={canvasRef} className="knowledgeCanvas" aria-label="Knowledge graph" hidden={mode === "3d"} />
        {mode === "3d" && <div ref={spaceRef} className="knowledgeCanvas knowledgeSpace" aria-label="Knowledge graph in 3D" />}
        {graph && graph.nodes.length === 0 && (
          <p className="knowledgeEmpty muted">No reports yet. Finished reports are added to the vault automatically.</p>
        )}
        <p className="knowledgeHint">
          {mode === "3d"
            ? "Colour: research area · Drag to rotate · scroll to zoom · right-drag to pan · click for details"
            : "Colour: research area · Scroll to zoom · drag to pan · drag a node · click for details"}
        </p>
        {selected && (
          <aside className="knowledgeDetail">
            <button className="linkButton closeButton" onClick={() => choose(null)} aria-label="Close">
              ×
            </button>
            <span className="detailType" style={{ color: selected.color }}>
              {typeLabels[selected.type].replace(/s$/, "")}
            </span>
            <h2>{selected.label}</h2>
            {selected.meta.question && <p className="muted">{selected.meta.question}</p>}
            <ul className="detailMeta">
              {selected.meta.style && <li>Style: {Formatter.skillName(selected.meta.style)}</li>}
              {selected.meta.created && <li>Written {Formatter.time(selected.meta.created)}</li>}
              {selected.meta.published && <li>Published {selected.meta.published}</li>}
              {selected.meta.arxiv && <li className="mono">arXiv:{selected.meta.arxiv}</li>}
            </ul>
            <div className="detailActions">
              {selected.meta.runId && (
                <a className="primary buttonLink" href={HashRouter.href({ page: "run", runId: selected.meta.runId })}>
                  Open report
                </a>
              )}
              {selected.meta.url && (
                <a className="secondary buttonLink" href={selected.meta.url} target="_blank" rel="noreferrer noopener">
                  Open on arXiv
                </a>
              )}
            </div>
            <h3>Connected ({selected.links})</h3>
            <ul className="detailLinks">
              {viewRef.current?.connected(selected.id).map((node) => (
                <li key={node.id}>
                  <button className="linkButton" onClick={() => choose(node.id)}>
                    <span className="legendDot" style={{ background: node.color }} />
                    {node.label}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        )}
      </div>
    </section>
  );
}

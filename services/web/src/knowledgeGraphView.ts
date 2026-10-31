import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import type { KnowledgeEdge, KnowledgeNode, KnowledgeNodeType } from "./api/types";

export interface GraphNode extends SimulationNodeDatum, KnowledgeNode {
  radius: number;
}

type GraphLink = SimulationLinkDatum<GraphNode>;

export const nodeColors: Record<KnowledgeNodeType, string> = {
  report: "#8b6cff",
  paper: "#22d3ee",
  topic: "#f59e0b",
  note: "#34d399",
};

/** Draws the knowledge graph on a canvas: d3 lays it out, this class paints it and handles zoom, pan, drag and hover. */
export class KnowledgeGraphView {
  private readonly context: CanvasRenderingContext2D;
  private readonly simulation: Simulation<GraphNode, GraphLink>;
  private readonly neighbours = new Map<string, Set<string>>();
  private nodes: GraphNode[] = [];
  private links: GraphLink[] = [];
  private scale = 1;
  private offsetX = 0;
  private offsetY = 0;
  private width = 0;
  private height = 0;
  private hovered: GraphNode | null = null;
  private selected: GraphNode | null = null;
  private dragging: { node: GraphNode | null; startX: number; startY: number; moved: boolean } | null = null;
  private hidden = new Set<KnowledgeNodeType>();
  private search = "";
  private fitted = false;
  private readonly resize = new ResizeObserver(() => this.fit());

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly onSelect: (node: GraphNode | null) => void,
  ) {
    const context = canvas.getContext("2d");
    if (!context) throw new Error("canvas 2d is not available");
    this.context = context;
    this.simulation = forceSimulation<GraphNode, GraphLink>()
      .force("charge", forceManyBody<GraphNode>().strength((node) => -40 - node.radius * 12))
      .force("link", forceLink<GraphNode, GraphLink>().id((node) => node.id).distance(55).strength(0.4))
      .force("collide", forceCollide<GraphNode>((node) => node.radius + 4))
      .force("center", forceCenter(0, 0))
      // A gentle pull to the middle keeps notes with few or no links from drifting off.
      .force("x", forceX<GraphNode>(0).strength(0.06))
      .force("y", forceY<GraphNode>(0).strength(0.06))
      .on("tick", () => this.onTick());
    canvas.addEventListener("wheel", this.onWheel, { passive: false });
    canvas.addEventListener("pointerdown", this.onPointerDown);
    canvas.addEventListener("pointermove", this.onPointerMove);
    window.addEventListener("pointerup", this.onPointerUp);
    this.resize.observe(canvas);
    this.fit();
  }

  load(nodes: KnowledgeNode[], edges: KnowledgeEdge[]): void {
    this.nodes = nodes.map((node) => ({ ...node, radius: KnowledgeGraphView.radius(node) }));
    this.links = edges.map((edge) => ({ source: edge.source, target: edge.target }));
    this.neighbours.clear();
    for (const edge of edges) {
      this.neighboursOf(edge.source).add(edge.target);
      this.neighboursOf(edge.target).add(edge.source);
    }
    this.simulation.nodes(this.nodes);
    this.simulation.force<ReturnType<typeof forceLink<GraphNode, GraphLink>>>("link")?.links(this.links);
    this.fitted = false;
    this.simulation.alpha(1).restart();
  }

  destroy(): void {
    this.simulation.stop();
    this.resize.disconnect();
    window.removeEventListener("pointerup", this.onPointerUp);
  }

  setHidden(types: Set<KnowledgeNodeType>): void {
    this.hidden = types;
    this.draw();
  }

  /** Highlights matching notes and returns the best one: an exact name first, then topics, reports, papers. */
  setSearch(text: string): GraphNode | null {
    this.search = text.trim().toLowerCase();
    this.draw();
    if (!this.search) return null;
    const rank = (node: GraphNode) =>
      (node.label.toLowerCase() === this.search || node.id.toLowerCase() === this.search ? 0 : 10) + KnowledgeGraphView.typeOrder.indexOf(node.type);
    return this.nodes.filter((node) => this.visible(node) && this.matches(node)).sort((first, second) => rank(first) - rank(second))[0] ?? null;
  }

  select(id: string | null): void {
    this.selected = this.nodes.find((node) => node.id === id) ?? null;
    if (this.selected?.x !== undefined && this.selected.y !== undefined) {
      // Bring the selected note to the middle of the view, close enough to read its neighbours.
      this.scale = Math.max(this.scale, 1.6);
      this.offsetX = -this.selected.x * this.scale;
      this.offsetY = -this.selected.y * this.scale;
    }
    this.onSelect(this.selected);
    this.draw();
  }

  connected(id: string): GraphNode[] {
    const ids = this.neighbours.get(id) ?? new Set<string>();
    return this.nodes.filter((node) => ids.has(node.id)).sort((first, second) => second.links - first.links);
  }

  private static readonly typeOrder: KnowledgeNodeType[] = ["topic", "report", "paper", "note"];

  private onTick(): void {
    // Once the layout has mostly settled, zoom so the whole graph fits; after that the view is the user's.
    if (!this.fitted && this.simulation.alpha() < 0.08) {
      this.fitted = true;
      this.fitToContent();
    }
    this.draw();
  }

  private fitToContent(): void {
    const placed = this.nodes.filter((node) => this.visible(node) && node.x !== undefined && node.y !== undefined);
    if (placed.length === 0 || this.width === 0) return;
    // Fit the bulk of the graph (5th to 95th percentile), so a few outlying notes do not shrink everything.
    const xs = placed.map((node) => node.x ?? 0).sort((first, second) => first - second);
    const ys = placed.map((node) => node.y ?? 0).sort((first, second) => first - second);
    const at = (values: number[], share: number) => values[Math.floor((values.length - 1) * share)] ?? 0;
    const [left, right, top, bottom] = [at(xs, 0.05), at(xs, 0.95), at(ys, 0.05), at(ys, 0.95)];
    this.scale = Math.min(1.6, Math.max(0.2, Math.min(this.width / (right - left + 120), this.height / (bottom - top + 120))));
    this.offsetX = -((left + right) / 2) * this.scale;
    this.offsetY = -((top + bottom) / 2) * this.scale;
  }

  private static radius(node: KnowledgeNode): number {
    const base = node.type === "topic" ? 7 : node.type === "report" ? 6 : 3.5;
    return base + Math.sqrt(node.links) * 1.6;
  }

  private neighboursOf(id: string): Set<string> {
    let set = this.neighbours.get(id);
    if (!set) {
      set = new Set();
      this.neighbours.set(id, set);
    }
    return set;
  }

  private matches(node: GraphNode): boolean {
    return node.label.toLowerCase().includes(this.search) || node.id.toLowerCase().includes(this.search);
  }

  private visible(node: GraphNode): boolean {
    return !this.hidden.has(node.type);
  }

  private fit(): void {
    const ratio = window.devicePixelRatio || 1;
    const box = this.canvas.getBoundingClientRect();
    this.width = box.width;
    this.height = box.height;
    this.canvas.width = Math.round(box.width * ratio);
    this.canvas.height = Math.round(box.height * ratio);
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.draw();
  }

  private toWorld(clientX: number, clientY: number): [number, number] {
    const box = this.canvas.getBoundingClientRect();
    return [
      (clientX - box.left - this.width / 2 - this.offsetX) / this.scale,
      (clientY - box.top - this.height / 2 - this.offsetY) / this.scale,
    ];
  }

  private nodeAt(clientX: number, clientY: number): GraphNode | null {
    const [x, y] = this.toWorld(clientX, clientY);
    let best: GraphNode | null = null;
    let bestDistance = Infinity;
    for (const node of this.nodes) {
      if (!this.visible(node) || node.x === undefined || node.y === undefined) continue;
      const distance = Math.hypot(node.x - x, node.y - y);
      if (distance < node.radius + 4 / this.scale && distance < bestDistance) {
        best = node;
        bestDistance = distance;
      }
    }
    return best;
  }

  private readonly onWheel = (event: WheelEvent): void => {
    event.preventDefault();
    const [worldX, worldY] = this.toWorld(event.clientX, event.clientY);
    const next = Math.min(4, Math.max(0.2, this.scale * Math.exp(-event.deltaY * 0.0015)));
    // Zoom around the pointer: the point under it stays put.
    this.offsetX += worldX * (this.scale - next);
    this.offsetY += worldY * (this.scale - next);
    this.scale = next;
    this.draw();
  };

  private readonly onPointerDown = (event: PointerEvent): void => {
    const node = this.nodeAt(event.clientX, event.clientY);
    this.dragging = { node, startX: event.clientX, startY: event.clientY, moved: false };
    if (node) {
      node.fx = node.x;
      node.fy = node.y;
      this.simulation.alphaTarget(0.2).restart();
    }
  };

  private readonly onPointerMove = (event: PointerEvent): void => {
    if (this.dragging) {
      const dx = event.clientX - this.dragging.startX;
      const dy = event.clientY - this.dragging.startY;
      this.dragging.moved ||= Math.hypot(dx, dy) > 3;
      if (this.dragging.node) {
        const [x, y] = this.toWorld(event.clientX, event.clientY);
        this.dragging.node.fx = x;
        this.dragging.node.fy = y;
      } else {
        this.offsetX += event.movementX;
        this.offsetY += event.movementY;
        this.draw();
      }
      return;
    }
    const node = this.nodeAt(event.clientX, event.clientY);
    if (node !== this.hovered) {
      this.hovered = node;
      this.canvas.style.cursor = node ? "pointer" : "grab";
      this.draw();
    }
  };

  private readonly onPointerUp = (): void => {
    if (!this.dragging) return;
    const { node, moved } = this.dragging;
    if (node) {
      node.fx = null;
      node.fy = null;
      this.simulation.alphaTarget(0);
    }
    if (!moved) this.select(node?.id ?? null);
    this.dragging = null;
  };

  private draw(): void {
    const context = this.context;
    const styles = getComputedStyle(this.canvas);
    const textColor = styles.getPropertyValue("--text").trim() || "#e6e9f2";
    const edgeColor = styles.getPropertyValue("--borderStrong").trim() || "rgba(255,255,255,0.18)";
    context.clearRect(0, 0, this.width, this.height);
    context.save();
    context.translate(this.width / 2 + this.offsetX, this.height / 2 + this.offsetY);
    context.scale(this.scale, this.scale);

    const focus = this.hovered ?? this.selected;
    const lit = focus ? new Set([focus.id, ...(this.neighbours.get(focus.id) ?? [])]) : null;
    const searching = this.search.length > 0;

    for (const link of this.links) {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (!this.visible(source) || !this.visible(target) || source.x === undefined || target.x === undefined) continue;
      const active = lit !== null && lit.has(source.id) && lit.has(target.id) && (source.id === focus?.id || target.id === focus?.id);
      context.strokeStyle = active ? nodeColors[focus?.type ?? "report"] : edgeColor;
      context.globalAlpha = lit && !active ? 0.12 : active ? 0.9 : 0.45;
      context.lineWidth = (active ? 1.6 : 0.8) / this.scale;
      context.beginPath();
      context.moveTo(source.x, source.y ?? 0);
      context.lineTo(target.x, target.y ?? 0);
      context.stroke();
    }

    for (const node of this.nodes) {
      if (!this.visible(node) || node.x === undefined || node.y === undefined) continue;
      const dimmed = (lit !== null && !lit.has(node.id)) || (searching && !this.matches(node));
      const color = nodeColors[node.type];
      context.globalAlpha = dimmed ? 0.15 : 1;
      context.shadowColor = color;
      context.shadowBlur = dimmed ? 0 : node === focus ? 22 : 10;
      context.fillStyle = color;
      context.beginPath();
      context.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      context.fill();
      context.shadowBlur = 0;
      if (node === this.selected) {
        context.strokeStyle = textColor;
        context.lineWidth = 2 / this.scale;
        context.stroke();
      }
    }

    // Labels: topics always, reports once zoomed in, anything lit by hover or matched by search.
    context.globalAlpha = 1;
    context.fillStyle = textColor;
    context.textAlign = "center";
    context.font = `${12 / this.scale}px Inter, system-ui, sans-serif`;
    for (const node of this.nodes) {
      if (!this.visible(node) || node.x === undefined || node.y === undefined) continue;
      const show =
        lit?.has(node.id) ||
        (searching && this.matches(node)) ||
        (!lit && !searching && ((node.type === "topic" && (this.scale > 0.9 || node.links >= 3)) || (node.type === "report" && this.scale > 1.4)));
      if (!show) continue;
      const label = node.label.length > 42 ? `${node.label.slice(0, 40)}…` : node.label;
      context.globalAlpha = node.type === "topic" || lit?.has(node.id) ? 0.95 : 0.7;
      context.fillText(label, node.x, node.y - node.radius - 5 / this.scale);
    }
    context.restore();
  }
}

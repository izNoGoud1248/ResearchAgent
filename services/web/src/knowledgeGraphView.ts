import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import type { KnowledgeEdge, KnowledgeNode, KnowledgeNodeType } from "./api/types";

export interface GraphNode extends SimulationNodeDatum, KnowledgeNode {
  radius: number;
  cluster: number;
  color: string;
}

type GraphLink = SimulationLinkDatum<GraphNode>;

export interface Cluster {
  color: string;
  name: string;
  size: number;
  anchorId: string;
}

const palette = [
  "#ff6b8b", "#ffd166", "#06d6a0", "#4cc9f0", "#b388ff", "#ff9f5a", "#7bdff2", "#c6f68d",
  "#f28482", "#a0c4ff", "#f7aef8", "#5eead4", "#fde047", "#fb7185", "#93c5fd", "#bef264",
];
export const looseColor = "#8a93a8";

/** Groups notes that link mostly to each other (weighted label propagation), so each research area gets its own colour. */
export class KnowledgeClusters {
  static detect(ids: string[], neighbours: Map<string, Set<string>>): Map<string, number> {
    const label = new Map(ids.map((id, index) => [id, index]));
    const order = [...ids].sort();
    for (let round = 0; round < 25; round++) {
      let changed = false;
      for (const id of order) {
        const votes = new Map<number, number>();
        for (const neighbour of neighbours.get(id) ?? []) {
          // A hub such as "Large Language Models" links to everything, so its vote counts for less.
          const weight = 1 / Math.max(1, neighbours.get(neighbour)?.size ?? 1);
          const neighbourLabel = label.get(neighbour) ?? 0;
          votes.set(neighbourLabel, (votes.get(neighbourLabel) ?? 0) + weight);
        }
        const best = [...votes.entries()].sort((first, second) => second[1] - first[1] || first[0] - second[0])[0]?.[0];
        if (best !== undefined && best !== label.get(id)) {
          label.set(id, best);
          changed = true;
        }
      }
      if (!changed) break;
    }
    return label;
  }
}

class Shade {
  static rgb(hex: string): [number, number, number] {
    const value = Number.parseInt(hex.slice(1), 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
  }

  /** Mixes a colour towards white (amount > 0) or black (amount < 0). */
  static mix(hex: string, amount: number): string {
    const target = amount > 0 ? 255 : 0;
    const [red, green, blue] = Shade.rgb(hex).map((channel) => Math.round(channel + (target - channel) * Math.abs(amount)));
    return `rgb(${red}, ${green}, ${blue})`;
  }

  static alpha(hex: string, opacity: number): string {
    const [red, green, blue] = Shade.rgb(hex);
    return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
  }
}

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
  private clusterList: Cluster[] = [];
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
    this.neighbours.clear();
    for (const edge of edges) {
      this.neighboursOf(edge.source).add(edge.target);
      this.neighboursOf(edge.target).add(edge.source);
    }
    const labels = KnowledgeClusters.detect(nodes.map((node) => node.id), this.neighbours);
    this.nodes = nodes.map((node) => ({ ...node, radius: KnowledgeGraphView.radius(node), cluster: labels.get(node.id) ?? 0, color: looseColor }));
    this.colourClusters();
    this.links = edges.map((edge) => ({ source: edge.source, target: edge.target }));
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

  /** The notes with their cluster colours, for the 3D view. */
  allNodes(): GraphNode[] {
    return this.nodes;
  }

  /** Clusters biggest first, each named after its best-connected topic (or note). */
  clusters(): Cluster[] {
    return this.clusterList;
  }

  private colourClusters(): void {
    const members = new Map<number, GraphNode[]>();
    for (const node of this.nodes) members.set(node.cluster, [...(members.get(node.cluster) ?? []), node]);
    // Groups of fewer than three notes are not really clusters; they keep a neutral colour.
    const ranked = [...members.values()].filter((group) => group.length >= 3).sort((first, second) => second.length - first.length);
    this.clusterList = ranked.slice(0, palette.length).map((group, index) => {
      const color = palette[index] ?? looseColor;
      for (const node of group) node.color = color;
      const byLinks = [...group].sort((first, second) => second.links - first.links);
      const anchor = byLinks.find((node) => node.type === "topic") ?? byLinks[0];
      return { color, name: anchor?.label ?? "Cluster", size: group.length, anchorId: anchor?.id ?? "" };
    });
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
    // Fit the bulk of the graph (2nd to 98th percentile), so a few outlying notes do not shrink everything.
    const xs = placed.map((node) => node.x ?? 0).sort((first, second) => first - second);
    const ys = placed.map((node) => node.y ?? 0).sort((first, second) => first - second);
    const at = (values: number[], share: number) => values[Math.floor((values.length - 1) * share)] ?? 0;
    const [left, right, top, bottom] = [at(xs, 0.02), at(xs, 0.98), at(ys, 0.02), at(ys, 0.98)];
    this.scale = Math.min(1.6, Math.max(0.2, Math.min(this.width / (right - left + 160), this.height / (bottom - top + 160))));
    this.offsetX = -((left + right) / 2) * this.scale;
    this.offsetY = -((top + bottom) / 2) * this.scale;
  }

  private static radius(node: KnowledgeNode): number {
    const base = node.type === "topic" ? 6.5 : node.type === "report" ? 6 : 3.2;
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
    context.clearRect(0, 0, this.width, this.height);
    context.save();
    context.translate(this.width / 2 + this.offsetX, this.height / 2 + this.offsetY);
    context.scale(this.scale, this.scale);

    const focus = this.hovered ?? this.selected;
    const lit = focus ? new Set([focus.id, ...(this.neighbours.get(focus.id) ?? [])]) : null;
    const searching = this.search.length > 0;

    // Edges take their cluster's colour inside a cluster and stay faint grey between clusters; overlaps add up to a glow.
    context.globalCompositeOperation = "lighter";
    for (const link of this.links) {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (!this.visible(source) || !this.visible(target) || source.x === undefined || target.x === undefined) continue;
      const active = lit !== null && (source.id === focus?.id || target.id === focus?.id);
      const sameCluster = source.color === target.color && source.color !== looseColor;
      const opacity = lit ? (active ? 0.85 : 0.04) : sameCluster ? 0.32 : 0.12;
      context.strokeStyle = Shade.alpha(active ? (focus?.color ?? source.color) : sameCluster ? source.color : looseColor, opacity);
      context.lineWidth = (active ? 1.5 : 0.7) / this.scale;
      context.beginPath();
      context.moveTo(source.x, source.y ?? 0);
      context.lineTo(target.x, target.y ?? 0);
      context.stroke();
    }
    context.globalCompositeOperation = "source-over";

    // Nodes are lit spheres: a highlight up and to the left, darker towards the edge, and a soft glow.
    for (const node of this.nodes) {
      if (!this.visible(node) || node.x === undefined || node.y === undefined) continue;
      const dimmed = (lit !== null && !lit.has(node.id)) || (searching && !this.matches(node));
      const { x, y, radius, color } = node;
      context.globalAlpha = dimmed ? 0.12 : 1;
      context.shadowColor = color;
      context.shadowBlur = dimmed ? 0 : node === focus ? 26 : radius * 1.6;
      const sphere = context.createRadialGradient(x - radius * 0.35, y - radius * 0.4, radius * 0.1, x, y, radius);
      sphere.addColorStop(0, Shade.mix(color, 0.65));
      sphere.addColorStop(0.45, color);
      sphere.addColorStop(1, Shade.mix(color, -0.45));
      context.fillStyle = sphere;
      context.beginPath();
      context.arc(x, y, radius, 0, Math.PI * 2);
      context.fill();
      context.shadowBlur = 0;
      // Shape shows the kind of note: topics wear a ring, your own notes a dashed one.
      if (node.type === "topic" || node.type === "note") {
        context.strokeStyle = Shade.alpha(color, 0.75);
        context.lineWidth = 1.2 / this.scale;
        context.setLineDash(node.type === "note" ? [3 / this.scale, 2 / this.scale] : []);
        context.beginPath();
        context.arc(x, y, radius + 3.5 / this.scale + 1.5, 0, Math.PI * 2);
        context.stroke();
        context.setLineDash([]);
      }
      if (node === this.selected) {
        context.strokeStyle = "#ffffff";
        context.lineWidth = 2 / this.scale;
        context.beginPath();
        context.arc(x, y, radius + 6 / this.scale + 2, 0, Math.PI * 2);
        context.stroke();
      }
    }

    // Labels: big topics always, reports once zoomed in, anything lit by hover or matched by search.
    context.globalAlpha = 1;
    context.textAlign = "center";
    context.font = `500 ${12 / this.scale}px Inter, system-ui, sans-serif`;
    context.shadowColor = "rgba(0, 0, 0, 0.9)";
    context.shadowBlur = 4;
    context.fillStyle = "#f4f6fb";
    for (const node of this.nodes) {
      if (!this.visible(node) || node.x === undefined || node.y === undefined) continue;
      const show =
        lit?.has(node.id) ||
        (searching && this.matches(node)) ||
        (!lit && !searching && ((node.type === "topic" && (this.scale > 0.9 || node.links >= 3)) || (node.type === "report" && this.scale > 1.4)));
      if (!show) continue;
      const label = node.label.length > 42 ? `${node.label.slice(0, 40)}…` : node.label;
      context.globalAlpha = node.type === "topic" || lit?.has(node.id) ? 0.95 : 0.7;
      context.fillText(label, node.x, node.y - node.radius - 7 / this.scale);
    }
    context.shadowBlur = 0;
    context.restore();
  }
}

import type { ForceGraph3DInstance } from "3d-force-graph";
import type { KnowledgeEdge, KnowledgeNodeType } from "./api/types";
import { type GraphNode, looseColor } from "./knowledgeGraphView";

interface Node3d {
  id: string;
  label: string;
  type: KnowledgeNodeType;
  color: string;
  links: number;
  x?: number;
  y?: number;
  z?: number;
}

interface Link3d {
  source: string | Node3d;
  target: string | Node3d;
  color: string;
}

/** The same graph in 3D, for showing off rather than daily use. The library loads only when this view is opened. */
export class Knowledge3dView {
  private hidden = new Set<KnowledgeNodeType>();
  private readonly resize: ResizeObserver;

  private constructor(
    private readonly graph: ForceGraph3DInstance<Node3d, Link3d>,
    private readonly container: HTMLElement,
  ) {
    this.resize = new ResizeObserver(() => graph.width(container.clientWidth).height(container.clientHeight));
    this.resize.observe(container);
  }

  static async create(container: HTMLElement, nodes: GraphNode[], edges: KnowledgeEdge[], onSelect: (id: string) => void): Promise<Knowledge3dView> {
    const { default: ForceGraph3D } = await import("3d-force-graph");
    const colors = new Map(nodes.map((node) => [node.id, node.color]));
    const data = {
      nodes: nodes.map((node) => ({ id: node.id, label: node.label, type: node.type, color: node.color, links: node.links })),
      links: edges.map((edge) => {
        const color = colors.get(edge.source) === colors.get(edge.target) ? (colors.get(edge.source) ?? looseColor) : looseColor;
        return { source: edge.source, target: edge.target, color };
      }),
    };
    // The library's constructor is not generic, so the instance is given our node and link types here.
    const graph = (new ForceGraph3D(container) as unknown as ForceGraph3DInstance<Node3d, Link3d>)
      .backgroundColor("#04050b")
      .width(container.clientWidth)
      .height(container.clientHeight)
      .showNavInfo(false)
      .nodeRelSize(3)
      .nodeVal((node) => (node.type === "paper" ? 1 : node.type === "topic" ? 5 : 4) + node.links * 0.4)
      .nodeColor((node) => node.color)
      .nodeOpacity(0.95)
      .nodeResolution(16)
      .nodeLabel((node) => Knowledge3dView.label(node))
      .linkColor((link) => link.color)
      .linkOpacity(0.28)
      .linkWidth(0.4)
      .onNodeClick((node) => onSelect(node.id))
      .graphData(data);
    const view = new Knowledge3dView(graph, container);
    graph.onEngineStop(() => graph.zoomToFit(600, 40));
    return view;
  }

  /** Hover label as plain text: titles come from reports, so they never go in as HTML. */
  private static label(node: Node3d): HTMLElement {
    const label = document.createElement("div");
    label.className = "graph3dLabel";
    label.textContent = node.label;
    return label;
  }

  setHidden(types: Set<KnowledgeNodeType>): void {
    this.hidden = types;
    this.graph.nodeVisibility((node) => !this.hidden.has(node.type));
    this.graph.linkVisibility((link) => {
      const source = link.source as Node3d;
      const target = link.target as Node3d;
      return !this.hidden.has(source.type) && !this.hidden.has(target.type);
    });
  }

  /** Flies the camera to a note, keeping a little distance so its neighbours stay in view. */
  focus(id: string): void {
    const node = this.graph.graphData().nodes.find((candidate) => candidate.id === id);
    if (node?.x === undefined || node.y === undefined || node.z === undefined) return;
    const distance = 120;
    const ratio = 1 + distance / Math.max(1, Math.hypot(node.x, node.y, node.z));
    this.graph.cameraPosition({ x: node.x * ratio, y: node.y * ratio, z: node.z * ratio }, { x: node.x, y: node.y, z: node.z }, 1200);
  }

  destroy(): void {
    this.resize.disconnect();
    this.graph._destructor();
    this.container.replaceChildren();
  }
}

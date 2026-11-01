import type { ForceGraph3DInstance } from "3d-force-graph";
import type { Camera } from "three";
import type { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
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
  // Set when the node's label is created, so its visibility can follow the camera.
  tag?: CSS2DObject;
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
  // How close the camera must be before a report's or minor topic's name shows; papers only on hover.
  private static readonly reportLabelDistance = 260;

  private constructor(
    private readonly graph: ForceGraph3DInstance<Node3d, Link3d>,
    private readonly container: HTMLElement,
  ) {
    this.resize = new ResizeObserver(() => graph.width(container.clientWidth).height(container.clientHeight));
    this.resize.observe(container);
  }

  static async create(container: HTMLElement, nodes: GraphNode[], edges: KnowledgeEdge[], onSelect: (id: string) => void): Promise<Knowledge3dView> {
    const [{ default: ForceGraph3D }, { CSS2DRenderer, CSS2DObject }] = await Promise.all([
      import("3d-force-graph"),
      import("three/examples/jsm/renderers/CSS2DRenderer.js"),
    ]);
    const colors = new Map(nodes.map((node) => [node.id, node.color]));
    const data = {
      nodes: nodes.map((node) => ({ id: node.id, label: node.label, type: node.type, color: node.color, links: node.links })),
      links: edges.map((edge) => {
        const color = colors.get(edge.source) === colors.get(edge.target) ? (colors.get(edge.source) ?? looseColor) : looseColor;
        return { source: edge.source, target: edge.target, color };
      }),
    };
    // The library's constructor is not generic, so the instance is given our node and link types here.
    // A second renderer draws ordinary page elements at 3D positions: the names next to the spheres.
    const graph = (new ForceGraph3D(container, { extraRenderers: [new CSS2DRenderer()] }) as unknown as ForceGraph3DInstance<Node3d, Link3d>)
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
      .nodeThreeObject((node) => {
        const tag = new CSS2DObject(Knowledge3dView.tagElement(node));
        node.tag = tag;
        return tag;
      })
      .nodeThreeObjectExtend(true)
      .linkColor((link) => link.color)
      .linkOpacity(0.28)
      .linkWidth(0.4)
      .onNodeClick((node) => onSelect(node.id))
      .graphData(data);
    const view = new Knowledge3dView(graph, container);
    graph.onEngineStop(() => graph.zoomToFit(600, 40));
    graph.onEngineTick(() => view.updateLabels());
    (graph.controls() as { addEventListener(type: "change", listener: () => void): void }).addEventListener("change", () => view.updateLabels());
    return view;
  }

  /** Hover label as plain text: titles come from reports, so they never go in as HTML. */
  private static label(node: Node3d): HTMLElement {
    const label = document.createElement("div");
    label.className = "graph3dLabel";
    label.textContent = node.label;
    return label;
  }

  /** A name tag as plain text, like the hover label; papers have none, there are too many to show at once. */
  private static tagElement(node: Node3d): HTMLElement {
    const tag = document.createElement("div");
    tag.className = `graph3dTag tag-${node.type}`;
    tag.textContent = node.type === "paper" ? "" : node.label.length > 40 ? `${node.label.slice(0, 38)}…` : node.label;
    return tag;
  }

  private updateLabels(): void {
    const camera: Camera = this.graph.camera();
    for (const node of this.graph.graphData().nodes) {
      if (!node.tag || node.x === undefined || node.y === undefined || node.z === undefined) continue;
      const distance = Math.hypot(camera.position.x - node.x, camera.position.y - node.y, camera.position.z - node.z);
      const near = distance < Knowledge3dView.reportLabelDistance;
      // Like the 2D view: well-connected topics always, everything else once the camera is close enough to read it.
      const shown = node.type === "topic" || node.type === "note" ? node.links >= 3 || near : node.type === "report" && near;
      node.tag.visible = shown && !this.hidden.has(node.type);
    }
  }

  setHidden(types: Set<KnowledgeNodeType>): void {
    this.hidden = types;
    this.graph.nodeVisibility((node) => !this.hidden.has(node.type));
    this.graph.linkVisibility((link) => {
      const source = link.source as Node3d;
      const target = link.target as Node3d;
      return !this.hidden.has(source.type) && !this.hidden.has(target.type);
    });
    this.updateLabels();
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

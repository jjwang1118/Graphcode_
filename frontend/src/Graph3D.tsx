// 3D 畫布，沿用參照專案（components/Graph3D.tsx）：three.js 的力導向球體。
// 與 2D 吃同一份視圖、同一個影響範圍、同一個細節框——只是呈現方式不同（D5）。

import ForceGraph3D, { type ForceGraph3DInstance } from '3d-force-graph';
import { useEffect, useRef, useState } from 'react';
import SpriteText from 'three-spritetext';

import type { View } from './api';
import type { Mark, Wave } from './elements';
import type { EdgeInfo, Point } from './Graph';
import { IMPACT_STEP_MS, palette } from './palette';

interface Props {
  view: View | null;
  /** 節點間距。3D 改的是力導向的理想邊長，不是事後縮放座標 */
  spacing: number;
  nodeScale: number;
  /** 動態：關係線上有往箭頭方向流動的光點 */
  motion: boolean;
  wave: Wave | null;
  onSelect: (node: string | null, at: Point | null) => void;
  onToggle: (node: string) => void;
  onEdge: (edges: EdgeInfo[], at: Point) => void;
}

interface Node3D {
  id: string;
  label: string;
  type: string;
  size: number;
  color: string;
  x?: number;
  y?: number;
  z?: number;
}

interface Link3D {
  source: string | Node3D;
  target: string | Node3D;
  type: string;
  count: number;
}

const SIZE: Record<string, number> = {
  repo: 9,
  directory: 6,
  file: 3.5,
  external_group: 6,
  external_package: 4.5,
  class: 3,
  function: 2.2,
  variable: 1.4,
};
const COLOR: Record<string, string> = {
  repo: palette.repo,
  directory: palette.directory,
  file: palette.file,
  external_group: palette.external,
  external_package: palette.external,
  class: palette.class,
  function: palette.function,
  variable: palette.variable,
};
const LINK_COLOR: Record<string, string> = {
  imports: palette.edgeImports,
  defines: palette.edgeDefines,
  inherits: palette.edgeInherits,
  calls: palette.edgeCalls,
  references: palette.edgeReferences,
};
// 影響範圍：3D 沒有邊框可用，改用顏色區分
const MARK_COLOR: Record<Mark, string> = {
  origin: '#ffffff',
  certain: palette.impact,
  possible: 'rgba(94,234,212,0.5)',
  candidate: palette.accent,
};
/** 淡化用的顏色。3D 沒有 2D 那種整體 opacity，只能讓顏色自己帶 alpha。 */
const DIM_NODE = 'rgba(91,107,140,0.12)';
const DIM_LINK = 'rgba(70,112,92,0.05)';
const LABEL_COLOR = '#e6ecf5';
const LABEL_BACKGROUND = 'rgba(10,13,20,0.82)';
const PARTICLE_MAX_LINKS = 800;
const DOUBLE_CLICK_MS = 350;

const isRelation = (link: Link3D) => link.type !== 'contains' && link.type !== 'defines';
const idOf = (end: string | Node3D) => (typeof end === 'object' ? end.id : end);

export default function Graph3D({ view, spacing, nodeScale, motion, wave, onSelect, onToggle, onEdge }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const scene = useRef<ForceGraph3DInstance | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // 滑鼠所在節點與它的鄰居；null＝沒有在看誰
  const focus = useRef<Set<string> | null>(null);
  const neighbours = useRef(new Map<string, Set<string>>());
  const waveNow = useRef<{ wave: Wave; shown: number } | null>(null);
  const scaleRef = useRef(nodeScale);
  scaleRef.current = nodeScale;
  const motionRef = useRef(motion);
  motionRef.current = motion;
  const lastClick = useRef({ id: '', at: 0 });
  const handlers = useRef({ onSelect, onToggle, onEdge });
  handlers.current = { onSelect, onToggle, onEdge };

  useEffect(() => {
    const container = box.current;
    if (!container) return;
    const reached = (id: string): Mark | null => {
      const now = waveNow.current;
      if (!now) return null;
      const step = now.wave.stepOf.get(id);
      return step !== undefined && step <= now.shown ? (now.wave.markOf.get(id) ?? null) : null;
    };
    const at = (event: MouseEvent): Point => {
      const frame = container.getBoundingClientRect();
      return { x: event.clientX - frame.left, y: event.clientY - frame.top };
    };
    let instance: ForceGraph3DInstance;
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      instance = (new (ForceGraph3D as any)(container, { rendererConfig: { alpha: true, antialias: true } }) as ForceGraph3DInstance)
        .backgroundColor('rgba(0,0,0,0)')
        .showNavInfo(false)
        .nodeLabel('label')
        .nodeVal('size')
        .nodeColor((node: object) => {
          const point = node as Node3D;
          if (waveNow.current) {
            const mark = reached(point.id);
            return mark ? MARK_COLOR[mark] : DIM_NODE;
          }
          const lit = focus.current;
          return !lit || lit.has(point.id) ? point.color : DIM_NODE;
        })
        .nodeOpacity(0.95)
        .nodeResolution(16)
        .nodeThreeObjectExtend(true)
        .nodeThreeObject((node: object) => {
          const point = node as Node3D;
          const text = new SpriteText(point.label ?? '');
          text.color = palette.text;
          text.textHeight = 2 + scaleRef.current;
          const placed = text as unknown as { position: { set(x: number, y: number, z: number): void } };
          placed.position.set(0, Math.cbrt(point.size ?? 1) * 2 * scaleRef.current + 3, 0);
          return text;
        })
        .linkColor((link: object) => {
          const edge = link as Link3D;
          const own = LINK_COLOR[edge.type] ?? palette.edge;
          if (waveNow.current) return reached(idOf(edge.source)) && reached(idOf(edge.target)) ? own : DIM_LINK;
          const lit = focus.current;
          if (!lit) return own;
          return lit.has(idOf(edge.source)) && lit.has(idOf(edge.target)) ? own : DIM_LINK;
        })
        .linkWidth((link: object) => (isRelation(link as Link3D) ? 0.6 : 0.3))
        .linkOpacity(0.55)
        .linkDirectionalArrowLength((link: object) => (isRelation(link as Link3D) ? 3 : 0))
        .linkDirectionalArrowRelPos(1)
        .linkDirectionalParticleWidth(1.2)
        .linkDirectionalParticleSpeed(0.006)
        .linkThreeObjectExtend(true)
        .linkThreeObject((link: object) => {
          const count = (link as Link3D).count;
          if (count <= 1) return null as never;
          const text = new SpriteText(String(count));
          text.color = LABEL_COLOR;
          text.textHeight = 3.5;
          text.backgroundColor = LABEL_BACKGROUND;
          text.padding = 0.6;
          return text;
        })
        .linkPositionUpdate((sprite: object | null, ends: { start: { x: number; y: number; z: number }; end: { x: number; y: number; z: number } }) => {
          if (!sprite) return;
          const placed = sprite as { position: { x: number; y: number; z: number } };
          placed.position.x = (ends.start.x + ends.end.x) / 2;
          placed.position.y = (ends.start.y + ends.end.y) / 2;
          placed.position.z = (ends.start.z + ends.end.z) / 2;
        })
        .linkHoverPrecision(6)
        .onLinkClick((link: object, event: MouseEvent) => {
          const edge = link as Link3D;
          handlers.current.onEdge(
            [{ source: idOf(edge.source), target: idOf(edge.target), type: edge.type, count: edge.count }],
            at(event),
          );
        })
        .onNodeHover((node: object | null) => {
          if (!waveNow.current) light(node as Node3D | null);
        })
        .onNodeClick((node: object, event: MouseEvent) => {
          const id = (node as Node3D).id;
          const now = Date.now();
          // 這個函式庫沒有雙擊事件：短時間內點同一個節點兩次就當雙擊
          const double = lastClick.current.id === id && now - lastClick.current.at < DOUBLE_CLICK_MS;
          lastClick.current = { id, at: now };
          if (double) handlers.current.onToggle(id);
          else handlers.current.onSelect(id, at(event));
        })
        .onBackgroundClick(() => {
          light(null);
          handlers.current.onSelect(null, null);
        });
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : '3D 畫布無法初始化');
      return;
    }
    scene.current = instance;

    function light(node: Node3D | null) {
      if (node === null) {
        focus.current = null;
      } else {
        const lit = new Set<string>([node.id]);
        neighbours.current.get(node.id)?.forEach((id) => lit.add(id));
        focus.current = lit;
      }
      instance.nodeColor(instance.nodeColor()).linkColor(instance.linkColor());
    }

    // 呼叫與引用的線不該把節點拉在一起：它們只在看影響範圍時出現，不能讓圖因此變形
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const force = instance.d3Force('link') as any;
    if (force) {
      const original = force.strength();
      force.strength((link: Link3D, index: number, links: Link3D[]) =>
        link.type === 'calls' || link.type === 'references' ? 0 : original(link, index, links),
      );
    }

    const observer = new ResizeObserver(() => {
      instance.width(container.clientWidth).height(container.clientHeight);
    });
    observer.observe(container);
    instance.width(container.clientWidth).height(container.clientHeight);
    return () => {
      observer.disconnect();
      try {
        instance._destructor();
      } catch {
        // 解構失敗不影響下一次建立
      }
      scene.current = null;
    };
  }, []);

  // 換圖。沿用舊的節點物件：位置留在原地，新節點從上層的位置長出來
  useEffect(() => {
    const instance = scene.current;
    if (!instance || !view) return;
    const previous = new Map((instance.graphData().nodes as Node3D[]).map((node) => [node.id, node]));
    const first = previous.size === 0;
    const adjacency = new Map<string, Set<string>>();
    const nodes = view.nodes.map((node) => {
      const kept = previous.get(node.id);
      const up = node.parent ? previous.get(node.parent) : undefined;
      const next: Node3D = kept ?? { id: node.id, label: '', type: '', size: 1, color: '' };
      if (!kept && up && up.x !== undefined) {
        next.x = up.x + (Math.random() - 0.5) * 10;
        next.y = (up.y ?? 0) + (Math.random() - 0.5) * 10;
        next.z = (up.z ?? 0) + (Math.random() - 0.5) * 10;
      }
      next.label = node.label;
      next.type = node.type;
      next.size = SIZE[node.type] ?? 3;
      next.color = node.parse_error || node.unresolved_calls ? palette.danger : (COLOR[node.type] ?? palette.file);
      return next;
    });
    const links: Link3D[] = view.edges.map((edge) => {
      for (const [a, b] of [[edge.source, edge.target], [edge.target, edge.source]]) {
        if (!adjacency.has(a)) adjacency.set(a, new Set());
        adjacency.get(a)?.add(b);
      }
      return { source: edge.source, target: edge.target, type: edge.type, count: edge.count };
    });
    neighbours.current = adjacency;
    focus.current = null;
    instance.graphData({ nodes, links });
    flow(instance, motionRef.current, links.length);
    if (!first) return;
    const framed = window.setTimeout(() => instance.zoomToFit(600, 60), 1200);
    return () => window.clearTimeout(framed);
  }, [view]);

  // 影響範圍：先全部變暗，再一層一層亮起來
  useEffect(() => {
    const instance = scene.current;
    if (!instance) return;
    waveNow.current = wave ? { wave, shown: -1 } : null;
    const refresh = () => instance.nodeColor(instance.nodeColor()).linkColor(instance.linkColor());
    refresh();
    if (!wave) return;
    const timers: number[] = [];
    for (let step = 0; step <= wave.steps; step += 1) {
      timers.push(
        window.setTimeout(() => {
          if (waveNow.current) waveNow.current.shown = step;
          refresh();
        }, step * IMPACT_STEP_MS),
      );
    }
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [wave, view]);

  useEffect(() => {
    const instance = scene.current;
    if (!instance || !view) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const link = instance.d3Force('link') as any;
    if (link) link.distance(24 * spacing);
    instance.d3ReheatSimulation();
  }, [spacing, view]);

  useEffect(() => {
    const instance = scene.current;
    if (!instance) return;
    instance.nodeRelSize(2 * nodeScale).nodeThreeObject(instance.nodeThreeObject());
  }, [nodeScale]);

  useEffect(() => {
    const instance = scene.current;
    if (instance) flow(instance, motion, instance.graphData().links.length);
  }, [motion]);

  return (
    <div className="stage">
      {/* 跟 2D 同一組動態背景。3D 的畫布是透明的，所以這三層在它底下透出來。 */}
      <div className="bg-grid" />
      <div className="bg-glow" />
      <div className="bg-scan" />
      <div ref={box} className="canvas" />
      {failure && <div className="failure">3D 無法顯示：{failure}</div>}
    </div>
  );
}

/** 動態：關係線上有往箭頭方向流動的光點；線太多時不放。 */
function flow(instance: ForceGraph3DInstance, motion: boolean, links: number) {
  const on = motion && links <= PARTICLE_MAX_LINKS;
  instance.linkDirectionalParticles((link: object) => (on && isRelation(link as Link3D) ? 2 : 0));
}

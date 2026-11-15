// 畫布，沿用參照專案的操作方式：滑過節點亮起鄰居、點節點看影響範圍一層層亮起、
// 點空白處還原、點線看細節、左下縮放鈕、右下縮圖。新增：雙擊展開或收合、動態效果。
// Cytoscape 實例放在 ref，不進 React state：重畫整張圖會丟掉使用者的平移與縮放。

import cytoscape from 'cytoscape';
import { useEffect, useRef } from 'react';

import type { View } from './api';
import { toElements, type Wave } from './elements';
import { graphStyle, minimapStyle } from './graphStyle';
import { IMPACT_STEP_MS, palette } from './palette';

export interface Point {
  x: number;
  y: number;
}

export interface EdgeInfo {
  source: string;
  target: string;
  type: string;
  count: number;
}

interface Props {
  view: View | null;
  query: string;
  /** 節點間距的倍率：排版完之後把座標等比例拉開 */
  spacing: number;
  /** 節點大小的倍率 */
  nodeScale: number;
  /** 動態效果：節點緩緩漂浮、關係線流動、換圖時滑到新位置 */
  motion: boolean;
  wave: Wave | null;
  onSelect: (node: string | null, at: Point | null) => void;
  onToggle: (node: string) => void;
  onEdge: (edges: EdgeInfo[], at: Point) => void;
}

// 動態效果的上限：圖太大時每一幀都重畫會卡，超過就自動停用
const DRIFT_MAX_NODES = 500;
const FLOW_MAX_EDGES = 800;
const DRIFT_RADIUS = 5; // 漂浮的幅度（畫布座標）
const GLIDE_MS = 650; // 換圖時滑到新位置的時間
const FRAME_MS = 40; // 約 25 fps，夠順又不吃太多 CPU

export function Graph({ view, query, spacing, nodeScale, motion, wave, onSelect, onToggle, onEdge }: Props) {
  const canvasBox = useRef<HTMLDivElement>(null);
  const minimapBox = useRef<HTMLDivElement>(null);
  const viewportBox = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);
  const mini = useRef<cytoscape.Core | null>(null);
  // 節點「真正的位置」。畫面上的位置＝它加上漂浮的偏移，所以任何計算都讀這裡
  const base = useRef(new Map<string, Point>());
  const structure = useRef('');
  const waving = useRef(false);
  const gliding = useRef(false); // 正在滑到新位置：這段時間不漂浮
  const grabbed = useRef<string | null>(null);
  const spacingRef = useRef(spacing);
  const motionRef = useRef(motion);
  motionRef.current = motion;
  const queryRef = useRef(query);
  queryRef.current = query;
  const handlers = useRef({ onSelect, onToggle, onEdge });
  handlers.current = { onSelect, onToggle, onEdge };

  useEffect(() => {
    if (!canvasBox.current || !minimapBox.current) return;
    const main = cytoscape({
      container: canvasBox.current,
      style: graphStyle(nodeScale),
      wheelSensitivity: 0.5,
      minZoom: 0.05,
      maxZoom: 6,
      boxSelectionEnabled: false,
    });
    const map = cytoscape({
      container: minimapBox.current,
      style: minimapStyle,
      userZoomingEnabled: false,
      userPanningEnabled: false,
      boxSelectionEnabled: false,
      autoungrabify: true,
    });
    cy.current = main;
    mini.current = map;

    main.on('mouseover', 'node', (event) => {
      if (waving.current) return;
      main.elements().addClass('dim');
      event.target.closedNeighborhood().removeClass('dim').addClass('hl');
    });
    main.on('mouseout', 'node', () => {
      if (waving.current) return;
      main.elements().removeClass('dim hl');
      highlight(main, queryRef.current);
    });
    main.on('tap', 'node', (event) => handlers.current.onSelect(event.target.id(), event.renderedPosition));
    main.on('dbltap', 'node', (event) => handlers.current.onToggle(event.target.id()));
    main.on('tap', (event) => {
      if (event.target === main) handlers.current.onSelect(null, null);
    });
    main.on('tap', 'edge', (event) => {
      const edges = event.target.parallelEdges().map((edge: cytoscape.EdgeSingular) => ({
        source: edge.source().id(),
        target: edge.target().id(),
        type: edge.data('type') as string,
        count: edge.data('count') as number,
      }));
      handlers.current.onEdge(edges, event.renderedPosition);
    });
    // 拖節點：拖的時候它不漂浮，放開的地方就是它新的真正位置
    main.on('grab', 'node', (event) => {
      grabbed.current = event.target.id();
    });
    main.on('free', 'node', (event) => {
      base.current.set(event.target.id(), { ...event.target.position() });
      grabbed.current = null;
      syncMinimap(main, map, viewportBox.current, base.current);
    });
    main.on('viewport', () => drawViewport(main, map, viewportBox.current));
    map.on('tap', (event) => {
      const zoom = main.zoom();
      main.animate(
        { pan: { x: main.width() / 2 - event.position.x * zoom, y: main.height() / 2 - event.position.y * zoom } },
        { duration: 200 },
      );
    });

    // 右側欄出現或收起時畫布的寬度會變，Cytoscape 不會自己發現
    const observer = new ResizeObserver(() => {
      main.resize();
      map.resize();
      drawViewport(main, map, viewportBox.current);
    });
    observer.observe(canvasBox.current);

    // ── 動態：節點緩緩漂浮、關係線流動 ──
    let last = 0;
    let frame = 0;
    const tick = (now: number) => {
      frame = window.requestAnimationFrame(tick);
      if (now - last < FRAME_MS || !motionRef.current || gliding.current || document.hidden) return;
      last = now;
      const seconds = now / 1000;
      const nodes = main.nodes();
      const drift = nodes.length <= DRIFT_MAX_NODES;
      const flowing = main.edges('.flow');
      if (!drift && flowing.empty()) return;
      main.batch(() => {
        if (drift) {
          nodes.forEach((node) => {
            const at = base.current.get(node.id());
            if (!at || node.id() === grabbed.current) return;
            const phase = phaseOf(node.id());
            node.position({
              x: at.x + DRIFT_RADIUS * Math.sin(seconds * 0.7 + phase),
              y: at.y + DRIFT_RADIUS * Math.cos(seconds * 0.55 + phase * 1.7),
            });
          });
        }
        // 虛線往箭頭的方向流：看得出「誰依賴誰」
        if (flowing.nonempty()) flowing.style('line-dash-offset', -((seconds * 22) % 32));
      });
    };
    frame = window.requestAnimationFrame(tick);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      main.destroy();
      map.destroy();
      cy.current = null;
      mini.current = null;
    };
    // 只建立一次；nodeScale 的變動由下面的 effect 處理
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    cy.current?.style(graphStyle(nodeScale));
  }, [nodeScale]);

  // 動態關掉時：節點回到真正的位置，線變回實線
  useEffect(() => {
    const main = cy.current;
    if (!main) return;
    settle(main, base.current);
    markFlow(main, motion);
  }, [motion]);

  // 換圖。節點有增減才重排：舊節點留在原位，新節點從上層的位置長出來
  useEffect(() => {
    const main = cy.current;
    if (!main || !view) return;
    const known = base.current;
    const { nodes, edges } = toElements(view);
    const shape = nodes.map((node) => node.data.id).join('\n');
    const first = structure.current === '' || main.elements().empty();
    const changed = shape !== structure.current;
    structure.current = shape;
    main.stop(true, false);
    main.batch(() => {
      main.elements().remove();
      main.add([...nodes, ...edges]);
      main.nodes().forEach((node) => {
        const up = node.data('up') as string | undefined;
        const at = known.get(node.id()) ?? (up ? known.get(up) : undefined);
        if (at) node.position({ ...at });
      });
    });
    markFlow(main, motionRef.current);
    if (!changed) {
      syncMinimap(main, mini.current, viewportBox.current, known);
      return;
    }
    // 起點：舊節點在原位，新節點疊在上層的位置上
    const from = new Map<string, Point>();
    main.nodes().forEach((node) => {
      from.set(node.id(), { ...node.position() });
    });
    main
      .layout({
        name: 'cose',
        animate: false,
        randomize: first,
        fit: false,
        padding: 40,
        nodeRepulsion: () => 12000,
        idealEdgeLength: () => 90,
        nodeOverlap: 20,
        numIter: first ? 1500 : 500,
      } as cytoscape.LayoutOptions)
      .run();
    // 排版只決定相對位置；節點之間拉多開由間距倍率決定
    rescale(main, spacingRef.current);
    known.clear();
    main.nodes().forEach((node) => {
      known.set(node.id(), { ...node.position() });
    });
    if (first) frameGraph(main);
    syncMinimap(main, mini.current, viewportBox.current, known);
    if (first || !motionRef.current) return;
    // 從起點滑到新位置，而不是瞬間跳過去
    gliding.current = true;
    main.batch(() => {
      main.nodes().forEach((node) => {
        const start = from.get(node.id());
        if (start) node.position(start);
      });
    });
    main.nodes().forEach((node) => {
      const to = known.get(node.id());
      if (to) node.animate({ position: to }, { duration: GLIDE_MS, easing: 'ease-out-cubic' });
    });
    const done = window.setTimeout(() => {
      gliding.current = false;
    }, GLIDE_MS + 30);
    return () => {
      window.clearTimeout(done);
      gliding.current = false;
    };
  }, [view]);

  // 間距只是幾何縮放、不重跑排版，所以可以邊拖邊套用
  useEffect(() => {
    const main = cy.current;
    if (!main || main.elements().empty()) return;
    main.stop(true, false);
    settle(main, base.current);
    rescale(main, spacing / spacingRef.current);
    spacingRef.current = spacing;
    main.nodes().forEach((node) => {
      base.current.set(node.id(), { ...node.position() });
    });
    syncMinimap(main, mini.current, viewportBox.current, base.current);
  }, [spacing]);

  // 影響範圍：先全部變暗，再一層一層亮起來
  useEffect(() => {
    const main = cy.current;
    if (!main) return;
    main.elements().removeClass('dim hl match impact-origin impact-certain impact-possible impact-candidate');
    waving.current = wave !== null;
    if (!wave) {
      highlight(main, queryRef.current);
      return;
    }
    main.elements().addClass('dim');
    const timers: number[] = [];
    for (let step = 0; step <= wave.steps; step += 1) {
      timers.push(
        window.setTimeout(() => {
          main.nodes().forEach((node) => {
            if (wave.stepOf.get(node.id()) === step) {
              node.removeClass('dim').addClass(`impact-${wave.markOf.get(node.id())}`);
            }
          });
          // 兩端都亮了的線才亮
          main.edges().forEach((edge) => {
            const from = wave.stepOf.get(edge.source().id());
            const to = wave.stepOf.get(edge.target().id());
            if (from !== undefined && to !== undefined && Math.max(from, to) <= step) edge.removeClass('dim');
          });
        }, step * IMPACT_STEP_MS),
      );
    }
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [wave, view]);

  useEffect(() => {
    const main = cy.current;
    if (!main || waving.current) return;
    const matched = highlight(main, query);
    if (matched?.length) main.animate({ center: { eles: matched[0] } }, { duration: 300 });
  }, [query]);

  return (
    <div className="stage">
      <div className="bg-grid" />
      <div className="bg-glow" />
      <div className="bg-scan" />
      <div
        ref={canvasBox}
        className="canvas"
        onPointerDown={(event) => (event.currentTarget.style.cursor = 'grabbing')}
        onPointerUp={(event) => (event.currentTarget.style.cursor = 'grab')}
      />
      <div className="zoom">
        <button onClick={() => zoomBy(cy.current, 1.4)}>＋</button>
        <button onClick={() => zoomBy(cy.current, 1 / 1.4)}>－</button>
        <button onClick={() => cy.current?.animate({ fit: { eles: cy.current.elements(), padding: 40 } }, { duration: 250 })}>⤢</button>
      </div>
      <div className="minimap">
        <div ref={minimapBox} className="minimap-canvas" />
        <div ref={viewportBox} className="minimap-viewport" />
      </div>
    </div>
  );
}

/** 每個節點固定的相位：漂浮時各走各的，不會整張圖一起晃。 */
function phaseOf(id: string): number {
  let hash = 0;
  for (let index = 0; index < id.length; index += 1) hash = (hash * 31 + id.charCodeAt(index)) | 0;
  return (Math.abs(hash) % 628) / 100;
}

/** 把節點放回真正的位置（去掉漂浮的偏移）。 */
function settle(main: cytoscape.Core, base: Map<string, Point>) {
  main.batch(() => {
    main.nodes().forEach((node) => {
      const at = base.get(node.id());
      if (at) node.position({ ...at });
    });
  });
}

/** 關係線（不含骨架）標成會流動的；太多條或動態關掉時不標。 */
function markFlow(main: cytoscape.Core, motion: boolean) {
  const relations = main.edges('[type != "contains"][type != "defines"]');
  main.edges().removeClass('flow').removeStyle('line-dash-offset');
  if (motion && relations.length <= FLOW_MAX_EDGES) relations.addClass('flow');
}

/** 搜尋：名稱符合的發亮，其餘變暗。回傳符合的節點。 */
function highlight(main: cytoscape.Core, query: string) {
  main.elements().removeClass('dim match');
  const wanted = query.trim().toLowerCase();
  if (!wanted) return null;
  const matched = main.nodes().filter((node) => String(node.data('label')).toLowerCase().includes(wanted));
  main.elements().addClass('dim');
  matched.removeClass('dim').addClass('match');
  return matched;
}

function zoomBy(main: cytoscape.Core | null, factor: number) {
  if (!main) return;
  main.animate(
    { zoom: { level: main.zoom() * factor, renderedPosition: { x: main.width() / 2, y: main.height() / 2 } } },
    { duration: 150 },
  );
}

const INITIAL_MIN_ZOOM = 0.8;
const INITIAL_MAX_ZOOM = 1.1;

/** 第一次排完：整張圖塞進畫面；塞進去之後字太小或太大就改成固定倍率、對準專案根。 */
function frameGraph(main: cytoscape.Core) {
  main.fit(undefined, 40);
  const zoom = main.zoom();
  if (zoom >= INITIAL_MIN_ZOOM && zoom <= INITIAL_MAX_ZOOM) return;
  main.zoom(Math.min(Math.max(zoom, INITIAL_MIN_ZOOM), INITIAL_MAX_ZOOM));
  const root = main.nodes('[type = "repo"]');
  main.center(zoom < INITIAL_MIN_ZOOM && root.nonempty() ? root : main.elements());
}

/** 以整張圖的中心為準，把所有節點的座標等比例拉開或收攏。 */
function rescale(main: cytoscape.Core, factor: number) {
  if (factor === 1 || !Number.isFinite(factor) || factor <= 0) return;
  const box = main.nodes().boundingBox();
  const center = { x: (box.x1 + box.x2) / 2, y: (box.y1 + box.y2) / 2 };
  main.batch(() => {
    main.nodes().forEach((node) => {
      const at = node.position();
      node.position({ x: center.x + (at.x - center.x) * factor, y: center.y + (at.y - center.y) * factor });
    });
  });
}

/** 縮圖畫的是節點真正的位置，不跟著漂浮。 */
function syncMinimap(main: cytoscape.Core, map: cytoscape.Core | null, box: HTMLDivElement | null, base: Map<string, Point>) {
  if (!map) return;
  map.elements().remove();
  map.add(
    main.nodes().map((node) => ({
      group: 'nodes' as const,
      data: { id: node.id(), type: node.data('type') },
      position: { ...(base.get(node.id()) ?? node.position()) },
    })),
  );
  map.add(
    main.edges().map((edge) => ({
      group: 'edges' as const,
      data: { id: edge.id(), source: edge.source().id(), target: edge.target().id() },
    })),
  );
  map.fit(undefined, 8);
  drawViewport(main, map, box);
}

/** 在縮圖上框出主畫布目前看到的範圍。 */
function drawViewport(main: cytoscape.Core, map: cytoscape.Core, box: HTMLDivElement | null) {
  if (!box) return;
  const seen = main.extent();
  const zoom = map.zoom();
  const pan = map.pan();
  const left = Math.max(0, seen.x1 * zoom + pan.x);
  const top = Math.max(0, seen.y1 * zoom + pan.y);
  const right = Math.min(map.width(), seen.x2 * zoom + pan.x);
  const bottom = Math.min(map.height(), seen.y2 * zoom + pan.y);
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
  box.style.width = `${Math.max(0, right - left)}px`;
  box.style.height = `${Math.max(0, bottom - top)}px`;
  box.style.borderColor = palette.accent;
}

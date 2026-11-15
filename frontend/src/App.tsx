// 狀態與版面，沿用參照專案：左側欄、上方搜尋列、畫布。
// 圖的運算全在後端：這裡只收集查詢條件（層級、展開了誰、看哪些關係），變了就重新要一次。

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api, EDGE_TYPES, type Detail, type EdgeType, type Externals, type Found, type Impact, type Summary, type View } from './api';
import { EdgeContent, NodeContent } from './DetailBox';
import { shortId, toWave } from './elements';
import { Graph, type EdgeInfo, type Point } from './Graph';
import { Sidebar } from './Sidebar';

// 3D 用到 three.js，體積大：第一次切到 3D 才載入
const Graph3D = lazy(() => import('./Graph3D'));

/** 兩個畫布都常駐，只切可見性：卸載重建會丟掉排好的位置；用 visibility 才保得住尺寸。 */
function Pane({ visible, children }: { visible: boolean; children: React.ReactNode }) {
  return (
    <div className="pane" style={{ visibility: visible ? 'visible' : 'hidden', pointerEvents: visible ? 'auto' : 'none' }}>
      {children}
    </div>
  );
}

/** 右側欄正在顯示的東西：一個節點，或一組線。 */
type Pinned = { node: string } | { edges: EdgeInfo[] };

export function App() {
  const [path, setPath] = useState(() => localStorage.getItem('codegraph.project') ?? '');
  const [project, setProject] = useState('');
  const [summary, setSummary] = useState<Summary | null>(null);
  const [level, setLevel] = useState<number | null>(3);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [collapsed, setCollapsed] = useState<string[]>([]);
  // 呼叫與引用的線很多，平常不畫，點節點看影響範圍時才出現
  const [shown, setShown] = useState<EdgeType[]>(['imports', 'inherits']);
  const [externals, setExternals] = useState<Externals>('grouped');
  // 節點間距的倍率。預設拉開一點，標籤才不會互相蓋住
  const [spacing, setSpacing] = useState(() => Number(localStorage.getItem('codegraph.spacing')) || 2.5);
  // 節點大小的倍率。全部展開或把間距拉開之後，原本的大小會太小
  const [nodeScale, setNodeScale] = useState(() => Number(localStorage.getItem('codegraph.nodeScale')) || 2);
  const [motion, setMotion] = useState(() => localStorage.getItem('codegraph.motion') !== 'off');
  const [renderer, setRenderer] = useState<'2d' | '3d'>('2d');
  // 3D 開過一次之後就留著，切回 2D 也不卸載
  const [used3d, setUsed3d] = useState(false);
  const [view, setView] = useState<View | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [pinned, setPinned] = useState<Pinned | null>(null);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Found[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 連續操作時只認最後一次問的：先送出的回應晚到不能蓋掉它
  const asked = useRef(0);

  const guard = useCallback(async (work: () => Promise<void>) => {
    setLoading(true);
    setError(null);
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '分析失敗');
    } finally {
      setLoading(false);
    }
  }, []);

  const analyze = () =>
    guard(async () => {
      const result = await api.analyze(path.trim());
      localStorage.setItem('codegraph.project', path.trim());
      if (result.root !== project) {
        setExpanded([]);
        setCollapsed([]);
        setTarget(null);
        setPinned(null);
        setFound(null);
      }
      setSummary(result);
      setProject(result.root);
    });

  const options = useMemo(
    // 看影響範圍時四種關係都要：受影響的節點之間靠它們連起來
    () => ({ level, expanded, collapsed, externals, edge_types: target ? EDGE_TYPES : shown }),
    [level, expanded, collapsed, externals, shown, target],
  );

  useEffect(() => {
    if (!project) return;
    const ticket = (asked.current += 1);
    guard(async () => {
      const [nextView, nextImpact] = await Promise.all([
        api.view(project, options),
        target ? api.impact(project, target, options).catch(() => null) : Promise.resolve(null),
      ]);
      if (ticket !== asked.current) return;
      setView(nextView);
      setImpact(nextImpact);
    });
  }, [project, options, target, summary, guard]);

  useEffect(() => {
    setDetail(null);
    if (!project || !target) return;
    api.detail(project, target).then(setDetail, () => setDetail(null));
  }, [project, target, summary]);

  const wave = useMemo(() => toWave(impact), [impact]);

  function select(node: string | null, at: Point | null) {
    if (node === null || at === null) {
      setTarget(null);
      setPinned(null);
      return;
    }
    // 外部套件群組是合出來的節點，沒有影響範圍可言
    setTarget(node.startsWith('extgroup:') ? null : node);
    setPinned({ node });
  }

  function toggle(node: string) {
    const item = view?.nodes.find((n) => n.id === node);
    if (!item || item.children === 0) return;
    const without = (list: string[]) => list.filter((id) => id !== node);
    setExpanded((list) => (item.expanded ? without(list) : [...without(list), node]));
    setCollapsed((list) => (item.expanded ? [...without(list), node] : without(list)));
  }

  function changeLevel(next: number | null) {
    setLevel(next);
    setExpanded([]);
    setCollapsed([]);
  }

  // 讓一個收在上層裡的節點出現在畫面上：展開它的每一層上層
  const reveal = (id: string) =>
    guard(async () => {
      const [hit] = await api.find(project, id);
      if (!hit) return;
      setExpanded((list) => [...new Set([...list, ...hit.ancestors])]);
      setCollapsed((list) => list.filter((item) => !hit.ancestors.includes(item)));
      setFound(null);
      setQuery(hit.label);
    });

  const pinnedNode = pinned && 'node' in pinned ? view?.nodes.find((n) => n.id === pinned.node) : undefined;

  return (
    <div className="layout">
      <Sidebar
        path={path}
        onPathChange={setPath}
        onAnalyze={analyze}
        loading={loading}
        error={error}
        level={level}
        onLevelChange={changeLevel}
        externals={externals}
        onExternalsChange={setExternals}
        spacing={spacing}
        onSpacingChange={(value) => {
          setSpacing(value);
          localStorage.setItem('codegraph.spacing', String(value));
        }}
        nodeScale={nodeScale}
        onNodeScaleChange={(value) => {
          setNodeScale(value);
          localStorage.setItem('codegraph.nodeScale', String(value));
        }}
        motion={motion}
        onMotionChange={(value) => {
          setMotion(value);
          localStorage.setItem('codegraph.motion', value ? 'on' : 'off');
        }}
        renderer={renderer}
        onRendererChange={(next) => {
          setRenderer(next);
          setPinned(null);
          if (next === '3d') setUsed3d(true);
        }}
        shown={target ? EDGE_TYPES : shown}
        onToggleRelation={(type) => setShown((list) => (list.includes(type) ? list.filter((t) => t !== type) : [...list, type]))}
        summary={summary}
        view={view}
      />

      <div className="content">
        <header>
          <input
            className="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setFound(null);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setQuery('');
                setFound(null);
              }
              if (event.key === 'Enter' && project && query.trim()) {
                void guard(async () => setFound(await api.find(project, query.trim())));
              }
            }}
            placeholder="搜尋節點名稱⋯⋯符合的會發亮，其餘變暗"
          />
          {query && <span className="hint">Enter 找收合中的定義 · Esc 還原</span>}
          {found && (
            <div className="results">
              {found.length === 0 && <span className="dim-text">找不到</span>}
              {found.map((hit) => (
                <button key={hit.id} className="link" onClick={() => void reveal(hit.id)}>
                  {shortId(hit.id)} <span className="dim-text">{hit.type}</span>
                </button>
              ))}
            </div>
          )}
        </header>

        <main>
          <Pane visible={renderer === '2d'}>
            <Graph
              view={view}
              query={query}
              spacing={spacing}
              nodeScale={nodeScale}
              motion={motion}
              wave={wave}
              onSelect={select}
              onToggle={toggle}
              onEdge={(edges) => setPinned({ edges })}
            />
          </Pane>
          {used3d && (
            <Pane visible={renderer === '3d'}>
              <Suspense fallback={null}>
                <Graph3D
                  view={view}
                  spacing={spacing}
                  nodeScale={nodeScale}
                  motion={motion}
                  wave={wave}
                  onSelect={select}
                  onToggle={toggle}
                  onEdge={(edges) => setPinned({ edges })}
                />
              </Suspense>
            </Pane>
          )}
        </main>
      </div>

      {/* 右側欄：點了節點或線才出現，點空白處收起 */}
      {pinned && (
        <aside className="panel">
          <button className="close" onClick={() => select(null, null)} title="關閉">
            ×
          </button>
          {'edges' in pinned && <EdgeContent edges={pinned.edges} />}
          {'node' in pinned && pinnedNode && (
            <NodeContent
              node={pinnedNode}
              detail={detail?.id === pinned.node ? detail : null}
              impact={impact?.target === pinned.node ? impact : null}
              onReveal={(id) => void reveal(id)}
            />
          )}
        </aside>
      )}
    </div>
  );
}

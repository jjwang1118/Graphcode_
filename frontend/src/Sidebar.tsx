// 側欄，區塊與順序沿用參照專案：專案路徑、畫布、層級、圖例、統計。

import type { EdgeType, Externals, Summary, View } from './api';
import { palette } from './palette';

export const LEVELS: { value: number | null; label: string }[] = [
  { value: 0, label: '整個專案' },
  { value: 1, label: '第 1 層目錄' },
  { value: 2, label: '第 2 層目錄' },
  { value: 3, label: '第 3 層目錄' },
  { value: 4, label: '第 4 層目錄' },
  { value: 5, label: '第 5 層目錄' },
  { value: null, label: '不收合（最細）' },
];
const EXTERNALS: Record<Externals, string> = {
  full: '每個套件一個節點',
  grouped: '合成一個，可展開',
  hidden: '隱藏',
};
const levelKey = (level: number | null) => (level === null ? 'all' : String(level));

const CLIP: Record<string, string | undefined> = {
  hexagon: 'polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%)',
  diamond: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
  pentagon: 'polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0% 38%)',
  triangle: 'polygon(50% 0%, 100% 100%, 0% 100%)',
};
const SHAPES: [string, string, string][] = [
  ['repo', palette.repo, 'hexagon'],
  ['directory', palette.directory, 'square'],
  ['file', palette.file, 'circle'],
  ['class', palette.class, 'pentagon'],
  ['function', palette.function, 'triangle'],
  ['variable', palette.variable, 'circle'],
  ['external package', palette.external, 'diamond'],
];
const SKELETON: [string, string, string][] = [
  ['contains', palette.edge, '骨架'],
  ['defines', palette.edgeDefines, '宣告'],
];
const RELATIONS: [EdgeType, string, string][] = [
  ['imports', palette.edgeImports, '依賴'],
  ['inherits', palette.edgeInherits, '繼承'],
  ['calls', palette.edgeCalls, '呼叫'],
  ['references', palette.edgeReferences, '引用'],
];
const FRAMES: [string, string, string, string?][] = [
  ['可展開', palette.borderBright, 'solid', '雙擊展開或收合'],
  ['有解不出', palette.danger, 'dashed', '這個節點有呼叫解不出'],
  ['影響：確定', palette.impact, 'solid'],
  ['影響：可能', palette.impact, 'dashed', '多種型別之一，或經父類別方法'],
  ['影響：候選', palette.accent, 'dotted', '解不出的呼叫裡提到這個名字，未確認'],
];

interface Props {
  path: string;
  onPathChange: (path: string) => void;
  onAnalyze: () => void;
  loading: boolean;
  error: string | null;
  level: number | null;
  onLevelChange: (level: number | null) => void;
  externals: Externals;
  onExternalsChange: (externals: Externals) => void;
  spacing: number;
  onSpacingChange: (spacing: number) => void;
  nodeScale: number;
  onNodeScaleChange: (scale: number) => void;
  motion: boolean;
  onMotionChange: (motion: boolean) => void;
  renderer: '2d' | '3d';
  onRendererChange: (renderer: '2d' | '3d') => void;
  shown: EdgeType[];
  onToggleRelation: (type: EdgeType) => void;
  summary: Summary | null;
  view: View | null;
  onShowCycles: () => void;
}

export function Sidebar(props: Props) {
  const { path, loading, summary, view } = props;
  const calls = summary?.uses.calls;
  return (
    <aside className="sidebar">
      <div className="brand">CODEGRAPH</div>

      <Section title="專案路徑">
        <input
          className="field"
          value={path}
          onChange={(event) => props.onPathChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !loading && path) props.onAnalyze();
          }}
          placeholder="/home/you/project"
        />
        <button className="field action" onClick={props.onAnalyze} disabled={loading || !path}>
          {loading ? '分析中…' : '分析'}
        </button>
        {props.error && <div className="error">{props.error}</div>}
      </Section>

      <Section title="畫布">
        <div className="pair">
          {(['2d', '3d'] as const).map((mode) => (
            <button key={mode} className={props.renderer === mode ? 'field action' : 'field'} onClick={() => props.onRendererChange(mode)}>
              {mode.toUpperCase()}
            </button>
          ))}
        </div>
      </Section>

      <Section title="層級">
        <select
          className="field"
          value={levelKey(props.level)}
          onChange={(event) => props.onLevelChange(event.target.value === 'all' ? null : Number(event.target.value))}
        >
          {LEVELS.map((option) => (
            <option key={levelKey(option.value)} value={levelKey(option.value)}>
              {option.label}
            </option>
          ))}
        </select>
        <label className="caption sub">外部套件</label>
        <select className="field" value={props.externals} onChange={(event) => props.onExternalsChange(event.target.value as Externals)}>
          {Object.entries(EXTERNALS).map(([mode, label]) => (
            <option key={mode} value={mode}>
              {label}
            </option>
          ))}
        </select>
        <label className="caption sub">節點間距 {props.spacing.toFixed(1)}</label>
        <input
          type="range"
          className="range"
          min={0.8}
          max={6}
          step={0.1}
          value={props.spacing}
          onChange={(event) => props.onSpacingChange(Number(event.target.value))}
        />
        <label className="caption sub">節點大小 {props.nodeScale.toFixed(1)}</label>
        <input
          type="range"
          className="range"
          min={1}
          max={5}
          step={0.1}
          value={props.nodeScale}
          onChange={(event) => props.onNodeScaleChange(Number(event.target.value))}
        />
        <label className="check" title="節點緩緩漂浮、關係線流動、換圖時滑到新位置。圖太大時自動停用">
          <input type="checkbox" checked={props.motion} onChange={(event) => props.onMotionChange(event.target.checked)} />
          動態
        </label>
      </Section>

      <Section title="圖例">
        {SHAPES.map(([label, color, shape]) => (
          <div key={label} className="legend">
            <span
              style={{
                width: shape === 'hexagon' ? 14 : 11,
                height: shape === 'hexagon' ? 14 : 11,
                background: color,
                borderRadius: shape === 'circle' ? '50%' : shape === 'square' ? 3 : 0,
                clipPath: CLIP[shape],
              }}
            />
            {label}
          </div>
        ))}
        <div className="lines">
          {SKELETON.map(([label, color, note]) => (
            <div key={label} className="line-legend">
              <span className="bar" style={{ background: color }} />
              <span>
                {label}
                <span className="note">{note}</span>
              </span>
            </div>
          ))}
          {RELATIONS.map(([type, color, note]) => (
            <button
              key={type}
              className={props.shown.includes(type) ? 'line-legend' : 'line-legend off'}
              onClick={() => props.onToggleRelation(type)}
              title="點一下顯示或隱藏"
            >
              <span className="bar" style={{ background: color }} />
              <span>
                {type}
                <span className="note">{note}</span>
              </span>
            </button>
          ))}
          <div className="line-legend">
            <span className="count">5</span>
            <span>同一對之間有幾筆</span>
          </div>
        </div>
        <div className="lines">
          {FRAMES.map(([label, color, style, hint]) => (
            <div key={label} className="legend" title={hint}>
              <span className="frame" style={{ borderColor: color, borderStyle: style }} />
              {label}
            </div>
          ))}
        </div>
      </Section>

      {summary && view && (
        <Section title="統計">
          <div className="stats">
            <Stat label="節點" value={view.meta.visible_nodes} />
            <Stat label="邊" value={view.meta.visible_edges} />
            <button className="stat-button" onClick={props.onShowCycles} title="互相 import 的檔案有幾組；點一下看清單">
              <Stat label="循環" value={summary.cycles} />
            </button>
          </div>
          {/* 只在不是 0 的時候顯示：平常沒事就不該佔版面，出事一定要看得到 */}
          {calls && calls.unresolved > 0 && <Row label="呼叫解不出" value={calls.unresolved} hint={`共 ${calls.expressions} 個呼叫；解不出的不會出現在圖上`} />}
          {!summary.uses.available && <Row label="沒有呼叫關係" value={0} />}
          {summary.unresolved_imports > 0 && <Row label="接不到目標" value={summary.unresolved_imports} />}
          {summary.parse_errors.length > 0 && <Row label="解析失敗" value={summary.parse_errors.length} hint={summary.parse_errors.map((e) => e.file).join(', ')} />}
          {summary.missing_dependencies.length > 0 && (
            <Row label="套件未安裝" value={summary.missing_dependencies.length} hint={summary.missing_dependencies.join(', ')} />
          )}
        </Section>
      )}
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="caption">{title}</div>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="stat">{value}</div>
      <div className="caption">{label}</div>
    </div>
  );
}

function Row({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="kv" title={hint}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}

// 畫布的視覺定義，沿用參照專案（codegraph/frontend/src/graph/style.ts）。
// 編碼標準：型別決定形狀、顏色與大小；線的粗細只表達「代表幾筆」。

import type { StylesheetStyle } from 'cytoscape';

import { palette } from './palette';

const rule = (selector: string, style: Record<string, unknown>) => ({ selector, style }) as StylesheetStyle;
const line = (color: string, extra: Record<string, unknown> = {}) => ({
  'line-color': color,
  'target-arrow-color': color,
  ...extra,
});

/**
 * scale：節點大小的倍率。形狀與字一起放大（字放大得慢一點，免得標籤互相蓋住）；
 * 邊框與線的粗細不跟著變，它們各自表達別的事。
 */
export function graphStyle(scale: number): StylesheetStyle[] {
  const size = (base: number) => Math.round(base * scale * 10) / 10;
  const font = (base: number) => Math.round(base * (1 + (scale - 1) * 0.5) * 10) / 10;
  return [
  rule('node', {
    label: 'data(label)',
    color: palette.text,
    'font-size': font(15),
    'font-family': 'ui-monospace, SFMono-Regular, Menlo, monospace',
    'text-valign': 'center',
    'text-halign': 'right',
    'text-margin-x': size(5) + 4,
    'text-max-width': '200px',
    'text-wrap': 'ellipsis',
    'text-outline-color': palette.background,
    'text-outline-width': 3,
    'background-color': palette.file,
    'border-width': 1,
    'border-color': palette.border,
    width: size(15),
    height: size(15),
    'transition-property': 'opacity, border-color, border-width',
    'transition-duration': 180,
  }),
  rule('node[type = "file"]', { shape: 'ellipse', 'background-color': palette.file }),
  rule('node[type = "directory"]', {
    shape: 'round-rectangle',
    'background-color': palette.directory,
    'background-opacity': 0.85,
    width: size(26),
    height: size(26),
    'font-size': font(17),
  }),
  rule('node[type = "repo"]', {
    shape: 'hexagon',
    'background-color': palette.repo,
    width: size(46),
    height: size(46),
    'font-size': font(20),
    'border-width': 2,
    'border-color': palette.repo,
  }),
  rule('node[type = "external_package"]', { shape: 'diamond', 'background-color': palette.external, width: size(20), height: size(20) }),
  rule('node[type = "external_group"]', { shape: 'diamond', 'background-color': palette.external, width: size(28), height: size(28), 'font-size': font(16) }),
  rule('node[type = "class"]', { shape: 'pentagon', 'background-color': palette.class, width: size(13), height: size(13), 'font-size': font(14) }),
  rule('node[type = "function"]', { shape: 'triangle', 'background-color': palette.function, width: size(9), height: size(9), 'font-size': font(13) }),
  rule('node[type = "variable"]', { shape: 'ellipse', 'background-color': palette.variable, width: size(6), height: size(6), 'font-size': font(12) }),
  // 裡面還有東西（雙擊展開）：亮框。形狀與顏色仍歸型別管
  rule('node[collapsed]', { 'border-width': 2, 'border-color': palette.borderBright }),
  rule('node[incomplete]', { 'border-width': 2, 'border-color': palette.danger, 'border-style': 'dashed' }),
  rule('node[parseError]', { 'border-width': 3, 'border-color': palette.danger, 'border-style': 'dashed' }),

  rule('edge', {
    width: 1.4,
    'line-opacity': 0.9,
    'curve-style': 'bezier',
    'target-arrow-shape': 'triangle',
    'arrow-scale': 0.7,
    'transition-property': 'opacity, line-color, width',
    'transition-duration': 180,
    ...line(palette.edge),
  }),
  rule('edge[type = "defines"]', line(palette.edgeDefines)),
  rule('edge[type = "imports"]', line(palette.edgeImports, { 'arrow-scale': 1.1 })),
  rule('edge[type = "inherits"]', line(palette.edgeInherits, { 'arrow-scale': 1.1 })),
  rule('edge[type = "calls"]', line(palette.edgeCalls, { 'arrow-scale': 1.1 })),
  rule('edge[type = "references"]', line(palette.edgeReferences, { 'arrow-scale': 1.1 })),
  rule('edge[count > 1]', {
    label: 'data(count)',
    color: palette.textDim,
    'font-size': font(12),
    'text-background-color': palette.background,
    'text-background-opacity': 0.85,
    'text-background-padding': '2px',
  }),
  rule('edge[count > 2]', { width: 2 }),
  rule('edge[count > 8]', { width: 2.8 }),
  rule('edge[count > 20]', { width: 3.6 }),

  // 動態開啟時關係線是流動的虛線（位移由 Graph.tsx 每一幀更新）
  rule('edge.flow', { 'line-style': 'dashed', 'line-dash-pattern': [10, 6] }),

  // ── 互動狀態 ──
  rule('.dim', { opacity: 0.12 }),
  rule('node.hl', { 'border-width': 3, 'border-color': palette.accent, 'border-style': 'solid', opacity: 1 }),
  rule('edge.hl', { ...line(palette.accent), width: 2, opacity: 1 }),
  rule('node.match', { 'border-width': 3, 'border-color': palette.repo, 'border-style': 'solid', color: palette.repo, opacity: 1 }),
  rule('node:selected', { 'border-width': 3, 'border-color': palette.accent, 'border-style': 'solid' }),

  // ── 影響範圍 ── 起點最粗；確定實線、可能虛線、候選點線（換色）
  rule('node.impact-origin', { 'border-width': 5, 'border-color': palette.impact, 'border-style': 'solid', color: palette.impact, opacity: 1 }),
  rule('node.impact-certain', { 'border-width': 3, 'border-color': palette.impact, 'border-style': 'solid', opacity: 1 }),
  rule('node.impact-possible', { 'border-width': 3, 'border-color': palette.impact, 'border-style': 'dashed', opacity: 1 }),
  rule('node.impact-candidate', { 'border-width': 3, 'border-color': palette.accent, 'border-style': 'dotted', opacity: 1 }),
  ];
}

// 縮圖不需要標籤與箭頭，畫得越輕越好。
export const minimapStyle: StylesheetStyle[] = [
  rule('node', { label: '', 'background-color': palette.file, width: 6, height: 6, 'border-width': 0 }),
  rule('node[type = "directory"]', { 'background-color': palette.directory, width: 8, height: 8 }),
  rule('node[type = "repo"]', { 'background-color': palette.repo, width: 12, height: 12 }),
  rule('node[type = "external_package"], node[type = "external_group"]', { 'background-color': palette.external, width: 7, height: 7 }),
  rule('node[type = "class"]', { 'background-color': palette.class, width: 5, height: 5 }),
  rule('node[type = "function"]', { 'background-color': palette.function, width: 4, height: 4 }),
  rule('edge', { width: 1, 'line-color': palette.edge, 'curve-style': 'haystack', 'target-arrow-shape': 'none' }),
];

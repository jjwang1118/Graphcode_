// 配色沿用參照專案（codegraph/frontend/src/graph/style.ts）：型別決定形狀與顏色。

export const palette = {
  background: '#0a0d14',
  panel: '#11151f',
  border: '#1e2536',
  borderBright: '#8fa3c4',
  text: '#c8d3e3',
  textDim: '#6b7a94',
  repo: '#f5c451',
  directory: '#7de2ff',
  file: '#5b6b8c',
  class: '#d97fb8',
  function: '#9c8f7a',
  variable: '#c9a86a',
  external: '#f0883e',
  edge: '#46705c',
  edgeDefines: '#7a6a8f',
  edgeImports: '#7aa2e3',
  edgeInherits: '#d97fb8',
  edgeCalls: '#5eead4',
  edgeReferences: '#c9a86a',
  impact: '#5eead4',
  danger: '#ff6b6b',
  accent: '#a78bfa',
};

/** 影響範圍一層一層亮起來的間隔（毫秒）。 */
export const IMPACT_STEP_MS = 300;

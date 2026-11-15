// API 的資料 → 畫布要的形狀。所有形狀轉換集中在這裡，元件不直接拼 element。

import type { ElementDefinition } from 'cytoscape';

import type { Impact, View } from './api';

export function toElements(view: View): { nodes: ElementDefinition[]; edges: ElementDefinition[] } {
  const nodes = view.nodes.map((node) => ({
    group: 'nodes' as const,
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      up: node.parent,
      // 只在成立時才有這個欄位：樣式用「有沒有這個欄位」判斷
      ...(node.children > 0 && !node.expanded ? { collapsed: 1 } : {}),
      ...(node.unresolved_calls ? { incomplete: node.unresolved_calls } : {}),
      ...(node.parse_error ? { parseError: 1 } : {}),
    },
  }));
  const edges = view.edges.map((edge) => ({
    group: 'edges' as const,
    data: { id: edge.id, source: edge.source, target: edge.target, type: edge.type, count: edge.count },
  }));
  return { nodes, edges };
}

export type Mark = 'origin' | 'certain' | 'possible' | 'candidate';
const RANK: Record<Mark, number> = { origin: 0, certain: 1, possible: 2, candidate: 3 };

/** 影響範圍在畫面上怎麼亮：每個看得見的節點在第幾步亮、亮成哪一種。 */
export interface Wave {
  stepOf: Map<string, number>;
  markOf: Map<string, Mark>;
  steps: number;
}

export function toWave(impact: Impact | null): Wave | null {
  if (!impact) return null;
  const stepOf = new Map<string, number>();
  const markOf = new Map<string, Mark>();
  // 受影響的節點可能收在上層裡：亮在「畫面上代表它的節點」上，取最早的一步、最強的一種
  const put = (id: string, step: number, mark: Mark) => {
    const shown = impact.visible[id];
    if (!shown) return;
    const current = markOf.get(shown);
    if (current === undefined || RANK[mark] < RANK[current]) markOf.set(shown, mark);
    stepOf.set(shown, Math.min(stepOf.get(shown) ?? Infinity, step));
  };
  impact.scope.forEach((id) => put(id, 0, 'origin'));
  impact.levels.forEach((level, index) => level.forEach((entry) => put(entry.id, index + 1, entry.certainty)));
  const last = impact.levels.length + 1;
  impact.candidates.forEach((item) => put(item.id, last, 'candidate'));
  return { stepOf, markOf, steps: Math.max(0, ...stepOf.values()) };
}

export function shortId(id: string): string {
  const [, rest] = id.split(/:(.*)/s);
  return rest ?? id;
}

/** 顯示用的短名：`__init__.py` 帶上資料夾，其餘只留最後一段。 */
export function shortName(id: string): string {
  const path = shortId(id);
  if (path.includes('::')) return path.split('::').pop()!;
  const parts = path.split('/');
  const last = parts[parts.length - 1];
  return last === '__init__.py' && parts.length > 1 ? `${parts[parts.length - 2]}/${last}` : last;
}

// 後端 API 的型別與呼叫。契約：docs/spec/web.md。前端不做任何圖的運算。

export type EdgeType = 'imports' | 'calls' | 'inherits' | 'references';
export const EDGE_TYPES: EdgeType[] = ['imports', 'calls', 'inherits', 'references'];
export type Externals = 'full' | 'grouped' | 'hidden';
export type EdgeKind = EdgeType | 'contains' | 'defines';

export interface ViewNode {
  id: string;
  type: string;
  label: string;
  children: number;
  expanded: boolean;
  parent?: string;
  line?: number;
  end_line?: number;
  signature?: string;
  category?: string;
  parse_error?: string;
  unresolved_calls?: number;
}

export interface ViewEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeKind;
  count: number;
}

export interface View {
  nodes: ViewNode[];
  edges: ViewEdge[];
  meta: { visible_nodes: number; visible_edges: number; total_nodes: number; total_edges: number };
}

export type Certainty = 'certain' | 'possible';

export interface ImpactEntry {
  id: string;
  relation: string;
  certainty: Certainty;
  lines: number[];
  through: string;
}

export interface Impact {
  target: string;
  scope: string[];
  levels: ImpactEntry[][];
  overridden_by: string[];
  candidates: { id: string; line: number; text: string; reason: string; already_listed: boolean }[];
  completeness: {
    affected: number;
    certain: number;
    possible: number;
    candidates: number;
    unresolved_calls_in_project: number | null;
    uses_available: boolean;
  };
  visible: Record<string, string | null>;
}

export type Reliability = 'exact' | 'inferred' | 'heuristic';
type Block<T> = T & { reliability: Reliability; note?: string | null };

export interface Detail {
  id: string;
  type: string;
  file: string | null;
  line?: number;
  end_line?: number;
  interface?: Block<{
    signature?: string;
    decorators?: string[];
    is_async?: boolean;
    is_method?: boolean;
    docstring?: string | null;
    bases?: string[];
    members?: string[];
  }>;
  calls: Block<{
    local: { target: string; lines: number[]; via?: string; ambiguous?: boolean }[];
    external: { callee: string; lines: number[] }[];
    unresolved: { line: number; text: string; reason: string }[];
  }>;
  references: Block<{ targets: string[] }>;
  side_effects: Block<{
    direct: Record<string, { callee: string }[]>;
    indirect: Record<string, { callee: string; in: string }[]>;
  }>;
  state?: Block<{ receiver: string | null; reads: string[]; writes: string[]; global_writes: string[] }>;
  raises?: Block<{ exceptions: string[] }>;
  returns?: Block<{ return_statements: number; is_generator: boolean }>;
  source: Block<{ available: boolean; text: string | null }>;
}

export interface Found {
  id: string;
  type: string;
  label: string;
  line: number | null;
  signature: string | null;
  ancestors: string[];
}

export interface Summary {
  source: string;
  root: string;
  python: { executable: string; version: string };
  counts: { nodes: Record<string, number>; edges: Record<string, number> };
  imports: Record<string, number>;
  uses: { available: boolean; calls?: { expressions: number; resolved: number; unresolved: number } };
  missing_dependencies: string[];
  parse_errors: { file: string }[];
  unresolved_imports: number;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export interface ViewOptions {
  level: number | null; // 0＝只有專案根、n＝到第 n 層目錄、null＝不收合
  expanded: string[];
  collapsed: string[];
  edge_types: EdgeType[];
  externals: Externals;
}

export const api = {
  analyze: (project: string, force = false) => post<Summary>('analyze', { project, force }),
  view: (project: string, options: ViewOptions) => post<View>('view', { project, ...options }),
  find: (project: string, name: string) => post<Found[]>('find', { project, name }),
  detail: (project: string, target: string) => post<Detail>('detail', { project, target }),
  impact: (project: string, target: string, options: ViewOptions) =>
    post<Impact>('impact', { project, target, ...options }),
};

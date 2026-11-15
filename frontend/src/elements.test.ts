import cytoscape from 'cytoscape';
import { describe, expect, it } from 'vitest';

import type { Impact, View } from './api';
import { shortId, shortName, toElements, toWave } from './elements';

const view: View = {
  nodes: [
    { id: 'repo:.', type: 'repo', label: 'proj', children: 1, expanded: true },
    { id: 'dir:app', type: 'directory', label: 'app', children: 2, expanded: true, parent: 'repo:.' },
    { id: 'file:app/a.py', type: 'file', label: 'a.py', children: 3, expanded: false, parent: 'dir:app', unresolved_calls: 2 },
    { id: 'file:app/b.py', type: 'file', label: 'b.py', children: 0, expanded: false, parent: 'dir:app' },
    { id: 'extgroup:stdlib', type: 'external_group', label: '標準庫（2）', children: 2, expanded: false },
  ],
  edges: [
    { id: 'c1', source: 'repo:.', target: 'dir:app', type: 'contains', count: 1 },
    { id: 'e1', source: 'file:app/a.py', target: 'file:app/b.py', type: 'calls', count: 6 },
    { id: 'e2', source: 'file:app/b.py', target: 'extgroup:stdlib', type: 'imports', count: 1 },
  ],
  meta: { visible_nodes: 5, visible_edges: 3, total_nodes: 20, total_edges: 30 },
};

const impact = {
  scope: ['function:app/b.py::f'],
  levels: [
    [{ id: 'function:app/a.py::g', relation: 'calls', certainty: 'possible', lines: [], through: '' }],
    [{ id: 'function:app/a.py::h', relation: 'calls', certainty: 'certain', lines: [], through: '' }],
  ],
  candidates: [
    { id: 'function:gone.py::x', line: 1, text: 'f', reason: '', already_listed: false },
    { id: 'function:app/c.py::y', line: 2, text: 'f', reason: '', already_listed: false },
  ],
  visible: {
    'function:app/b.py::f': 'file:app/b.py',
    'function:app/a.py::g': 'file:app/a.py',
    'function:app/a.py::h': 'file:app/a.py',
    'function:gone.py::x': null,
    'function:app/c.py::y': 'dir:app',
  },
} as unknown as Impact;

describe('toElements', () => {
  it('節點帶型別，可展開與有解不出的各有標記欄位', () => {
    const { nodes, edges } = toElements(view);
    const a = nodes.find((n) => n.data.id === 'file:app/a.py')!;
    expect(a.data).toMatchObject({ label: 'a.py', type: 'file', collapsed: 1, incomplete: 2, up: 'dir:app' });
    const b = nodes.find((n) => n.data.id === 'file:app/b.py')!;
    expect('collapsed' in b.data).toBe(false);
    expect('incomplete' in b.data).toBe(false);
    expect(edges.find((e) => e.data.id === 'e1')!.data).toMatchObject({ type: 'calls', count: 6 });
  });

  it('產出的 element 能被 Cytoscape 接受並排版', () => {
    const { nodes, edges } = toElements(view);
    const cy = cytoscape({ headless: true, elements: [...nodes, ...edges] });
    expect(cy.nodes().length).toBe(5);
    expect(cy.edges().length).toBe(3);
    expect(cy.nodes('[collapsed]').length).toBe(2);
    cy.layout({ name: 'cose', animate: false }).run();
  });
});

describe('toWave', () => {
  it('亮在看得見的代表節點上：取最早的一步、最強的一種', () => {
    const wave = toWave(impact)!;
    expect(wave.markOf.get('file:app/b.py')).toBe('origin');
    expect(wave.stepOf.get('file:app/b.py')).toBe(0);
    // a.py 同時代表「可能」（第 1 層）與「確定」（第 2 層）
    expect(wave.markOf.get('file:app/a.py')).toBe('certain');
    expect(wave.stepOf.get('file:app/a.py')).toBe(1);
    // 候選最後才亮；看不見的不算
    expect(wave.markOf.get('dir:app')).toBe('candidate');
    expect(wave.stepOf.get('dir:app')).toBe(3);
    expect(wave.markOf.size).toBe(3);
    expect(wave.steps).toBe(3);
  });
  it('沒有影響範圍時回 null', () => {
    expect(toWave(null)).toBeNull();
  });
});

describe('名字', () => {
  it('shortId 去掉型別前綴', () => {
    expect(shortId('function:app/a.py::Foo.go')).toBe('app/a.py::Foo.go');
  });
  it('shortName 只留最後一段，__init__.py 帶上資料夾', () => {
    expect(shortName('function:app/a.py::Foo.go')).toBe('Foo.go');
    expect(shortName('file:app/pkg/__init__.py')).toBe('pkg/__init__.py');
    expect(shortName('file:app/a.py')).toBe('a.py');
  });
});

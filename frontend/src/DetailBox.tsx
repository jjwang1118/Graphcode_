// 右側欄的內容：節點的細節與影響範圍，或一條線代表的關係。
// 排版原則：每一類一個可收合的區塊、標題列有筆數；清單一筆一行、太長就省略（滑鼠提示有全名）；
// 區塊內容太多時在區塊裡捲動，不把整欄撐長。說明文字收在滑鼠提示裡。
// （檔名沿用舊的；原本是浮在點擊處的小視窗，使用者要求改成固定在右側。）

import type { CycleGroup, Cycles, Detail, Impact, Reliability, ViewNode } from './api';
import { shortId, shortName } from './elements';
import type { EdgeInfo } from './Graph';

const RELIABILITY: Record<Reliability, string> = { exact: '準確', inferred: '推論', heuristic: '估計' };
const RELIABILITY_HINT: Record<Reliability, string> = {
  exact: '直接來自原始碼',
  inferred: '引擎解析的結果，可能不完整',
  heuristic: '依對照表估計，沒列到不代表沒有',
};

interface SectionProps {
  title: string;
  count?: number;
  tag?: Reliability;
  hint?: string | null;
  open?: boolean;
  children: React.ReactNode;
}

/** 一個可收合的區塊。標題列：名稱、筆數、可靠度。 */
function Section({ title, count, tag, hint, open = false, children }: SectionProps) {
  return (
    <details className="block" open={open}>
      <summary>
        <span className="name">{title}</span>
        {count !== undefined && <span className="count">{count}</span>}
        {tag && (
          <span className={`tag tag-${tag}`} title={hint ?? RELIABILITY_HINT[tag]}>
            {RELIABILITY[tag]}
          </span>
        )}
      </summary>
      <div className="body">{children}</div>
    </details>
  );
}

/** 區塊裡的小分組（例如影響範圍的每一層）。 */
function Group({ label, count, tone, open = false, children }: { label: string; count: number; tone?: string; open?: boolean; children: React.ReactNode }) {
  return (
    <details className="group" open={open}>
      <summary className={tone}>
        {label}
        <span className="count">{count}</span>
      </summary>
      <div className="list">{children}</div>
    </details>
  );
}

/** 一筆一行：左邊是內容（太長省略），右邊是行號之類的小字。 */
function Line({ children, side, title, tone }: { children: React.ReactNode; side?: React.ReactNode; title?: string; tone?: string }) {
  return (
    <div className={tone ? `line ${tone}` : 'line'} title={title}>
      <span className="main">{children}</span>
      {side !== undefined && side !== '' && <span className="side">{side}</span>}
    </div>
  );
}

const lines = (list: number[]) => (list.length === 0 ? '' : `${list.slice(0, 3).join(',')}${list.length > 3 ? '…' : ''}`);

export function EdgeContent({ edges }: { edges: EdgeInfo[] }) {
  const [first] = edges;
  return (
    <>
      <div className="p-title">
        {shortName(first.source)} → {shortName(first.target)}
      </div>
      <div className="p-meta" title={`${shortId(first.source)} → ${shortId(first.target)}`}>
        {edges.length} 種關係
      </div>
      <div className="list top">
        {edges.map((edge) => (
          <Line key={`${edge.type}:${edge.source}:${edge.target}`} side={`×${edge.count}`} title={`${shortId(edge.source)} → ${shortId(edge.target)}`}>
            {edge.type}
            {edges.some((other) => other.source !== edge.source) && <span className="dim-text"> {shortName(edge.source)} →</span>}
          </Line>
        ))}
      </div>
    </>
  );
}

function CycleGroups({ groups, onReveal }: { groups: CycleGroup[]; onReveal: (id: string) => void }) {
  return (
    <>
      {groups.slice(0, 40).map((group, index) => (
        <Group key={index} label={`${group.size} 個檔案`} count={group.edges.length} open={index < 3}>
          {group.edges.map((edge) => (
            <Line key={`${edge.source}>${edge.target}`} side={`行 ${edge.lines.slice(0, 3).join(',')}`} title={`${edge.source} → ${edge.target}`}>
              <button className="link" onClick={() => onReveal(`file:${edge.source}`)}>
                {shortName(`file:${edge.source}`)}
              </button>
              {' → '}
              <button className="link" onClick={() => onReveal(`file:${edge.target}`)}>
                {shortName(`file:${edge.target}`)}
              </button>
            </Line>
          ))}
        </Group>
      ))}
      {groups.length > 40 && <div className="more">只列出 40 組，共 {groups.length} 組</div>}
    </>
  );
}

export function CyclesContent({ cycles, onReveal }: { cycles: Cycles; onReveal: (id: string) => void }) {
  // 只有連函式裡的 import 也算才成圈的那幾組
  const strict = new Set(cycles.module.components.map((group) => group.files.join('|')));
  const extra = cycles.with_deferred.components.filter((group) => !strict.has(group.files.join('|')));
  return (
    <>
      <div className="p-title">循環依賴</div>
      <div className="p-meta" title="TYPE_CHECKING 底下的 import 不算">
        互相 import 的檔案
      </div>
      <Section title="檔案層的 import" count={cycles.module.count} open hint="一 import 就會發生">
        {cycles.module.count === 0 ? <div className="more">沒有</div> : <CycleGroups groups={cycles.module.components} onReveal={onReveal} />}
      </Section>
      {extra.length > 0 && (
        <Section title="含函式內的 import" count={extra.length} open>
          <CycleGroups groups={extra} onReveal={onReveal} />
        </Section>
      )}
    </>
  );
}

interface NodeProps {
  node: ViewNode;
  detail: Detail | null;
  impact: Impact | null;
  onReveal: (id: string) => void;
}

export function NodeContent({ node, detail, impact, onReveal }: NodeProps) {
  const link = (id: string) => (
    <button className="link" onClick={() => onReveal(id)}>
      {shortName(id)}
    </button>
  );
  const face = detail?.interface;
  return (
    <>
      <div className="p-title" title={node.id}>
        {node.label}
      </div>
      <div className="p-meta">
        {node.type}
        {node.line ? ` · 行 ${node.line}–${node.end_line}` : ''}
        {node.parse_error ? ' · 語法錯誤' : ''}
      </div>
      {face?.signature !== undefined && (
        <code className="block-code">
          {face.is_async ? 'async ' : ''}
          {shortName(node.id)}
          {face.signature}
        </code>
      )}
      {face?.bases && face.bases.length > 0 && <div className="p-meta">繼承 {face.bases.join(', ')}</div>}
      {face?.docstring && <div className="p-doc">{face.docstring.trim().split('\n')[0]}</div>}

      {impact && <ImpactBlock impact={impact} link={link} />}
      {detail && <DetailBlocks detail={detail} link={link} />}
    </>
  );
}

function ImpactBlock({ impact, link }: { impact: Impact; link: (id: string) => React.ReactNode }) {
  const done = impact.completeness;
  const unresolved = done.unresolved_calls_in_project ?? 0;
  return (
    <Section title="影響範圍" count={done.affected} open>
      <div className="chips">
        <span className="chip impact-text">確定 {done.certain}</span>
        <span className="chip impact-text faint" title="多種型別之一，或經父類別／Protocol 的方法">
          可能 {done.possible}
        </span>
        <span className="chip accent" title="解不出的呼叫裡提到這個名字，未確認">
          候選 {done.candidates}
        </span>
        {unresolved > 0 && (
          <span className="chip danger" title="專案內解不出的呼叫數；真正受影響的可能更多">
            ⚠ {unresolved}
          </span>
        )}
      </div>
      {impact.levels.map((level, index) => (
        <Group key={index} label={`第 ${index + 1} 層`} count={level.length} open={index === 0}>
          {level.slice(0, 100).map((entry) => (
            <Line
              key={entry.id}
              tone={entry.certainty === 'certain' ? undefined : 'faint'}
              side={entry.certainty === 'certain' ? entry.relation : `可能 · ${entry.relation}`}
              title={shortId(entry.id)}
            >
              {link(entry.id)}
            </Line>
          ))}
          {level.length > 100 && <div className="more">只列出 100 筆，共 {level.length} 筆</div>}
        </Group>
      ))}
      {impact.overridden_by.length > 0 && (
        <Group label="被覆寫" count={impact.overridden_by.length}>
          {impact.overridden_by.map((id) => (
            <Line key={id} title={shortId(id)}>
              {link(id)}
            </Line>
          ))}
        </Group>
      )}
      {impact.candidates.length > 0 && (
        <Group label="候選" count={impact.candidates.length} tone="accent">
          {impact.candidates.slice(0, 60).map((item, index) => (
            <Line key={index} side={`行 ${item.line}`} title={`${item.text}\n${item.reason}`}>
              {link(item.id)} <code>{item.text}</code>
            </Line>
          ))}
          {impact.candidates.length > 60 && <div className="more">只列出 60 筆，共 {impact.candidates.length} 筆</div>}
        </Group>
      )}
    </Section>
  );
}

function DetailBlocks({ detail, link }: { detail: Detail; link: (id: string) => React.ReactNode }) {
  const { calls, side_effects: effects, state, raises, source } = detail;
  const callCount = calls.local.length + calls.external.length + calls.unresolved.length;
  const direct = Object.entries(effects.direct);
  const indirect = Object.entries(effects.indirect);
  const stateCount = state ? state.reads.length + state.writes.length + state.global_writes.length : 0;
  const callees = (items: { callee: string }[]) => [...new Set(items.map((i) => i.callee))].join('\n');
  return (
    <>
      {callCount > 0 && (
        <Section title="呼叫" count={callCount} tag={calls.reliability} hint="依原始碼位置，不是執行順序" open>
          {calls.local.length > 0 && (
            <Group label="專案內" count={calls.local.length} open>
              {calls.local.map((call, index) => (
                <Line key={index} tone={call.ambiguous ? 'faint' : undefined} side={lines(call.lines)} title={shortId(call.target)}>
                  {link(call.target)}
                </Line>
              ))}
            </Group>
          )}
          {calls.unresolved.length > 0 && (
            <Group label="解不出" count={calls.unresolved.length} tone="danger" open>
              {calls.unresolved.map((item, index) => (
                <Line key={index} side={String(item.line)} title={item.reason}>
                  <code>{item.text}</code>
                </Line>
              ))}
            </Group>
          )}
          {calls.external.length > 0 && (
            <Group label="外部" count={calls.external.length}>
              {calls.external.map((call, index) => (
                <Line key={index} tone="dim-text" side={lines(call.lines)} title={call.callee}>
                  {call.callee}
                </Line>
              ))}
            </Group>
          )}
        </Section>
      )}
      {detail.references.targets.length > 0 && (
        <Section title="引用" count={detail.references.targets.length} tag={detail.references.reliability}>
          <div className="list">
            {detail.references.targets.map((id) => (
              <Line key={id} side={id.split(':')[0]} title={shortId(id)}>
                {link(id)}
              </Line>
            ))}
          </div>
        </Section>
      )}
      {state && stateCount > 0 && (
        <Section title="狀態" count={stateCount} tag={state.reliability} hint={state.note} open>
          <div className="pairs">
            {state.reads.length > 0 && (
              <>
                <span>讀</span>
                <span>{state.reads.join(', ')}</span>
              </>
            )}
            {state.writes.length > 0 && (
              <>
                <span className="warn">寫</span>
                <span>{state.writes.join(', ')}</span>
              </>
            )}
            {state.global_writes.length > 0 && (
              <>
                <span className="warn">全域</span>
                <span>{state.global_writes.join(', ')}</span>
              </>
            )}
          </div>
        </Section>
      )}
      {direct.length + indirect.length > 0 && (
        <Section title="副作用" count={direct.length + indirect.length} tag={effects.reliability} hint={effects.note} open>
          <div className="chips">
            {direct.map(([category, items]) => (
              <span key={category} className="chip warn" title={callees(items)}>
                {category}
              </span>
            ))}
            {indirect.map(([category, items]) => (
              <span key={`i-${category}`} className="chip dim-text" title={`由被呼叫者造成\n${callees(items)}`}>
                {category}（間接）
              </span>
            ))}
          </div>
        </Section>
      )}
      {raises && raises.exceptions.length > 0 && (
        <Section title="例外" count={raises.exceptions.length} tag={raises.reliability} hint={raises.note} open>
          <div className="chips">
            {raises.exceptions.map((name) => (
              <span key={name} className="chip">
                {name}
              </span>
            ))}
          </div>
        </Section>
      )}
      {source.available && source.text && detail.type !== 'file' && (
        <Section title="原始碼" count={source.text.split('\n').length} open={source.text.split('\n').length <= 25}>
          <pre>{source.text}</pre>
        </Section>
      )}
    </>
  );
}

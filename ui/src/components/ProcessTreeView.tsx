import { useMemo, useState } from 'react';
import type { ActivityEvent } from '../types';

type Props = {
  events: ActivityEvent[];
  rootPid: number;
};

type Node = {
  pid: number;
  ppid?: number | null;
  name?: string | null;
  count: number;
  children: number[];
};

function buildTree(events: ActivityEvent[]): Map<number, Node> {
  const nodes = new Map<number, Node>();

  const ensure = (pid: number, ppid?: number | null, name?: string | null): Node => {
    let node = nodes.get(pid);
    if (!node) {
      node = { pid, ppid: ppid ?? null, count: 0, children: [], name: name ?? null };
      nodes.set(pid, node);
    } else {
      if (ppid != null && node.ppid == null) node.ppid = ppid;
      if (name && !node.name) node.name = name;
    }
    return node;
  };

  for (const event of events) {
    if (event.pid == null) continue;
    const name =
      event.kind === 'process'
        ? (event.details as Record<string, unknown> | undefined)?.['name'] as string | undefined
        : undefined;
    const node = ensure(event.pid, event.ppid, name ?? null);
    node.count += 1;
    if (event.ppid != null) {
      ensure(event.ppid);
    }
  }

  for (const node of nodes.values()) {
    if (node.ppid != null && nodes.has(node.ppid) && node.ppid !== node.pid) {
      const parent = nodes.get(node.ppid)!;
      if (!parent.children.includes(node.pid)) parent.children.push(node.pid);
    }
  }
  return nodes;
}

function TreeRow({
  node,
  nodes,
  depth,
  collapsed,
  toggle,
}: {
  node: Node;
  nodes: Map<number, Node>;
  depth: number;
  collapsed: Set<number>;
  toggle: (pid: number) => void;
}) {
  const isCollapsed = collapsed.has(node.pid);
  const hasChildren = node.children.length > 0;
  return (
    <div>
      <div
        className="flex items-center gap-2 border-b border-slate-900 px-3 py-1.5 text-xs"
        style={{ paddingLeft: 12 + depth * 16 }}
      >
        <button
          onClick={() => toggle(node.pid)}
          className={`w-4 text-slate-500 ${hasChildren ? 'hover:text-slate-200' : 'invisible'}`}
        >
          {hasChildren ? (isCollapsed ? '▸' : '▾') : '·'}
        </button>
        <span className="font-mono text-slate-300">pid {node.pid}</span>
        {node.name && <span className="truncate text-slate-400">{node.name}</span>}
        <span className="ml-auto text-[10px] text-slate-500">{node.count} events</span>
      </div>
      {!isCollapsed &&
        node.children.map((childPid) => {
          const child = nodes.get(childPid);
          if (!child) return null;
          return (
            <TreeRow
              key={childPid}
              node={child}
              nodes={nodes}
              depth={depth + 1}
              collapsed={collapsed}
              toggle={toggle}
            />
          );
        })}
    </div>
  );
}

export function ProcessTreeView({ events, rootPid }: Props) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  const nodes = useMemo(() => buildTree(events), [events]);

  const toggle = (pid: number) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  };

  const root = nodes.get(rootPid);

  if (!root) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-4 text-center text-xs text-slate-500">
        No process events recorded yet for pid {rootPid}.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <TreeRow node={root} nodes={nodes} depth={0} collapsed={collapsed} toggle={toggle} />
    </div>
  );
}

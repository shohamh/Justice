import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import UnitCalendar from "../components/UnitCalendar";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import { useAuth } from "../auth/AuthContext";

function treeOrder(nodes: NodeDTO[]): NodeDTO[] {
  const ids = new Set(nodes.map((n) => n.id));
  const byParent = new Map<string | null, NodeDTO[]>();
  for (const n of nodes) {
    const key = n.parent_id && ids.has(n.parent_id) ? n.parent_id : null;
    byParent.set(key, [...(byParent.get(key) ?? []), n]);
  }
  const result: NodeDTO[] = [];
  function walk(parentId: string | null) {
    for (const n of byParent.get(parentId) ?? []) {
      result.push(n);
      walk(n.id);
    }
  }
  walk(null);
  return result;
}

function buildDepthMap(nodes: NodeDTO[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const n of nodes) {
    map.set(n.id, (n.path_ids?.length ?? 1) - 1);
  }
  return map;
}

interface NodeSearchDropdownProps {
  nodes: NodeDTO[];
  depthMap: Map<string, number>;
  value: string;
  onChange: (id: string) => void;
}

function NodeSearchDropdown({ nodes, depthMap, value, onChange }: NodeSearchDropdownProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = nodes.find((n) => n.id === value);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return nodes;
    return nodes.filter((n) => n.name.toLowerCase().includes(q));
  }, [nodes, search]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function handleOpen() {
    setOpen(true);
    setSearch("");
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  function handleSelect(id: string) {
    onChange(id);
    setOpen(false);
    setSearch("");
  }

  return (
    <div ref={containerRef} className="relative w-72" dir="rtl">
      {open ? (
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="חיפוש..."
          className="w-full border rounded p-1.5 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400"
        />
      ) : (
        <button
          type="button"
          onClick={handleOpen}
          className="w-full flex items-center justify-between border rounded p-1.5 text-sm text-right dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 hover:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          <span className="truncate">{selected?.name ?? "—"}</span>
          <span className="text-gray-400 mr-1">▾</span>
        </button>
      )}

      {open && (
        <ul className="absolute z-50 mt-1 w-full max-h-72 overflow-y-auto bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded shadow-lg text-sm">
          {filtered.length === 0 && (
            <li className="px-3 py-2 text-gray-400 text-xs">אין תוצאות</li>
          )}
          {filtered.map((n) => {
            const depth = depthMap.get(n.id) ?? 0;
            const isSelected = n.id === value;
            return (
              <li
                key={n.id}
                onMouseDown={() => handleSelect(n.id)}
                className={`cursor-pointer px-3 py-1.5 flex items-center gap-1 hover:bg-indigo-50 dark:hover:bg-indigo-900/40 ${isSelected ? "bg-indigo-100 dark:bg-indigo-900 font-medium" : ""}`}
                style={{ paddingRight: `${0.75 + depth * 1.25}rem` }}
              >
                {depth > 0 && <span className="text-gray-300 dark:text-gray-600 text-xs select-none">{"└"}</span>}
                <span className="truncate">{n.name}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [nodeId, setNodeId] = useState<string>("");

  useEffect(() => {
    void fetchFullTree().then((ns) => {
      const ordered = treeOrder(ns);
      setNodes(ordered);
      if (!nodeId) {
        const root = ordered.find((n) => n.level === "corps") ?? ordered[0];
        setNodeId(root?.id ?? "");
      }
    });
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  const depthMap = useMemo(() => buildDepthMap(nodes), [nodes]);

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <NodeSearchDropdown
          nodes={nodes}
          depthMap={depthMap}
          value={nodeId}
          onChange={setNodeId}
        />
        {nodeId ? <UnitCalendar nodeId={nodeId} /> : <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>}
      </section>
    </Layout>
  );
}

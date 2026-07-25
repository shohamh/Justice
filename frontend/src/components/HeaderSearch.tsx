import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import Fuse from "fuse.js";
import { useAuth } from "../auth/AuthContext";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { search, type SearchResponseDTO } from "../api/search";
import {
  getPageEntries,
  getQuickActionEntries,
  getHelpTopicEntries,
  getTabEntries,
  type PageEntry,
  type QuickActionEntry,
  type HelpTopicEntry,
  type TabEntry,
} from "../searchRegistry";

type FlatResult =
  | { kind: "page"; key: string; entry: PageEntry }
  | { kind: "action"; key: string; entry: QuickActionEntry }
  | { kind: "help"; key: string; entry: HelpTopicEntry }
  | { kind: "tab"; key: string; entry: TabEntry }
  | { kind: "soldier"; key: string; entry: SearchResponseDTO["soldiers"][number] }
  | { kind: "duty"; key: string; entry: SearchResponseDTO["duties"][number] }
  | { kind: "unit"; key: string; entry: SearchResponseDTO["units"][number] };

export default function HeaderSearch({ openHelp }: { openHelp: (tab?: string) => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const settings = usePublicSettings();
  const gimelimEnabled = settings?.["gimalim.enabled"] !== false;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [backendResults, setBackendResults] = useState<SearchResponseDTO>({ soldiers: [], duties: [], units: [] });
  const [backendError, setBackendError] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestQueryRef = useRef<string>("");

  const accessiblePages = useMemo(() => getPageEntries().filter((e) => e.canAccess(user)), [user]);
  const accessibleActions = useMemo(() => getQuickActionEntries().filter((e) => e.canAccess(user)), [user]);
  const accessibleHelp = useMemo(
    () => getHelpTopicEntries(gimelimEnabled).filter((e) => e.canAccess(user)),
    [user, gimelimEnabled],
  );
  const accessibleTabs = useMemo(() => getTabEntries().filter((e) => e.canAccess(user)), [user]);

  const pageFuse = useMemo(() => new Fuse(accessiblePages, { keys: ["keywords"], threshold: 0.4 }), [accessiblePages]);
  const actionFuse = useMemo(() => new Fuse(accessibleActions, { keys: ["keywords"], threshold: 0.4 }), [accessibleActions]);
  const helpFuse = useMemo(() => new Fuse(accessibleHelp, { keys: ["keywords"], threshold: 0.4 }), [accessibleHelp]);
  const tabFuse = useMemo(() => new Fuse(accessibleTabs, { keys: ["keywords"], threshold: 0.4 }), [accessibleTabs]);

  const trimmed = query.trim();
  const pageResults = trimmed ? pageFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];
  const actionResults = trimmed ? actionFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];
  const helpResults = trimmed ? helpFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];
  const tabResults = trimmed ? tabFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!trimmed) {
      latestQueryRef.current = "";
      setBackendResults({ soldiers: [], duties: [], units: [] });
      setBackendError(false);
      return;
    }
    debounceRef.current = setTimeout(() => {
      latestQueryRef.current = trimmed;
      search(trimmed)
        .then((res) => {
          if (latestQueryRef.current !== trimmed) return;
          setBackendResults(res);
          setBackendError(false);
        })
        .catch(() => {
          if (latestQueryRef.current !== trimmed) return;
          setBackendResults({ soldiers: [], duties: [], units: [] });
          setBackendError(true);
        });
    }, 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trimmed]);

  const flatResults: FlatResult[] = [
    ...pageResults.map((entry) => ({ kind: "page" as const, key: `page-${entry.id}`, entry })),
    ...actionResults.map((entry) => ({ kind: "action" as const, key: `action-${entry.id}`, entry })),
    ...helpResults.map((entry) => ({ kind: "help" as const, key: `help-${entry.id}`, entry })),
    ...tabResults.map((entry) => ({ kind: "tab" as const, key: `tab-${entry.id}`, entry })),
    ...backendResults.soldiers.map((entry) => ({ kind: "soldier" as const, key: `soldier-${entry.id}`, entry })),
    ...backendResults.duties.map((entry) => ({ kind: "duty" as const, key: `duty-${entry.id}`, entry })),
    ...backendResults.units.map((entry) => ({ kind: "unit" as const, key: `unit-${entry.id}`, entry })),
  ];

  const hasAnyResults = flatResults.length > 0;

  function openPanel() {
    setOpen(true);
  }

  function closePanel() {
    setOpen(false);
    setQuery("");
    setSelectedIndex(-1);
  }

  function handleSelect(r: FlatResult) {
    switch (r.kind) {
      case "page":
      case "action":
        navigate(r.entry.path);
        break;
      case "help":
        openHelp(r.entry.id);
        break;
      case "tab":
        navigate(`${r.entry.path}?tab=${r.entry.tabParam}`);
        break;
      case "soldier":
        navigate("/team");
        break;
      case "duty":
      case "unit":
        navigate("/unit-calendar");
        break;
    }
    closePanel();
  }

  useEffect(() => {
    setSelectedIndex(-1);
  }, [trimmed]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.code === "KeyK") {
        e.preventDefault();
        openPanel();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  function labelFor(r: FlatResult): string {
    switch (r.kind) {
      case "page":
        return t(r.entry.labelKey);
      case "action":
        return t(r.entry.labelKey);
      case "help":
        return `${t("search.categories.help")} > ${t(r.entry.labelKey)}`;
      case "tab":
        return `${t(r.entry.pageLabelKey)} > ${t(r.entry.labelKey)}`;
      case "soldier":
        return r.entry.full_name;
      case "duty":
        return r.entry.duty_type_name;
      case "unit":
        return r.entry.name;
    }
  }

  function subtitleFor(r: FlatResult): string | null {
    switch (r.kind) {
      case "soldier":
        return r.entry.subtitle ?? null;
      case "duty":
        return `${r.entry.start_date} · ${r.entry.location_name}`;
      case "unit":
        return r.entry.level;
      default:
        return null;
    }
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      closePanel();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, flatResults.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const selected = flatResults[selectedIndex];
      if (selected) handleSelect(selected);
    }
  }

  const groups: { titleKey: string; icon: string; items: FlatResult[] }[] = [
    { titleKey: "search.categories.page", icon: "📄", items: flatResults.filter((r) => r.kind === "page") },
    { titleKey: "search.categories.action", icon: "⚡", items: flatResults.filter((r) => r.kind === "action") },
    { titleKey: "search.categories.help", icon: "❓", items: flatResults.filter((r) => r.kind === "help") },
    { titleKey: "search.categories.tab", icon: "📑", items: flatResults.filter((r) => r.kind === "tab") },
    { titleKey: "search.categories.soldier", icon: "👤", items: flatResults.filter((r) => r.kind === "soldier") },
    { titleKey: "search.categories.duty", icon: "📅", items: flatResults.filter((r) => r.kind === "duty") },
    { titleKey: "search.categories.unit", icon: "🏛️", items: flatResults.filter((r) => r.kind === "unit") },
  ];

  return (
    <>
      <button onClick={openPanel} aria-label={t("search.placeholder")} className="text-gray-500 hover:text-indigo-600">
        <Search size={22} />
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/30" onClick={closePanel}>
          <div
            className="bg-white dark:bg-gray-800 mx-auto mt-16 max-w-xl rounded-lg shadow-lg p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              role="combobox"
              aria-expanded={open}
              aria-label={t("search.placeholder")}
              placeholder={t("search.placeholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleInputKeyDown}
              className="w-full border rounded px-3 py-2 bg-transparent dark:text-gray-100"
            />
            {trimmed !== "" && (
              <div className="mt-2 max-h-96 overflow-y-auto">
                {backendError && (
                  <div className="text-sm text-red-500 px-1 py-1">{t("search.error")}</div>
                )}
                {groups.map(
                  (g) =>
                    g.items.length > 0 && (
                      <div key={g.titleKey}>
                        <div className="text-xs text-gray-400 px-1">{g.icon} {t(g.titleKey)}</div>
                        {g.items.map((r) => {
                          const flatIndex = flatResults.indexOf(r);
                          return (
                            <div
                              key={r.key}
                              role="option"
                              aria-selected={flatIndex === selectedIndex}
                              onClick={() => handleSelect(r)}
                              className={`px-2 py-1 ${flatIndex === selectedIndex ? "bg-gray-100 dark:bg-gray-700" : ""}`}
                            >
                              {labelFor(r)}
                              {subtitleFor(r) && (
                                <div className="text-xs text-gray-400">{subtitleFor(r)}</div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ),
                )}
                {!hasAnyResults && !backendError && (
                  <div className="text-sm text-gray-500 px-1">{t("search.no_results")}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

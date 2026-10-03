import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { assignDmScope, removeDmScope } from "../api/dmScope";
import { useAuth } from "../auth/AuthContext";
import { getTransparencyAuthorizationScope } from "../api/auth";
import {
  isStaleSoldierRosterCursorError,
  listSoldierRosterPage,
  SoldierRosterItemDTO,
} from "../api/soldiers";
import { useModalBackClose } from "../hooks/useModalBackClose";
import { translateApiError } from "../utils/translateApiError";
import MessageDialog from "./MessageDialog";

interface Props {
  node: NodeDTO;
  onClose: () => void;
  onChanged: () => void;
}

const ROSTER_PAGE_SIZE = 10;
const MAX_AUTOMATIC_ROSTER_PAGES = 5;

interface CandidateSearchPage {
  authorizationIdentity: string;
  search: string;
  exclusionKey: string;
  items: SoldierRosterItemDTO[];
  nextCursor: string | null;
  hasMore: boolean;
}

interface CandidateWindow {
  items: SoldierRosterItemDTO[];
  nextCursor: string | null;
  hasMore: boolean;
  restartedFromFirstPage: boolean;
}

async function fetchCandidateWindow(
  search: string,
  startCursor: string | undefined,
  excludedIds: ReadonlySet<string>,
  signal: AbortSignal,
): Promise<CandidateWindow> {
  const readBatch = async (initialCursor: string | undefined) => {
    let cursor = initialCursor;
    let nextCursor: string | null = null;
    let hasMore = false;
    const items: SoldierRosterItemDTO[] = [];

    for (let pageIndex = 0; pageIndex < MAX_AUTOMATIC_ROSTER_PAGES; pageIndex += 1) {
      if (signal.aborted) return { items, nextCursor, hasMore };

      const page = await listSoldierRosterPage({
        ...(cursor ? { cursor } : {}),
        search,
        sort: "full_name",
        descending: false,
        page_size: ROSTER_PAGE_SIZE,
        active_only: false,
        signal,
      });
      items.push(...page.items.filter((soldier) => !excludedIds.has(soldier.id)));
      nextCursor = page.next_cursor;
      hasMore = page.has_more;

      if (items.length >= ROSTER_PAGE_SIZE || !hasMore || !nextCursor) {
        return { items, nextCursor, hasMore };
      }
      cursor = nextCursor;
    }

    return { items, nextCursor, hasMore };
  };

  try {
    return {
      ...(await readBatch(startCursor)),
      restartedFromFirstPage: false,
    };
  } catch (error) {
    if (signal.aborted || !isStaleSoldierRosterCursorError(error)) throw error;
    return {
      ...(await readBatch(undefined)),
      restartedFromFirstPage: true,
    };
  }
}

export default function AssignDutyManagersDialog({ node, onClose, onChanged }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const { user, authScopeReady } = useAuth();
  const [inputText, setInputText] = useState("");
  const [open, setOpen] = useState(false);
  const [candidatePage, setCandidatePage] = useState<CandidateSearchPage | null>(
    null,
  );
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [continueSearchKey, setContinueSearchKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rosterRequestGeneration = useRef(0);
  const continuationRequest = useRef<{
    key: string;
    controller: AbortController;
  } | null>(null);

  const rosterAuthorizationIdentity = authScopeReady
    ? getTransparencyAuthorizationScope(user)
    : null;
  const normalizedSearch = inputText.trim();
  const assignedIds = new Set(node.duty_managers.map((dm) => dm.soldier_id));
  const exclusionIds = [...assignedIds].sort();
  const exclusionKey = JSON.stringify(exclusionIds);
  const currentQueryKey = rosterAuthorizationIdentity
    ? JSON.stringify([
        rosterAuthorizationIdentity,
        normalizedSearch,
        exclusionKey,
      ])
    : null;
  const visibleCandidatePage =
    open &&
    rosterAuthorizationIdentity &&
    candidatePage?.authorizationIdentity === rosterAuthorizationIdentity &&
    candidatePage.search === normalizedSearch &&
    candidatePage.exclusionKey === exclusionKey
      ? candidatePage
      : null;
  const visibleCandidates =
    visibleCandidatePage?.items.filter((soldier) => !assignedIds.has(soldier.id)) ??
    [];

  useEffect(() => {
    const authorizationIdentity = rosterAuthorizationIdentity;
    const search = normalizedSearch;
    const excludedIdSet = new Set<string>(
      JSON.parse(exclusionKey) as string[],
    );
    const queryKey = currentQueryKey;
    const generation = ++rosterRequestGeneration.current;
    const controller = new AbortController();
    continuationRequest.current?.controller.abort();
    continuationRequest.current = null;
    setCandidatePage(null);
    setLoadingKey(null);
    setContinueSearchKey(null);

    if (!open || !authorizationIdentity || !queryKey) {
      return () => {
        controller.abort();
        if (rosterRequestGeneration.current === generation) {
          rosterRequestGeneration.current += 1;
        }
      };
    }

    const timeout = window.setTimeout(() => {
      setLoadingKey(queryKey);
      void fetchCandidateWindow(search, undefined, excludedIdSet, controller.signal)
        .then((windowedPage) => {
          if (
            controller.signal.aborted ||
            rosterRequestGeneration.current !== generation
          ) {
            return;
          }

          setCandidatePage({
            authorizationIdentity,
            search,
            exclusionKey,
            items: windowedPage.items,
            nextCursor: windowedPage.nextCursor,
            hasMore: windowedPage.hasMore,
          });
          setContinueSearchKey(
            windowedPage.items.length < ROSTER_PAGE_SIZE && windowedPage.hasMore
              ? queryKey
              : null,
          );
        })
        .catch(() => undefined)
        .finally(() => {
          if (rosterRequestGeneration.current === generation) {
            setLoadingKey((current) => (current === queryKey ? null : current));
          }
        });
    }, 200);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
      continuationRequest.current?.controller.abort();
      continuationRequest.current = null;
      if (rosterRequestGeneration.current === generation) {
        rosterRequestGeneration.current += 1;
      }
    };
  }, [
    currentQueryKey,
    exclusionKey,
    normalizedSearch,
    open,
    rosterAuthorizationIdentity,
  ]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function loadMoreCandidates() {
    const page = visibleCandidatePage;
    const queryKey = currentQueryKey;
    if (
      !page ||
      !page.hasMore ||
      !page.nextCursor ||
      !queryKey ||
      loadingKey === queryKey ||
      continuationRequest.current?.key === queryKey
    ) {
      return;
    }

    const generation = rosterRequestGeneration.current;
    const cursor = page.nextCursor;
    const excludedIdSet = new Set<string>(
      JSON.parse(exclusionKey) as string[],
    );
    const controller = new AbortController();
    continuationRequest.current?.controller.abort();
    continuationRequest.current = { key: queryKey, controller };
    setLoadingKey(queryKey);
    setContinueSearchKey(null);

    try {
      const windowedPage = await fetchCandidateWindow(
        page.search,
        cursor,
        excludedIdSet,
        controller.signal,
      );

      if (
        controller.signal.aborted ||
        rosterRequestGeneration.current !== generation ||
        continuationRequest.current?.key !== queryKey ||
        continuationRequest.current?.controller !== controller
      ) {
        return;
      }

      setCandidatePage((current) => {
        if (
          rosterRequestGeneration.current !== generation ||
          controller.signal.aborted ||
          continuationRequest.current?.key !== queryKey ||
          continuationRequest.current?.controller !== controller ||
          !current ||
          current.authorizationIdentity !== page.authorizationIdentity ||
          current.search !== page.search ||
          current.exclusionKey !== page.exclusionKey ||
          current.nextCursor !== cursor
        ) {
          return current;
        }

        const items = windowedPage.restartedFromFirstPage
          ? windowedPage.items
          : [
              ...current.items,
              ...windowedPage.items.filter(
                (soldier) =>
                  !current.items.some((item) => item.id === soldier.id),
              ),
            ];
        return {
          ...current,
          items,
          nextCursor: windowedPage.nextCursor,
          hasMore: windowedPage.hasMore,
        };
      });
      if (
        windowedPage.items.length < ROSTER_PAGE_SIZE &&
        windowedPage.hasMore
      ) {
        setContinueSearchKey(queryKey);
      }
    } catch {
      // Keep current candidates visible; a later scroll or continuation action retries.
      setContinueSearchKey(queryKey);
    } finally {
      if (continuationRequest.current?.controller === controller) {
        continuationRequest.current = null;
        setLoadingKey((current) => (current === queryKey ? null : current));
      }
    }
  }

  async function handleAdd(
    s: SoldierRosterItemDTO,
    selectionAuthorizationIdentity: string,
  ) {
    if (
      !authScopeReady ||
      !rosterAuthorizationIdentity ||
      selectionAuthorizationIdentity !== rosterAuthorizationIdentity ||
      assignedIds.has(s.id)
    ) {
      return;
    }
    setInputText("");
    setOpen(false);
    try {
      await assignDmScope(s.id, node.id);
      onChanged();
    } catch (err: unknown) {
      setMessage(translateApiError(err, t, "שגיאה בהוספת אחראי תורנויות ליחידה"));
    }
  }

  async function handleRemove(scopeId: string) {
    try {
      await removeDmScope(scopeId);
      onChanged();
    } catch (err: unknown) {
      setMessage(translateApiError(err, t, "שגיאה בהסרת אחראי התורנויות מהיחידה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96"
        onClick={(e) => e.stopPropagation()}
        data-testid="assign-duty-managers-dialog"
      >
        <h3 className="font-semibold mb-4 dark:text-gray-100">
          {t("team.assign_duty_managers")}: {node.name}
        </h3>

        {node.duty_managers.length === 0 ? (
          <p className="text-sm text-gray-500 mb-3">{t("team.no_duty_managers")}</p>
        ) : (
          <ul className="space-y-1 mb-3" data-testid="duty-managers-list">
            {node.duty_managers.map((dm) => (
              <li
                key={dm.scope_id}
                className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1"
              >
                <span>{dm.name}</span>
                <button
                  type="button"
                  className="text-red-500 hover:text-red-700 text-xs"
                  onClick={() => void handleRemove(dm.scope_id)}
                  data-testid={`remove-dm-${dm.scope_id}`}
                >
                  {t("notifications.remove")}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div ref={containerRef} className="relative">
          <input
            className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={inputText}
            onChange={(e) => { setInputText(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            placeholder={t("team.search_soldier_placeholder")}
            data-testid="duty-manager-search"
            autoComplete="off"
          />
          {open && visibleCandidatePage && visibleCandidates.length > 0 && (
            <ul
              className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto"
              onScroll={(event) => {
                const element = event.currentTarget;
                if (element.scrollHeight - element.scrollTop - element.clientHeight <= 48) {
                  void loadMoreCandidates();
                }
              }}
            >
              {visibleCandidates.map((s) => (
                <li
                  key={s.id}
                  className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    void handleAdd(s, visibleCandidatePage.authorizationIdentity);
                  }}
                  data-testid={`duty-manager-option-${s.id}`}
                >
                  {s.full_name}{" "}
                  <span className="text-gray-400 text-xs">({s.personal_number})</span>
                </li>
              ))}
              {currentQueryKey && loadingKey === currentQueryKey && (
                <li className="px-3 py-2 text-center text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
                  {t("team.roster_loading_more", "Loading more soldiers...")}
                </li>
              )}
              {visibleCandidatePage.hasMore &&
                continueSearchKey === currentQueryKey &&
                loadingKey !== currentQueryKey && (
                  <li className="p-1">
                    <button
                      type="button"
                      className="w-full rounded border px-2 py-1 text-xs dark:border-gray-600 dark:text-gray-100"
                      onClick={() => void loadMoreCandidates()}
                    >
                      {t("team.roster_load_more", "Load more")}
                    </button>
                  </li>
                )}
            </ul>
          )}
          {open &&
            currentQueryKey &&
            loadingKey === currentQueryKey &&
            visibleCandidates.length === 0 && (
              <p className="absolute z-10 mt-1 w-full rounded bg-white p-2 text-center text-xs text-gray-500 shadow dark:bg-gray-700 dark:text-gray-400" role="status" aria-live="polite">
                {t("team.roster_loading_more", "Loading more soldiers...")}
              </p>
            )}
          {open &&
            visibleCandidates.length === 0 &&
            visibleCandidatePage?.hasMore &&
            continueSearchKey === currentQueryKey &&
            loadingKey !== currentQueryKey && (
              <button
                type="button"
                className="absolute z-10 mt-1 w-full rounded border bg-white px-3 py-2 text-sm shadow dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                onClick={() => void loadMoreCandidates()}
              >
                {t("team.roster_load_more", "Load more")}
              </button>
            )}
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            type="button"
            className="border rounded px-3 py-1 dark:text-gray-100 dark:border-gray-600"
            onClick={onClose}
            data-testid="duty-managers-done"
          >
            {t("app.close")}
          </button>
        </div>
      </div>
      <MessageDialog open={message !== null} title={t("common.error", "שגיאה")} message={message ?? ""} onClose={() => setMessage(null)} />
    </div>
  );
}

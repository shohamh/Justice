import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import ExplanationModal from "../components/ExplanationModal";
import { Assignment, cancelAssignment, listAssignments, setOverride } from "../api/assignments";
import { createAdjustment } from "../api/scoreAdjustments";
import { getTransparencyAuthorizationScope } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import {
  isStaleSoldierRosterCursorError,
  listSoldierRosterPage,
  SoldierRosterItemDTO,
} from "../api/soldiers";
import { getDraftsPreview, resetDrafts, resetPublished } from "../api/algorithm";
import { lastDutyDay } from "../utils/formatDate";
import ConfirmDialog from "../components/ConfirmDialog";
import InputDialog from "../components/InputDialog";
import Tooltip from "../components/Tooltip";
import { translateApiError } from "../utils/translateApiError";

const DUTY_ROSTER_PAGE_SIZE = 10;
const DUTY_PICKER_ROW_HEIGHT = 40;
const DUTY_PICKER_VIEWPORT_HEIGHT = 192;
const DUTY_PICKER_OVERSCAN = 3;

interface DutyRosterPageState {
  authorizationIdentity: string;
  search: string;
  items: SoldierRosterItemDTO[];
  nextCursor: string | null;
  hasMore: boolean;
}

interface DutyRosterPageResult {
  page: Awaited<ReturnType<typeof listSoldierRosterPage>>;
  restartedFromFirstPage: boolean;
}

async function requestDutyRosterPage(
  search: string,
  cursor: string | undefined,
  signal: AbortSignal,
): Promise<DutyRosterPageResult> {
  const request = {
    ...(cursor ? { cursor } : {}),
    search,
    sort: "full_name" as const,
    descending: false,
    page_size: DUTY_ROSTER_PAGE_SIZE,
    active_only: false,
    signal,
  };

  try {
    return {
      page: await listSoldierRosterPage(request),
      restartedFromFirstPage: false,
    };
  } catch (error) {
    if (signal.aborted || !isStaleSoldierRosterCursorError(error) || !cursor) {
      throw error;
    }

    return {
      page: await listSoldierRosterPage({
        search,
        sort: "full_name",
        descending: false,
        page_size: DUTY_ROSTER_PAGE_SIZE,
        active_only: false,
        signal,
      }),
      restartedFromFirstPage: true,
    };
  }
}

function DutyManagementSoldierPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation();
  const { user, authScopeReady } = useAuth();
  const authorizationIdentity = authScopeReady
    ? getTransparencyAuthorizationScope(user)
    : null;
  const [inputText, setInputText] = useState("");
  const [inputShowsSelection, setInputShowsSelection] = useState(true);
  const [searchText, setSearchText] = useState("");
  const [open, setOpen] = useState(false);
  const [rosterPage, setRosterPage] = useState<DutyRosterPageState | null>(null);
  const [selectedOption, setSelectedOption] = useState<{
    id: string;
    name: string;
    authorizationIdentity: string;
  } | null>(null);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [continueKey, setContinueKey] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const requestGeneration = useRef(0);
  const continuationRequest = useRef<{
    key: string;
    cursor: string;
    controller: AbortController;
  } | null>(null);
  const rosterNamesById = useRef<{
    queryKey: string;
    names: Map<string, string>;
  } | null>(null);
  const listboxRef = useRef<HTMLUListElement | null>(null);
  const keyboardScrollTop = useRef<number | null>(null);
  const [listScrollTop, setListScrollTop] = useState(0);
  const listboxId = useId();
  const normalizedSearch = searchText.trim();
  const queryKey = authorizationIdentity
    ? JSON.stringify([authorizationIdentity, normalizedSearch])
    : null;
  const matchingRosterPage =
    authorizationIdentity &&
    rosterPage?.authorizationIdentity === authorizationIdentity &&
    rosterPage.search === normalizedSearch
      ? rosterPage
      : null;
  const visibleRosterPage = open ? matchingRosterPage : null;
  const visibleItems = visibleRosterPage?.items ?? [];
  const cachedRosterNames = rosterNamesById.current;
  const selectedPageName =
    authorizationIdentity &&
    value &&
    cachedRosterNames?.queryKey === queryKey
      ? cachedRosterNames.names.get(value)
      : undefined;
  const currentSelection =
    authorizationIdentity &&
    selectedOption?.id === value &&
    selectedOption.authorizationIdentity === authorizationIdentity
      ? selectedOption
      : authorizationIdentity && value && selectedPageName
        ? {
            id: value,
            name: selectedPageName,
            authorizationIdentity,
          }
        : null;
  const displayedSelectionName = currentSelection?.name ?? "";

  useEffect(() => {
    const identity = authorizationIdentity;
    const search = normalizedSearch;
    const key = queryKey;
    const generation = ++requestGeneration.current;
    const controller = new AbortController();
    setHighlightedIndex(-1);
    setListScrollTop(0);
    keyboardScrollTop.current = null;
    if (listboxRef.current) listboxRef.current.scrollTop = 0;
    rosterNamesById.current = null;
    continuationRequest.current?.controller.abort();
    continuationRequest.current = null;
    setRosterPage(null);
    setLoadingKey(null);
    setContinueKey(null);
    setErrorKey(null);

    if (!identity || !key) {
      return () => {
        controller.abort();
        if (requestGeneration.current === generation) {
          requestGeneration.current += 1;
        }
      };
    }

    const timeout = window.setTimeout(() => {
      setLoadingKey(key);
      void listSoldierRosterPage({
        search,
        sort: "full_name",
        descending: false,
        page_size: DUTY_ROSTER_PAGE_SIZE,
        active_only: false,
        signal: controller.signal,
      })
        .then((page) => {
          if (
            controller.signal.aborted ||
            requestGeneration.current !== generation
          ) {
            return;
          }

          const names = new Map<string, string>();
          page.items.forEach((item) => names.set(item.id, item.full_name));
          rosterNamesById.current = { queryKey: key, names };
          setRosterPage({
            authorizationIdentity: identity,
            search,
            items: page.items,
            nextCursor: page.next_cursor,
            hasMore: page.has_more,
          });
          setContinueKey(
            page.items.length < DUTY_ROSTER_PAGE_SIZE && page.has_more
              ? key
              : null,
          );
        })
        .catch(() => {
          if (!controller.signal.aborted) setErrorKey(key);
        })
        .finally(() => {
          if (requestGeneration.current === generation) {
            setLoadingKey((current) => (current === key ? null : current));
          }
        });
    }, normalizedSearch ? 200 : 0);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
      continuationRequest.current?.controller.abort();
      continuationRequest.current = null;
      if (requestGeneration.current === generation) {
        requestGeneration.current += 1;
      }
    };
  }, [authorizationIdentity, normalizedSearch, queryKey, retryCount]);

  useEffect(() => {
    if (
      !authorizationIdentity ||
      rosterPage?.authorizationIdentity !== authorizationIdentity ||
      rosterPage.search !== "" ||
      rosterPage.items.length === 0
    ) {
      return;
    }

    const defaultItem = rosterPage.items[0];
    const cachedNames = rosterNamesById.current;
    const selectedName = value
      ? cachedNames?.queryKey === queryKey
        ? cachedNames.names.get(value)
        : undefined
      : defaultItem?.full_name;
    const selectedId = value || defaultItem?.id;
    if (selectedName && selectedId) {
      setSelectedOption((current) =>
        current?.id === selectedId &&
        current.name === selectedName &&
        current.authorizationIdentity === authorizationIdentity
          ? current
          : {
              id: selectedId,
              name: selectedName,
              authorizationIdentity,
            },
      );
    }
    if (!value) {
      const first = defaultItem;
      if (!first) return;
      setInputShowsSelection(true);
      onChange(first.id);
    }
  }, [authorizationIdentity, onChange, queryKey, rosterPage, value]);

  async function loadMore() {
    const page = visibleRosterPage;
    const key = queryKey;
    if (
      !page ||
      !page.hasMore ||
      !page.nextCursor ||
      !key ||
      loadingKey === key ||
      continuationRequest.current?.key === key
    ) {
      return;
    }

    const generation = requestGeneration.current;
    const cursor = page.nextCursor;
    const controller = new AbortController();
    continuationRequest.current?.controller.abort();
    continuationRequest.current = { key, cursor, controller };
    setLoadingKey(key);
    setContinueKey(null);
    setErrorKey(null);

    try {
      const result = await requestDutyRosterPage(
        page.search,
        cursor,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestGeneration.current !== generation ||
        continuationRequest.current?.key !== key ||
        continuationRequest.current.controller !== controller
      ) {
        return;
      }

      const cachedNames = rosterNamesById.current;
      const names =
        result.restartedFromFirstPage ||
        cachedNames?.queryKey !== key
          ? new Map<string, string>()
          : cachedNames.names;
      result.page.items.forEach((item) => names.set(item.id, item.full_name));
      rosterNamesById.current = { queryKey: key, names };

      setRosterPage((current) => {
        if (
          requestGeneration.current !== generation ||
          controller.signal.aborted ||
          continuationRequest.current?.key !== key ||
          continuationRequest.current.controller !== controller ||
          !current ||
          current.authorizationIdentity !== page.authorizationIdentity ||
          current.search !== page.search ||
          current.nextCursor !== cursor
        ) {
          return current;
        }

        // The roster cursor is keyset-bound to the sort key and soldier ID,
        // and a roster revision change restarts at page one above.
        const items = result.restartedFromFirstPage
          ? result.page.items
          : [...current.items, ...result.page.items];
        return {
          ...current,
          items,
          nextCursor: result.page.next_cursor,
          hasMore: result.page.has_more,
        };
      });
      setContinueKey(
        result.page.items.length < DUTY_ROSTER_PAGE_SIZE && result.page.has_more
          ? key
          : null,
      );
    } catch {
      if (!controller.signal.aborted) {
        setErrorKey(key);
        setContinueKey(key);
      }
    } finally {
      if (continuationRequest.current?.controller === controller) {
        continuationRequest.current = null;
        setLoadingKey((current) => (current === key ? null : current));
      }
    }
  }

  function chooseSoldier(item: SoldierRosterItemDTO) {
    if (!authorizationIdentity || !authScopeReady) return;
    onChange(item.id);
    setSelectedOption({
      id: item.id,
      name: item.full_name,
      authorizationIdentity,
    });
    setInputText("");
    setInputShowsSelection(true);
    setSearchText("");
    setOpen(false);
    setHighlightedIndex(-1);
  }

  function highlightOption(index: number) {
    setHighlightedIndex(index);
    const listbox = listboxRef.current;
    if (!listbox || index < 0) return;

    const itemTop = index * DUTY_PICKER_ROW_HEIGHT;
    const itemBottom = itemTop + DUTY_PICKER_ROW_HEIGHT;
    let nextScrollTop = listbox.scrollTop;
    if (itemTop < nextScrollTop) {
      nextScrollTop = itemTop;
    } else if (itemBottom > nextScrollTop + listbox.clientHeight) {
      nextScrollTop = itemBottom - listbox.clientHeight;
    }
    if (nextScrollTop !== listbox.scrollTop) {
      keyboardScrollTop.current = nextScrollTop;
      listbox.scrollTop = nextScrollTop;
      setListScrollTop(nextScrollTop);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setListScrollTop(0);
        keyboardScrollTop.current = null;
        if (listboxRef.current) listboxRef.current.scrollTop = 0;
        setHighlightedIndex(matchingRosterPage?.items.length ? 0 : -1);
      } else {
        highlightOption(
          Math.min(highlightedIndex + 1, visibleItems.length - 1),
        );
      }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlightOption(
        Math.min(Math.max(highlightedIndex - 1, 0), visibleItems.length - 1),
      );
    } else if (event.key === "Enter" && open) {
      if (highlightedIndex >= 0 && highlightedIndex < visibleItems.length) {
        event.preventDefault();
        chooseSoldier(visibleItems[highlightedIndex]);
      } else {
        const exact = visibleItems.find(
          (item) => item.full_name === inputText.trim(),
        );
        if (exact) {
          event.preventDefault();
          chooseSoldier(exact);
        }
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  }

  const activeOptionId =
    highlightedIndex >= 0 && highlightedIndex < visibleItems.length
      ? `${listboxId}-option-${visibleItems[highlightedIndex].id}`
      : undefined;
  const virtualStartIndex = Math.max(
    0,
    Math.floor(listScrollTop / DUTY_PICKER_ROW_HEIGHT) - DUTY_PICKER_OVERSCAN,
  );
  const virtualEndIndex = Math.min(
    visibleItems.length,
    Math.ceil(
      (listScrollTop + DUTY_PICKER_VIEWPORT_HEIGHT) / DUTY_PICKER_ROW_HEIGHT,
    ) +
      DUTY_PICKER_OVERSCAN,
  );
  const virtualItems = visibleItems.slice(virtualStartIndex, virtualEndIndex);

  return (
    <div className="relative" data-testid="dm-soldier-picker">
      <input
        type="text"
        value={inputShowsSelection ? displayedSelectionName : inputText}
        autoComplete="off"
        data-testid="dm-soldier"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-activedescendant={activeOptionId}
        onChange={(event) => {
          setInputText(event.target.value);
          setInputShowsSelection(false);
          setSearchText(event.target.value);
          setOpen(true);
          setHighlightedIndex(-1);
          setListScrollTop(0);
          keyboardScrollTop.current = null;
          if (listboxRef.current) listboxRef.current.scrollTop = 0;
        }}
        onFocus={() => {
          setSearchText("");
          setOpen(true);
          setHighlightedIndex(-1);
          setListScrollTop(0);
          keyboardScrollTop.current = null;
          if (listboxRef.current) listboxRef.current.scrollTop = 0;
        }}
        onBlur={() => {
          window.setTimeout(() => {
            const exact = visibleItems.find(
              (item) => item.full_name === inputText.trim(),
            );
            if (exact) {
              chooseSoldier(exact);
            } else {
              setOpen(false);
            }
          }, 150);
        }}
        onKeyDown={handleKeyDown}
        className="block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      />
      {open && queryKey && (visibleRosterPage || loadingKey === queryKey || errorKey === queryKey) && (
        <ul
          ref={listboxRef}
          id={listboxId}
          role="listbox"
          className="absolute z-20 mt-1 w-full max-h-48 overflow-y-auto rounded border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-800"
          onScroll={(event) => {
            const element = event.currentTarget;
            const nextScrollTop = element.scrollTop;
            setListScrollTop(nextScrollTop);
            const windowStart = Math.max(
              0,
              Math.floor(nextScrollTop / DUTY_PICKER_ROW_HEIGHT) -
                DUTY_PICKER_OVERSCAN,
            );
            const windowEnd = Math.min(
              visibleItems.length,
              Math.ceil((nextScrollTop + element.clientHeight) / DUTY_PICKER_ROW_HEIGHT) +
                DUTY_PICKER_OVERSCAN,
            );
            const fromKeyboard =
              keyboardScrollTop.current !== null &&
              Math.abs(nextScrollTop - keyboardScrollTop.current) < 1;
            keyboardScrollTop.current = null;
            if (
              !fromKeyboard &&
              highlightedIndex >= 0 &&
              (highlightedIndex < windowStart || highlightedIndex >= windowEnd)
            ) {
              setHighlightedIndex(-1);
            }
            if (element.scrollHeight - element.scrollTop - element.clientHeight <= 48) {
              void loadMore();
            }
          }}
        >
          <li
            role="presentation"
            aria-hidden="true"
            className="pointer-events-none"
            style={{ height: visibleItems.length * DUTY_PICKER_ROW_HEIGHT }}
          />
          {virtualItems.map((item, offset) => {
            const index = virtualStartIndex + offset;
            return (
              <li
                key={item.id}
                id={`${listboxId}-option-${item.id}`}
                role="option"
                aria-selected={value === item.id}
                aria-posinset={index + 1}
                aria-setsize={visibleRosterPage?.hasMore ? -1 : visibleItems.length}
                onPointerDown={(event) => event.preventDefault()}
                onClick={() => chooseSoldier(item)}
                className={`flex h-full w-full cursor-pointer items-center px-3 text-right text-sm dark:text-gray-100 ${
                  index === highlightedIndex
                    ? "bg-gray-100 dark:bg-gray-700"
                    : "hover:bg-gray-50 dark:hover:bg-gray-700"
                } ${value === item.id ? "font-semibold text-indigo-600 dark:text-indigo-300" : ""}`}
                style={{
                  position: "absolute",
                  top: index * DUTY_PICKER_ROW_HEIGHT,
                  left: 0,
                  right: 0,
                  height: DUTY_PICKER_ROW_HEIGHT,
                }}
              >
                {item.full_name}
              </li>
            );
          })}
          {loadingKey === queryKey && (
            <li role="status" aria-live="polite" className="px-3 py-2 text-center text-xs text-gray-500 dark:text-gray-400">
              {t("team.roster_loading_more", "Loading more soldiers...")}
            </li>
          )}
          {visibleRosterPage?.hasMore &&
            continueKey === queryKey &&
            loadingKey !== queryKey && (
              <li className="p-1">
                <button
                  type="button"
                  onPointerDown={(event) => event.preventDefault()}
                  onClick={() => void loadMore()}
                  className="w-full rounded border px-2 py-1 text-xs dark:border-gray-600 dark:text-gray-100"
                >
                  {t("team.roster_load_more", "Load more")}
                </button>
              </li>
            )}
          {errorKey === queryKey && (
            <li role="alert" className="px-3 py-2 text-center text-xs text-red-600 dark:text-red-400">
              {t("common.error", "Unable to load soldiers")}
            </li>
          )}
        </ul>
      )}
      {open &&
        queryKey &&
        errorKey === queryKey &&
        !visibleRosterPage && (
          <button
            type="button"
            onPointerDown={(event) => event.preventDefault()}
            onClick={() => setRetryCount((current) => current + 1)}
            className="absolute z-20 mt-1 w-full rounded border bg-white px-3 py-2 text-sm shadow dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          >
            {t("common.retry", "Retry")}
          </button>
        )}
    </div>
  );
}

export function DutyManagementContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [soldierId, setSoldierId] = useState("");
  const [adjDelta, setAdjDelta] = useState("");
  const [adjReason, setAdjReason] = useState("");

  const [explanationId, setExplanationId] = useState<string | null>(null);
  const [cancelAssignmentId, setCancelAssignmentId] = useState<string | null>(null);
  const [overrideAssignmentId, setOverrideAssignmentId] = useState<string | null>(null);
  const [overrideDay, setOverrideDay] = useState<{ id: string; day: string } | null>(null);
  const [confirmCancelDrafts, setConfirmCancelDrafts] = useState(false);
  const [confirmCancelPublished, setConfirmCancelPublished] = useState(false);

  // Bulk cancel state
  const [draftsExpanded, setDraftsExpanded] = useState(false);
  const [cancelDraftsLoading, setCancelDraftsLoading] = useState(false);
  const [cancelDraftsMsg, setCancelDraftsMsg] = useState<string | null>(null);
  const [cancelPublishedLoading, setCancelPublishedLoading] = useState(false);
  const [cancelPublishedMsg, setCancelPublishedMsg] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const draftsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const publishedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const assignmentsQuery = useQuery({
    queryKey: queryKeys.assignments(soldierId),
    queryFn: () => listAssignments(soldierId),
    enabled: !!soldierId,
  });
  const rows: Assignment[] = assignmentsQuery.data ?? [];

  // DM-only endpoint — non-managers get a 403; treat that the same as "no drafts" without surfacing an error.
  const draftsQuery = useQuery({
    queryKey: queryKeys.draftsPreview(),
    queryFn: getDraftsPreview,
    retry: false,
  });
  const draftCount = draftsQuery.data?.count ?? 0;
  const draftItems = draftsQuery.data?.items ?? [];

  useEffect(() => {
    return () => {
      if (draftsTimerRef.current) clearTimeout(draftsTimerRef.current);
      if (publishedTimerRef.current) clearTimeout(publishedTimerRef.current);
    };
  }, []);

  async function doCancel(id: string, reason: string) {
    try {
      await cancelAssignment(id, reason);
      await queryClient.invalidateQueries({ queryKey: queryKeys.assignments(soldierId) });
    } catch (err) {
      setActionError(translateApiError(err, t, "שגיאה בביטול התורנות"));
    }
  }

  async function doOverride(id: string, day: string, repl: string) {
    try {
      await setOverride(id, day, { effective_soldier_id: repl || null, reason: repl ? "replacement" : "cancelled" });
      await queryClient.invalidateQueries({ queryKey: queryKeys.assignments(soldierId) });
    } catch (err) {
      setActionError(translateApiError(err, t, "שגיאה בעדכון החרגת התורנות"));
    }
  }

  async function submitAdj(e: FormEvent) {
    e.preventDefault();
    try {
      await createAdjustment({ soldier_id: soldierId, delta: adjDelta, reason: adjReason });
      setAdjDelta(""); setAdjReason("");
    } catch (err) {
      setActionError(translateApiError(err, t, "שגיאה בשמירת התאמת הניקוד"));
    }
  }

  async function handleCancelDrafts() {
    setCancelDraftsLoading(true);
    setCancelDraftsMsg(null);
    if (draftsTimerRef.current) clearTimeout(draftsTimerRef.current);
    try {
      const result = await resetDrafts(0);
      const msg = result.rejected === 0
        ? t("duty_management.cancel_drafts_none")
        : t("duty_management.cancel_drafts_result", { count: result.rejected });
      setCancelDraftsMsg(msg);
      draftsTimerRef.current = setTimeout(() => setCancelDraftsMsg(null), 5000);
      await queryClient.invalidateQueries({ queryKey: queryKeys.draftsPreview() });
      setDraftsExpanded(false);
    } catch {
      setCancelDraftsMsg("שגיאה בביטול טיוטות התורנויות");
      draftsTimerRef.current = setTimeout(() => setCancelDraftsMsg(null), 5000);
    } finally {
      setCancelDraftsLoading(false);
    }
  }

  async function handleCancelPublished() {
    setCancelPublishedLoading(true);
    setCancelPublishedMsg(null);
    if (publishedTimerRef.current) clearTimeout(publishedTimerRef.current);
    try {
      const result = await resetPublished(0);
      const msg = result.cancelled === 0
        ? t("duty_management.cancel_published_none")
        : t("duty_management.cancel_published_result", { count: result.cancelled });
      setCancelPublishedMsg(msg);
      publishedTimerRef.current = setTimeout(() => setCancelPublishedMsg(null), 5000);
      await queryClient.invalidateQueries({ queryKey: queryKeys.draftsPreview() });
    } catch {
      setCancelPublishedMsg("שגיאה בביטול התורנויות שפורסמו");
      publishedTimerRef.current = setTimeout(() => setCancelPublishedMsg(null), 5000);
    } finally {
      setCancelPublishedLoading(false);
    }
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6" data-testid="duty-management-page">
      {actionError && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{actionError}</p>}
      <h2 className="text-xl font-semibold">{t("duty_management.title")}</h2>

      <div className="block text-sm">
        <span className="block mb-0.5">{t("duty_management.soldier")}</span>
        <DutyManagementSoldierPicker value={soldierId} onChange={setSoldierId} />
      </div>

      <ul className="text-sm space-y-1" data-testid="assignment-list">
        {rows.length === 0 && <li data-testid="dm-empty">{t("duty_management.none")}</li>}
        {rows.map((a) => (
          <li key={a.id} data-testid={`assignment-row-${a.id}`} className="flex items-center gap-2">
            <span dir="ltr">{a.start_date} → {lastDutyDay(a.end_date)}</span>
            {a.weapon_ineligible && (
              <Tooltip
                as="span"
                title={a.weapon_ineligible_reason ?? undefined}
                content={a.weapon_ineligible_reason ?? undefined}
                className="mr-1 text-red-500 dark:text-red-400"
              >
                ⚠️
              </Tooltip>
            )}
            <button className="text-xs text-indigo-600 dark:text-indigo-300" onClick={() => setOverrideAssignmentId(a.id)} data-testid={`override-${a.id}`}>{t("duty_management.override")}</button>
            <button className="text-xs text-red-600" onClick={() => setCancelAssignmentId(a.id)} data-testid={`cancel-${a.id}`}>{t("duty_management.cancel")}</button>
            <button
              className="text-gray-400 hover:text-indigo-600 text-xs font-bold border border-gray-300 dark:border-gray-600 rounded-full w-5 h-5 inline-flex items-center justify-center"
              onClick={() => setExplanationId(a.id)}
              title="למה קיבל חייל זה תורנות זו?"
            >
              ?
            </button>
          </li>
        ))}
      </ul>

      <form onSubmit={submitAdj} className="flex items-end gap-2 border-t dark:border-gray-600 pt-4" data-testid="adjustment-form">
        <h3 className="font-medium">{t("duty_management.score_adjustment")}</h3>
        <input className="border rounded p-1 w-24 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={adjDelta} onChange={(e) => setAdjDelta(e.target.value)} placeholder={t("duty_management.delta")} required data-testid="adj-delta" />
        <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={adjReason} onChange={(e) => setAdjReason(e.target.value)} placeholder={t("duty_management.reason")} required data-testid="adj-reason" />
        <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="adj-submit">{t("duty_management.apply")}</button>
      </form>

      <div className="border-t dark:border-gray-600 pt-4 space-y-4" dir="rtl">
        <h3 className="font-medium text-sm text-gray-700 dark:text-gray-300">
          {t("duty_management.bulk_cancel_section_title")}
        </h3>

        {/* Drafts row */}
        <div className="space-y-2">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="text-gray-700 dark:text-gray-300">
              {t("duty_management.drafts_from_today_label")}
            </span>
            <button
              type="button"
              onClick={() => setDraftsExpanded(v => !v)}
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                draftCount > 0
                  ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 hover:bg-amber-200 dark:hover:bg-amber-800"
                  : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
              }`}
            >
              {draftCount > 0
                ? t("duty_management.drafts_badge", { count: draftCount })
                : t("duty_management.drafts_badge_none")}
              {draftCount > 0 ? ` ${draftsExpanded ? t("duty_management.drafts_toggle_hide") : t("duty_management.drafts_toggle_show")}` : ""}
            </button>
            <button
              type="button"
              onClick={() => setConfirmCancelDrafts(true)}
              disabled={cancelDraftsLoading || draftCount === 0}
              className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700 disabled:opacity-40"
            >
              {t("duty_management.cancel_drafts_btn")}
            </button>
            {cancelDraftsMsg && (
              <span className="text-xs text-gray-600 dark:text-gray-400">{cancelDraftsMsg}</span>
            )}
          </div>
          {draftsExpanded && draftItems.length > 0 && (
            <ul className="text-xs space-y-0.5 pr-2 max-h-40 overflow-y-auto border rounded dark:border-gray-600 p-2">
              {draftItems.map(item => (
                <li key={item.assignment_id} className="text-gray-700 dark:text-gray-300">
                  {item.soldier_name} · {item.duty_type_name} · {item.start_date}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Published row */}
        <div className="flex items-center gap-3 flex-wrap text-sm">
          <span className="text-gray-700 dark:text-gray-300">
            {t("duty_management.published_from_today_label")}
          </span>
          <button
            type="button"
            onClick={() => setConfirmCancelPublished(true)}
            disabled={cancelPublishedLoading}
            className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-40"
          >
            {t("duty_management.cancel_published_btn")}
          </button>
          {cancelPublishedMsg && (
            <span className="text-xs text-gray-600 dark:text-gray-400">{cancelPublishedMsg}</span>
          )}
        </div>
      </div>
      {explanationId && (
        <ExplanationModal assignmentId={explanationId} onClose={() => setExplanationId(null)} />
      )}
      <InputDialog
        open={cancelAssignmentId !== null}
        title={t("duty_management.cancel_title", "ביטול תורנות")}
        label={t("duty_management.cancel_reason")}
        required
        onClose={() => setCancelAssignmentId(null)}
        onConfirm={reason => {
          const id = cancelAssignmentId;
          setCancelAssignmentId(null);
          if (id) return doCancel(id, reason);
        }}
      />
      <InputDialog
        open={overrideAssignmentId !== null}
        title={t("duty_management.override_title", "החלפת תורנות")}
        label={t("duty_management.override_day")}
        required
        onClose={() => setOverrideAssignmentId(null)}
        onConfirm={day => {
          const id = overrideAssignmentId;
          setOverrideAssignmentId(null);
          if (id) setOverrideDay({ id, day });
        }}
      />
      <InputDialog
        open={overrideDay !== null}
        title={t("duty_management.replacement_title", "מחליף לתורנות")}
        label={t("duty_management.replacement")}
        onClose={() => setOverrideDay(null)}
        onConfirm={replacement => {
          const target = overrideDay;
          setOverrideDay(null);
          if (target) return doOverride(target.id, target.day, replacement);
        }}
      />
      <ConfirmDialog
        open={confirmCancelDrafts}
        title={t("duty_management.cancel_drafts_title", "ביטול טיוטות")}
        message={t("duty_management.cancel_drafts_confirm", { count: draftCount })}
        danger
        confirmDisabled={cancelDraftsLoading}
        onClose={() => setConfirmCancelDrafts(false)}
        onConfirm={() => { setConfirmCancelDrafts(false); void handleCancelDrafts(); }}
      />
      <ConfirmDialog
        open={confirmCancelPublished}
        title={t("duty_management.cancel_published_title", "ביטול תורנויות")}
        message={t("duty_management.cancel_published_confirm")}
        danger
        confirmDisabled={cancelPublishedLoading}
        onClose={() => setConfirmCancelPublished(false)}
        onConfirm={() => { setConfirmCancelPublished(false); void handleCancelPublished(); }}
      />
    </section>
  );
}

export default function DutyManagementPage() {
  return <Layout><DutyManagementContent /></Layout>;
}

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DeputyDTO, createDeputy, listDeputies, revokeDeputy } from "../api/deputies";
import { useAuth } from "../auth/AuthContext";
import { getTransparencyAuthorizationScope } from "../api/auth";
import {
  isStaleSoldierRosterCursorError,
  listSoldierRosterPage,
  SoldierRosterItemDTO,
} from "../api/soldiers";
import DateInput from "./DateInput";
import { translateApiError } from "../utils/translateApiError";
import { todayIso } from "../utils/formatDate";
import ConfirmDialog from "./ConfirmDialog";

interface Props {
  principalId: string;
  principalRoles: { isCommander: boolean; isDutyManager: boolean };
}

interface DeputySearchPageState {
  authorizationIdentity: string;
  search: string;
  items: SoldierRosterItemDTO[];
  nextCursor: string | null;
  hasMore: boolean;
}

function statusOf(g: DeputyDTO, today: string): "active" | "future" | "expired" {
  if (g.end_date < today) return "expired";
  if (g.start_date > today) return "future";
  return "active";
}

export default function DeputiesPanel({ principalId, principalRoles }: Props) {
  const { t } = useTranslation();
  const { user, authScopeReady } = useAuth();
  const [grants, setGrants] = useState<DeputyDTO[]>([]);
  const [selectedDeputyId, setSelectedDeputyId] = useState("");
  const [selectionAuthorizationIdentity, setSelectionAuthorizationIdentity] =
    useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [open, setOpen] = useState(false);
  const [candidateResults, setCandidateResults] =
    useState<DeputySearchPageState | null>(null);
  const [loadingMoreKey, setLoadingMoreKey] = useState<string | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [role, setRole] = useState<"commander" | "duty_manager">(
    principalRoles.isCommander ? "commander" : "duty_manager"
  );
  const [startDate, setStartDate] = useState(todayIso());
  const [endDate, setEndDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rosterRequestGeneration = useRef(0);
  const continuationRequest = useRef<{
    key: string;
    controller: AbortController;
  } | null>(null);

  const bothRoles = principalRoles.isCommander && principalRoles.isDutyManager;
  const rosterAuthorizationIdentity = authScopeReady
    ? getTransparencyAuthorizationScope(user)
    : null;
  const selectionMatchesCurrentScope = Boolean(
    selectedDeputyId &&
      authScopeReady &&
      rosterAuthorizationIdentity &&
      selectionAuthorizationIdentity === rosterAuthorizationIdentity,
  );
  const effectiveSearchText =
    selectedDeputyId && !selectionMatchesCurrentScope ? "" : searchText;
  const normalizedSearch = effectiveSearchText.trim();
  const currentSearchKey = rosterAuthorizationIdentity
    ? JSON.stringify([rosterAuthorizationIdentity, normalizedSearch])
    : null;
  const visibleCandidateResults =
    open &&
    rosterAuthorizationIdentity &&
    candidateResults?.authorizationIdentity === rosterAuthorizationIdentity &&
    candidateResults.search === normalizedSearch
      ? candidateResults
      : null;
  async function refresh() {
    setGrants(await listDeputies(principalId));
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [principalId]);

  useEffect(() => {
    if (
      selectedDeputyId &&
      (!authScopeReady ||
        !rosterAuthorizationIdentity ||
        selectionAuthorizationIdentity !== rosterAuthorizationIdentity)
    ) {
      setSelectedDeputyId("");
      setSelectionAuthorizationIdentity(null);
      setSearchText("");
    }
  }, [
    authScopeReady,
    rosterAuthorizationIdentity,
    selectedDeputyId,
    selectionAuthorizationIdentity,
  ]);

  useEffect(() => {
    const authorizationIdentity = rosterAuthorizationIdentity;
    const search = effectiveSearchText.trim();
    const generation = ++rosterRequestGeneration.current;
    const controller = new AbortController();
    continuationRequest.current?.controller.abort();
    continuationRequest.current = null;
    setLoadingMoreKey(null);
    setCandidateResults(null);

    if (!open || !authorizationIdentity) {
      return () => {
        controller.abort();
        if (rosterRequestGeneration.current === generation) {
          rosterRequestGeneration.current += 1;
        }
      };
    }

    const timeout = window.setTimeout(() => {
      void listSoldierRosterPage({
        search,
        sort: "full_name",
        descending: false,
        page_size: 10,
        active_only: false,
        signal: controller.signal,
      })
        .then((page) => {
          if (
            !controller.signal.aborted &&
            rosterRequestGeneration.current === generation
          ) {
            setCandidateResults({
              authorizationIdentity,
              search,
              items: page.items,
              nextCursor: page.next_cursor,
              hasMore: page.has_more,
            });
          }
        })
        .catch(() => undefined);
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
  }, [effectiveSearchText, open, rosterAuthorizationIdentity]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function loadMoreCandidates() {
    const page = visibleCandidateResults;
    if (
      !page ||
      !page.hasMore ||
      !page.nextCursor ||
      !rosterAuthorizationIdentity ||
      !currentSearchKey
    ) {
      return;
    }

    const requestKey = currentSearchKey;
    if (continuationRequest.current?.key === requestKey) return;

    continuationRequest.current?.controller.abort();
    const controller = new AbortController();
    const generation = rosterRequestGeneration.current;
    const cursor = page.nextCursor;
    continuationRequest.current = { key: requestKey, controller };
    setLoadingMoreKey(requestKey);

    try {
      const nextPage = await listSoldierRosterPage({
        cursor,
        search: page.search,
        sort: "full_name",
        descending: false,
        page_size: 10,
        active_only: false,
        signal: controller.signal,
      });

      if (
        controller.signal.aborted ||
        rosterRequestGeneration.current !== generation
      ) {
        return;
      }

      setCandidateResults((current) => {
        if (
          !current ||
          current.authorizationIdentity !== page.authorizationIdentity ||
          current.search !== page.search ||
          current.nextCursor !== cursor
        ) {
          return current;
        }

        const existingIds = new Set(current.items.map((soldier) => soldier.id));
        return {
          ...current,
          items: [
            ...current.items,
            ...nextPage.items.filter((soldier) => !existingIds.has(soldier.id)),
          ],
          nextCursor: nextPage.next_cursor,
          hasMore: nextPage.has_more,
        };
      });
    } catch (error) {
      if (
        !controller.signal.aborted &&
        rosterRequestGeneration.current === generation &&
        continuationRequest.current?.controller === controller &&
        isStaleSoldierRosterCursorError(error)
      ) {
        const recoveryController = new AbortController();
        continuationRequest.current = {
          key: requestKey,
          controller: recoveryController,
        };

        try {
          const refreshedPage = await listSoldierRosterPage({
            search: page.search,
            sort: "full_name",
            descending: false,
            page_size: 10,
            active_only: false,
            signal: recoveryController.signal,
          });

          if (
            recoveryController.signal.aborted ||
            rosterRequestGeneration.current !== generation ||
            continuationRequest.current?.controller !== recoveryController
          ) {
            return;
          }

          setCandidateResults((current) => {
            if (
              rosterRequestGeneration.current !== generation ||
              recoveryController.signal.aborted ||
              continuationRequest.current?.key !== requestKey ||
              continuationRequest.current?.controller !== recoveryController ||
              !current ||
              current.authorizationIdentity !== page.authorizationIdentity ||
              current.search !== page.search ||
              current.nextCursor !== cursor
            ) {
              return current;
            }

            return {
              ...current,
              items: refreshedPage.items,
              nextCursor: refreshedPage.next_cursor,
              hasMore: refreshedPage.has_more,
            };
          });
        } catch {
          // A later bottom scroll retries the stale-cursor refresh.
        } finally {
          if (continuationRequest.current?.controller === recoveryController) {
            continuationRequest.current = null;
            setLoadingMoreKey((current) =>
              current === requestKey ? null : current,
            );
          }
        }
      }
    } finally {
      if (continuationRequest.current?.controller === controller) {
        continuationRequest.current = null;
        setLoadingMoreKey((current) =>
          current === requestKey ? null : current,
        );
      }
    }
  }

  function selectCandidate(soldier: SoldierRosterItemDTO) {
    if (!authScopeReady || !rosterAuthorizationIdentity) return;
    setSelectedDeputyId(soldier.id);
    setSelectionAuthorizationIdentity(rosterAuthorizationIdentity);
    setSearchText(`${soldier.full_name} (${soldier.personal_number})`);
    setOpen(false);
  }

  async function handleAdd() {
    if (!selectionMatchesCurrentScope) return;
    setError(null);
    try {
      await createDeputy({
        principal_id: principalId, deputy_id: selectedDeputyId, role,
        start_date: startDate, end_date: endDate,
      });
      setSelectedDeputyId("");
      setSelectionAuthorizationIdentity(null);
      setSearchText("");
      await refresh();
    } catch (err) {
      setError(translateApiError(err, t, "שגיאה בעדכון ממלא המקום"));
    }
  }

  async function handleRevoke(id: string) {
    await revokeDeputy(id);
    await refresh();
  }

  const today = todayIso();

  return (
    <div className="space-y-3" dir="rtl">
      <h4 className="font-semibold text-sm">{t("deputies.title", "ממלאי מקום")}</h4>

      {!(open && (visibleCandidateResults?.items.length ?? 0) > 0) && (grants.length === 0 ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">{t("deputies.no_deputies", "אין ממלאי מקום מוגדרים")}</p>
      ) : (
        <ul className="space-y-1">
          {grants.map((g) => {
            const s = statusOf(g, today);
            const badgeKey = s === "active" ? "deputies.active_badge" : s === "future" ? "deputies.future_badge" : "deputies.expired_badge";
            const badgeText = s === "active" ? "פעיל" : s === "future" ? "עתידי" : "פג תוקף";
            return (
              <li key={g.id} className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1">
                <span>
                  {g.deputy_name}{" "}
                  <span className="text-xs text-gray-400">
                    ({g.role === "commander" ? t("deputies.role_commander", "מפקד") : t("deputies.role_duty_manager", "אחראי תורנויות")}, {g.start_date} — {g.end_date})
                  </span>{" "}
                  <span className="text-xs">{t(badgeKey, badgeText)}</span>
                </span>
                {s !== "expired" && (
                  <button type="button" onClick={() => setRevokeId(g.id)} className="text-red-600 text-xs hover:underline">
                    {t("deputies.revoke", "הסר")}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ))}

      <div className="flex flex-wrap gap-2 items-end pt-2 border-t dark:border-gray-600">
        <div ref={containerRef} className="relative">
          <input
            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={effectiveSearchText}
            onChange={(e) => {
              setSearchText(e.target.value);
              setSelectedDeputyId("");
              setSelectionAuthorizationIdentity(null);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            placeholder={t("deputies.search_soldier_placeholder", "חיפוש חייל...")}
            autoComplete="off"
          />
          {open && visibleCandidateResults && visibleCandidateResults.items.length > 0 && (
            <ul
              className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto"
              onScroll={(event) => {
                const element = event.currentTarget;
                if (element.scrollHeight - element.scrollTop - element.clientHeight <= 48) {
                  void loadMoreCandidates();
                }
              }}
            >
              {visibleCandidateResults.items.map((s) => (
                <li
                  key={s.id}
                  className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                  onClick={() => selectCandidate(s)}
                >
                  {s.full_name} <span className="text-gray-400 text-xs">({s.personal_number})</span>
                </li>
              ))}
              {loadingMoreKey === currentSearchKey && (
                <li className="px-3 py-2 text-center text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
                  {t("team.roster_loading_more", "Loading more soldiers...")}
                </li>
              )}
            </ul>
          )}
        </div>

        {bothRoles && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500" htmlFor="deputy-role-select">{t("deputies.role_label", "תפקיד")}</label>
            <select
              id="deputy-role-select"
              value={role}
              onChange={(e) => setRole(e.target.value as "commander" | "duty_manager")}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            >
              <option value="commander">{t("deputies.role_commander", "מפקד")}</option>
              <option value="duty_manager">{t("deputies.role_duty_manager", "אחראי תורנויות")}</option>
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500" htmlFor="deputy-start-date">{t("deputies.start_date", "מתאריך")}</label>
          <DateInput id="deputy-start-date" className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={startDate} onChange={setStartDate} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500" htmlFor="deputy-end-date">{t("deputies.end_date", "עד תאריך")}</label>
          <DateInput id="deputy-end-date" className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={endDate} onChange={setEndDate} min={startDate} />
        </div>

        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={!selectionMatchesCurrentScope}
          className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          {t("deputies.add", "הוסף ממלא מקום")}
        </button>
      </div>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <ConfirmDialog
        open={revokeId !== null}
        title={t("deputies.revoke_title", "הסרת ממלא מקום")}
        message={t("deputies.revoke_confirm", "להסיר את ממלא המקום?")}
        danger
        onClose={() => setRevokeId(null)}
        onConfirm={() => {
          const id = revokeId;
          setRevokeId(null);
          if (id) void handleRevoke(id);
        }}
      />
    </div>
  );
}

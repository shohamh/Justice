import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RangeEvent } from "../../api/ranges";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";
import { formatDate, todayIso } from "../../utils/formatDate";

interface Props {
  ranges: RangeEvent[];
  onOpenRange: (range: RangeEvent) => void;
  title?: string;
  hasMore?: boolean;
  loadingMore?: boolean;
  loadError?: boolean;
  onLoadMore?: () => void;
}

const ROW_HEIGHT = 44;
const VIEWPORT_HEIGHT = 352;
const OVERSCAN = 4;

export default function UpcomingRangesWidget({ ranges, onOpenRange, title, hasMore, loadingMore, loadError, onLoadMore }: Props) {
  const { t } = useTranslation();
  const [scrollTop, setScrollTop] = useState(0);
  const today = todayIso();
  const upcoming = (Array.isArray(ranges) ? ranges : [])
    .filter((r) => r.assigned_to_me === true && r.date >= today && r.status === "planned")
    .sort((a, b) => a.date.localeCompare(b.date));
  const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const end = Math.min(upcoming.length, Math.ceil((scrollTop + VIEWPORT_HEIGHT) / ROW_HEIGHT) + OVERSCAN);

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">{title ?? "מטווחים קרובים"}</h2>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין מטווחים קרובים</p>
      ) : (
        <div
          className="overflow-auto"
          role="region"
          aria-label={t("home.ranges_region")}
          tabIndex={0}
          style={{ maxHeight: VIEWPORT_HEIGHT }}
          onScroll={event => {
          const element = event.currentTarget;
          setScrollTop(element.scrollTop);
          if (hasMore && !loadingMore && !loadError && element.scrollTop + element.clientHeight >= element.scrollHeight - ROW_HEIGHT * 4) onLoadMore?.();
          }}
        >
        <table className="w-full text-sm table-fixed">
          <thead>
            <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
              <th className="pb-2 w-6"></th>
            </tr>
          </thead>
          <tbody>
            {start > 0 && <tr aria-hidden="true"><td colSpan={4} style={{ height: start * ROW_HEIGHT, padding: 0 }} /></tr>}
            {upcoming.slice(start, end).map((range) => (
              <tr
                key={range.id}
                style={{ height: ROW_HEIGHT }}
                className="border-b last:border-0 dark:border-gray-600 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => onOpenRange(range)}
                title={t("home.open_range", { location: range.location, date: formatDate(range.date) })}
              >
                <td className="py-2">{formatDate(range.date)}</td>
                <td className="py-2">{RANGE_TYPE_LABELS[range.range_type] ?? range.range_type}</td>
                <td className="py-2 truncate" title={range.location}>{range.location}</td>
                <td className="py-2 text-gray-400 text-xs">
                  <button
                    type="button"
                    aria-label={t("home.open_range", { location: range.location, date: formatDate(range.date) })}
                    onClick={event => {
                      event.stopPropagation();
                      onOpenRange(range);
                    }}
                    className="rounded px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600"
                  >
                    ›
                  </button>
                </td>
              </tr>
            ))}
            {end < upcoming.length && <tr aria-hidden="true"><td colSpan={4} style={{ height: (upcoming.length - end) * ROW_HEIGHT, padding: 0 }} /></tr>}
          </tbody>
        </table>
        </div>
      )}
      {hasMore && (
        <button
          type="button"
          disabled={loadingMore}
          onClick={onLoadMore}
          aria-live="polite"
          className="mt-2 rounded border border-gray-300 px-3 py-1 text-sm text-blue-700 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:text-blue-300 dark:hover:bg-gray-800"
        >
          {loadError ? t("common.retry") : loadingMore ? t("home.ranges_loading_more") : t("home.ranges_load_more")}
        </button>
      )}
    </section>
  );
}

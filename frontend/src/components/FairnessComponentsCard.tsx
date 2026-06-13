import { useEffect, useState } from "react";
import { getFairnessComponents, type FairnessComponents } from "../api/scoring";

function cvBadge(cv: number): string {
  if (cv < 0.25) return "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300";
  if (cv <= 0.5) return "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300";
  return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
}

/**
 * פיזור עומס per connected component of soldiers who do the same duties.
 * Splits the single global CV — which is inflated by soldiers exempt from
 * everything and by mixing groups that can't substitute for each other — into a
 * per-group spread plus the count of soldiers exempt from all duties.
 */
export default function FairnessComponentsCard() {
  const [data, setData] = useState<FairnessComponents | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getFairnessComponents().then(setData).catch(() => setFailed(true));
  }, []);

  if (failed || !data) return null;

  return (
    <div dir="rtl" className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">פיזור עומס לפי קבוצות כשירות</h3>
        {data.exempt_from_all.count > 0 && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {data.exempt_from_all.count} חיילים פטורים מכל התורנויות
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
        כל קבוצה היא אוסף חיילים שמבצעים את אותן תורנויות (מחוברים דרך סוגי תורנות משותפים).
        הפיזור (CV) מחושב בנפרד לכל קבוצה — כך רואים את ההוגנות האמיתית בתוך כל קבוצה, בלי עיוות
        מחיילים שאינם כשירים לאותן תורנויות.
      </p>
      <div className="space-y-2">
        {data.components.map((c, i) => (
          <div key={i} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-sm text-gray-700 dark:text-gray-200">
                <span className="font-semibold">{c.soldier_count}</span> חיילים
              </span>
              {c.effort ? (
                <span className={`text-xs font-semibold px-2 py-0.5 rounded ${cvBadge(c.effort.cv)}`}>
                  פיזור CV {(c.effort.cv * 100).toFixed(0)}%
                </span>
              ) : (
                <span className="text-xs text-gray-400">פחות מ-2 חיילים</span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {c.duty_type_names.map((n) => (
                <span
                  key={n}
                  className="text-xs bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 px-2 py-0.5 rounded"
                >
                  {n}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

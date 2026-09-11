import { InlineMath, BlockMath } from "react-katex";

export default function FairnessHelpModal({ variant, onClose }: { variant: "soldiers" | "subunits"; onClose: () => void }) {
  const isSoldiers = variant === "soldiers";
  const unit = isSoldiers ? "חייל" : "מסגרת";
  const unitPlural = isSoldiers ? "החיילים" : "המסגרות";
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto space-y-5"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-gray-900 dark:text-white">
          {isSoldiers ? "פיזור עומס (CV) — כיצד מחושב?" : "פיזור עומס בין מסגרות — כיצד מחושב?"}
        </h3>

        <p className="text-sm text-gray-700 dark:text-gray-300">
          {isSoldiers
            ? "מדד המציג כמה שוויונית חלוקת התורנויות בין החיילים. ערך נמוך פירושו שכולם נושאים עומס דומה."
            : "מדד המציג כמה שוויוני הנטל בין המסגרות השונות, לפי ממוצע עומס לחייל בכל מסגרת."}
        </p>

        {/* Stddev */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-1">שלב 1 — סטיית תקן (σ)</p>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
            לכל {unit} מחשבים כמה הוא שונה מהממוצע, מעלים בריבוע (כדי שהפרשים בכיוונים הפוכים לא יתבטלו), מחשבים ממוצע של הריבועים, ולוקחים שורש ריבועי.
          </p>
          <div className="bg-gray-50 dark:bg-gray-900 rounded-lg px-4 py-3 overflow-x-auto text-center">
            <BlockMath math={String.raw`\sigma = \sqrt{\frac{\displaystyle\sum_{i=1}^{n}(x_i - \mu)^2}{n}}`} />
          </div>
          <div className="mt-2 text-xs text-gray-500 dark:text-gray-400 space-y-0.5 pr-1">
            <p><InlineMath math="x_i" /> — {isSoldiers ? "עומס חייל i" : "ממוצע עומס מסגרת i"}</p>
            <p><InlineMath math="\mu" /> — ממוצע {isSoldiers ? "עומסי כל החיילים" : "ממוצעי כל המסגרות"}</p>
            <p><InlineMath math="n" /> — מספר {unitPlural}</p>
          </div>
        </div>

        {/* CV */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-1">שלב 2 — מקדם הפיזור (CV)</p>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
            מנרמל את סטיית התקן לפי הממוצע, כך שאפשר להשוות פיזור גם כשהממוצע משתנה לאורך הזמן.
          </p>
          <div className="bg-gray-50 dark:bg-gray-900 rounded-lg px-4 py-3 overflow-x-auto text-center">
            <BlockMath math={String.raw`CV = \frac{\sigma}{\mu}`} />
          </div>
        </div>

        {/* Worked example */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-2">דוגמה</p>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
            שתי קבוצות של 4 {unitPlural} עם אותו ממוצע עומס (25%), אבל פיזור שונה:
          </p>
          <div className="space-y-2 text-sm">
            <div className="flex items-start gap-2">
              <span className="mt-1 inline-block w-2 h-2 rounded-full shrink-0 bg-green-500" />
              <span className="text-gray-700 dark:text-gray-300">
                <strong>24%, 25%, 26%, 25%</strong> — כולם קרובים לממוצע ← <strong>CV ≈ 3%</strong>, פיזור בריא.
              </span>
            </div>
            <div className="flex items-start gap-2">
              <span className="mt-1 inline-block w-2 h-2 rounded-full shrink-0 bg-red-500" />
              <span className="text-gray-700 dark:text-gray-300">
                <strong>10%, 15%, 35%, 40%</strong> — אותו ממוצע, אבל שניים נושאים כמעט כפול מהשניים האחרים ← <strong>CV ≈ 51%</strong>, פיזור לא שוויוני.
              </span>
            </div>
          </div>
        </div>

        {/* Thresholds */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-2">פרשנות</p>
          <div className="space-y-2 text-sm">
            {[
              { dot: "bg-green-500", range: "פחות מ-25%", desc: isSoldiers ? "פיזור בריא — העומס מחולק בצורה שוויונית" : "פיזור בריא — המסגרות נושאות עומס דומה" },
              { dot: "bg-yellow-500", range: "25%–50%", desc: "אי-שוויון בינוני — כדאי לבדוק" },
              { dot: "bg-red-500", range: "מעל 50%", desc: isSoldiers ? "פיזור גבוה — חיילים מסוימים נושאים עומס שונה מאוד מהממוצע" : "פיזור גבוה — מסגרת אחת לפחות נושאת עומס שונה מאוד משאר המסגרות" },
            ].map(({ dot, range, desc }) => (
              <div key={range} className="flex items-start gap-2">
                <span className={`mt-1 inline-block w-2 h-2 rounded-full shrink-0 ${dot}`} />
                <span className="text-gray-700 dark:text-gray-300"><strong>{range}</strong> — {desc}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="text-left pt-1">
          <button type="button" className="bg-indigo-600 text-white px-4 py-1.5 rounded text-sm" onClick={onClose}>סגור</button>
        </div>
      </div>
    </div>
  );
}

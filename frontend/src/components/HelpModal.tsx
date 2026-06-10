import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { EffortBreakdown, getEffortBreakdown } from "../api/scoring";

interface Props {
  onClose: () => void;
  gimelimEnabled?: boolean;
}

function buildTabs(gimelimEnabled: boolean) {
  const tabs = [
    { id: "swaps", label: "🔄 החלפות" },
    { id: "algorithm", label: "⚙️ האלגוריתם" },
    { id: "fairness", label: "⚖️ הוגנות ושקיפות" },
    { id: "deep", label: "🔬 מאחורי הקלעים" },
  ];
  if (gimelimEnabled) {
    tabs.push({ id: "gimelim", label: "🏥 גימלים" });
  }
  return tabs;
}

function FlowStep({ icon, text, color = "indigo" }: { icon: string; text: string; color?: string }) {
  const colors: Record<string, string> = {
    indigo: "bg-indigo-50 dark:bg-indigo-950 border-indigo-200 dark:border-indigo-800 text-indigo-800 dark:text-indigo-200",
    green: "bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800 text-green-800 dark:text-green-200",
    red: "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200",
    amber: "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200",
    blue: "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200",
    gray: "bg-gray-50 dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300",
  };
  return (
    <div className={`border rounded-lg px-3 py-2 text-sm font-medium text-center ${colors[color] ?? colors.indigo}`}>
      {icon} {text}
    </div>
  );
}

function Arrow({ split }: { split?: boolean }) {
  if (split) {
    return (
      <div className="flex items-start gap-1 my-1">
        <div className="flex flex-col items-center flex-1">
          <div className="text-gray-400 text-xs mb-0.5">פתוח לכולם</div>
          <div className="text-gray-300 text-lg">↓</div>
        </div>
        <div className="flex flex-col items-center flex-1">
          <div className="text-gray-400 text-xs mb-0.5">חייל ספציפי</div>
          <div className="text-gray-300 text-lg">↓</div>
        </div>
      </div>
    );
  }
  return <div className="text-center text-gray-300 text-lg my-0.5">↓</div>;
}

function SwapsTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">איך עובדות החלפות?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        מנגנון ההחלפות מאפשר לשני חיילים להחליף ביניהם תורנויות, בכפוף לאישור. כך זה עובד:
      </p>

      {/* Flow diagram */}
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600">
        <FlowStep icon="🙋" text="חייל מגיש בקשת החלפה" color="indigo" />
        <Arrow split />
        <div className="grid grid-cols-2 gap-2">
          <FlowStep icon="📢" text="מתפרסם בלוח ההחלפות" color="blue" />
          <FlowStep icon="📩" text="נשלחת הודעה לחייל המבוקש" color="blue" />
        </div>
        <Arrow />
        <FlowStep icon="🤝" text="חייל מציע להחליף ושני הצדדים מאשרים" color="indigo" />
        <Arrow />
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">נדרש אישור מפקד</div>
            <FlowStep icon="👮" text="המפקד מאשר" color="amber" />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">ללא אישור</div>
            <div className="h-8" />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="bg-blue-50 dark:bg-blue-950 rounded-lg p-3 border border-blue-200 dark:border-blue-800">
          <p className="font-medium text-blue-800 dark:text-blue-200 mb-1">📌 בקשה פתוחה</p>
          <p className="text-blue-700 dark:text-blue-300">לא יודעים מי יחליף? כל חייל ביחידה יכול לראות את הבקשה ולהציע עצמו.</p>
        </div>
        <div className="bg-purple-50 dark:bg-purple-950 rounded-lg p-3 border border-purple-200 dark:border-purple-800">
          <p className="font-medium text-purple-800 dark:text-purple-200 mb-1">📌 בקשה ממוקדת</p>
          <p className="text-purple-700 dark:text-purple-300">יש מישהו ספציפי? ציינו אותו — הוא יקבל התראה ויאשר או ידחה.</p>
        </div>
        <div className="bg-amber-50 dark:bg-amber-950 rounded-lg p-3 border border-amber-200 dark:border-amber-800">
          <p className="font-medium text-amber-800 dark:text-amber-200 mb-1">⚠️ חשוב לדעת</p>
          <ul className="text-amber-700 dark:text-amber-300 space-y-1 list-disc list-inside">
            <li>החלפה אינה משפיעה על הניקוד — הניקוד נשאר על מי שסיפק את התורנות בפועל.</li>
            <li>המפקד רשאי לדחות גם אם שני הצדדים הסכימו.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function AlgorithmTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">איך האלגוריתם מחלק תורנויות?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        האלגוריתם פותר את <strong>כל המשמרות בבת אחת</strong> — לא אחת אחרי השנייה — ומחפש שיבוץ שמכסה את כולן תוך שמירה על כל הכללים:
      </p>

      {/* Flow diagram */}
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="📋" text="כל המשמרות הפתוחות נאספות יחד" color="gray" />
        <Arrow />
        <FlowStep icon="🚫" text="לכל משמרת: מסננים חיילים לא כשירים (פטורים, אילוצים, יחידה)" color="amber" />
        <Arrow />
        <FlowStep icon="⚖️" text="מחפשים שיבוץ שמכסה את הכל ועומד בכל המגבלות" color="blue" />
        <Arrow />
        <FlowStep icon="📊" text="בין פתרונות תקינים — מעדיפים חיילים עם עומס רבעוני נמוך" color="indigo" />
        <Arrow />
        <FlowStep icon="✅" text="שיבוץ בוצע!" color="green" />
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 מה האלגוריתם לוקח בחשבון?</p>
        {[
          { icon: "📊", title: "עומס רבעוני", desc: "מי שחלקו בתורנויות ברבעונים האחרונים נמוך מחבריו מקבל עדיפות. חייל חדש בעל עומס אפס יזכה בתורנויות עד שישתווה לשאר. ראו הסבר מלא בטאב הוגנות." },
          { icon: "🚫", title: "פטורים ואילוצים", desc: "חיילים עם פטור רלוונטי מוסרים. אילוצים אישיים (תאריכים) גם מסננים." },
          { icon: "🎖️", title: "דרישות המשמרת", desc: "חוגרים/קצינים, בה\"ד 1, מין — כל משמרת מגדירה את הדרישות שלה." },
          { icon: "🔒", title: "איזון עומסים", desc: "האלגוריתם ממזער את הפער בין החייל עם העומס הגבוה ביותר לנמוך ביותר. אם אין מספיק חיילים כשירים, הפער עלול להישאר — האלגוריתם עושה את מיטבו בתוך האילוצים." },
          { icon: "⏱️", title: "מגבלת עומס (T/W)", desc: "חייל לא יכול לקבל יותר מ-T ימי תורנות בכל חלון W ימים ברצף. זה מונע עומס יתר על חייל אחד." },
          { icon: "🗺️", title: "רזרבה", desc: "חיילי רזרבה משובצים כגיבוי לאותה משמרת — האלגוריתם מעדיף רזרבה מהיחידה הקרובה ביותר בהיררכיה." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📝 דוגמה מספרית</p>
        <p className="text-indigo-700 dark:text-indigo-300 text-xs leading-relaxed">
          נניח שיש 3 חיילים: דן (עומס 3%), יעל (5%), ורוני (8%).
          משמרת חדשה צריכה מישהו — יעל פטורה ממנה.
          האלגוריתם בוחר מדן ורוני; מכיוון שדן בעל עומס נמוך יותר הוא יקבל עדיפות.
          כך ברמה העולמית, ההפרש בין רוני (8%) לדן ייצטמצם עם הזמן.
        </p>
        <div className="grid grid-cols-3 gap-2 text-xs text-center">
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן</p>
            <p>עומס: 3%</p>
            <p className="text-green-600">⬆ עדיפות גבוהה</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל</p>
            <p>עומס: 5%</p>
            <p className="text-gray-500">✗ פטור חל</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-orange-700 dark:text-orange-300">רוני</p>
            <p>עומס: 8%</p>
            <p className="text-orange-600">⬇ עדיפות נמוכה</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function FairnessTab() {
  const { user } = useAuth();
  const [myBreakdown, setMyBreakdown] = useState<EffortBreakdown | null>(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(false);

  useEffect(() => {
    if (!user) return;
    setLoadingBreakdown(true);
    getEffortBreakdown(user.id)
      .then(setMyBreakdown)
      .catch(() => setMyBreakdown(null))
      .finally(() => setLoadingBreakdown(false));
  }, [user]);

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">הוגנות ושקיפות</h3>
      <p className="text-gray-700 dark:text-gray-300">
        המערכת מודדת הוגנות על פי <strong>עומס רבעוני</strong> — כמה מסך תורנויות היחידה ברבעון נשא כל חייל, בממוצע על פני הרבעונים שבהם שירת.
      </p>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📊 איך מחשבים את העומס הרבעוני?</p>

        <div className="space-y-2 text-indigo-700 dark:text-indigo-300">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-medium text-sm">שלב 1 — חלק רבעוני</p>
            <div className="flex items-center justify-center gap-2 text-xs flex-wrap">
              <div className="bg-indigo-100 dark:bg-indigo-900 rounded px-2 py-1 font-medium">ניקוד החייל ברבעון</div>
              <div className="text-gray-500 font-bold">÷</div>
              <div className="bg-purple-100 dark:bg-purple-900 rounded px-2 py-1 font-medium">ניקוד כלל היחידה ברבעון</div>
              <div className="text-gray-500 font-bold">=</div>
              <div className="bg-green-100 dark:bg-green-900 rounded px-2 py-1 font-medium">חלק%</div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-medium text-sm">שלב 2 — ממוצע משוקלל לפי נוכחות</p>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              רבעונים בהם שירתת פחות ימים (הצטרפת באמצע, חופשה ממושכת) מקבלים משקל פחות בממוצע. רבעון שלם = משקל מלא.
            </p>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-2">
            <p className="font-medium text-sm">שלב 3 — חישוב הממוצע הסופי</p>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              סכום החלקים המשוקללים מחולק ב<strong>מכנה</strong> הכולל שני חלקים:
            </p>
            <div className="text-xs space-y-1.5">
              <div className="flex gap-2 items-start">
                <span className="shrink-0 bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300 rounded px-1 font-medium">W</span>
                <span className="text-gray-600 dark:text-gray-300"><strong>היסטוריה כוללת</strong> — סכום הנוכחות ברבעונות העבר. 4 רבעונות מלאים = W=4.</span>
              </div>
              <div className="flex gap-2 items-start">
                <span className="shrink-0 bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded px-1 font-medium">C</span>
                <span className="text-gray-600 dark:text-gray-300"><strong>רבעון נוכחי — תמיד 1</strong> — מייצג סיבוב תכנון שלם שטרם בוצע. C אינו מודד כמה מהרבעון הנוכחי עבר — הוא קבוע 1 לכולם. הוא נכלל במכנה <em>בלבד</em>, כך שאין לו עדיין תרומה לעומס שנצבר.</span>
              </div>
            </div>
            <div className="bg-indigo-50 dark:bg-indigo-900 rounded p-2 text-xs text-center font-medium text-indigo-800 dark:text-indigo-200">
              עומס = עומס שנצבר ÷ (W + 1)
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              המשמעות: לפני כל סיבוב, הציון של <em>כולם</em> נמוך יותר ב-1 מחלק — ורק תורנויות חדשות יחזירו אותו לרמה הקודמת. זה מונע מוותיקים &ldquo;לנוח&rdquo; על ניקוד עבר.
            </p>
          </div>
        </div>

        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
          <p className="font-medium mb-1">🔑 למה זה פותר את בעיית הוותיקות?</p>
          <p>אם ביחידה היו מעט תורנויות לפני 5 שנים — כולם קיבלו חלק קטן. זה לא פוגע בחייל ותיק, כי היחס (חלק/כלל) נשאר הוגן בכל רבעון. חייל חדש מושווה <em>רק לתקופה שהוא שירת בה</em>.</p>
        </div>
      </div>

      {/* Personal breakdown */}
      <div className="bg-green-50 dark:bg-green-950 rounded-xl p-4 border border-green-200 dark:border-green-800 space-y-2">
        <p className="font-semibold text-green-800 dark:text-green-200">🔢 הנתונים שלי</p>
        {loadingBreakdown && (
          <p className="text-xs text-gray-500 dark:text-gray-400">טוען...</p>
        )}
        {!loadingBreakdown && myBreakdown && myBreakdown.quarters.length === 0 && (
          <p className="text-xs text-gray-600 dark:text-gray-400">אין היסטוריה — חייל חדש. העומס שלך הוא 0%.</p>
        )}
        {!loadingBreakdown && myBreakdown && myBreakdown.quarters.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse" style={{ minWidth: "320px" }}>
                <thead>
                  <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-green-800">
                    <th className="text-right py-1 pb-1.5 font-medium">רבעון</th>
                    <th className="text-right py-1 pb-1.5 font-medium px-2">ניקוד חייל</th>
                    <th className="text-right py-1 pb-1.5 font-medium px-2">ניקוד יחידה</th>
                    <th className="text-right py-1 pb-1.5 font-medium px-2">% נוכחות</th>
                    <th className="text-right py-1 pb-1.5 font-medium">חלק בנטל</th>
                  </tr>
                </thead>
                <tbody>
                  {myBreakdown.quarters.map((q) => {
                    const unitScore = parseFloat(q.unit_score);
                    return (
                      <tr key={q.quarter_label} className={`border-b border-green-200 dark:border-green-800 ${q.is_partial ? "bg-amber-50/50 dark:bg-amber-950/20" : ""}`}>
                        <td className="py-1.5 text-gray-700 dark:text-gray-300 font-medium">
                          <span className={q.is_partial ? "italic" : ""}>{q.quarter_label}</span>
                          {q.is_partial && <span className="mr-1 text-amber-600 dark:text-amber-400 font-normal not-italic">(חלקי)</span>}
                        </td>
                        <td className="py-1.5 text-right px-2 text-gray-700 dark:text-gray-300 tabular-nums">{parseFloat(q.soldier_score).toFixed(1)}</td>
                        <td className="py-1.5 text-right px-2 text-gray-500 dark:text-gray-400 tabular-nums">
                          {unitScore > 0 ? unitScore.toFixed(1) : "—"}
                        </td>
                        <td className="py-1.5 text-right px-2 text-gray-500 dark:text-gray-400 tabular-nums">{(parseFloat(q.active_frac) * 100).toFixed(0)}%</td>
                        <td className="py-1.5 text-right font-semibold text-green-700 dark:text-green-300 tabular-nums">{(parseFloat(q.share) * 100).toFixed(2)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {myBreakdown.quarters.some((q) => q.is_partial) && (
                <p className="mt-1.5 text-xs text-amber-700 dark:text-amber-400">
                  ⚠️ <strong>רבעון חלקי</strong> — הרבעון עדיין בתהליך; מוצגים נתונים עד אתמול בלבד. ניקוד חייל/יחידה הוא ניקוד רבעוני בלבד — לא מצטבר.
                </p>
              )}
            </div>
            {/* Derivation with real numbers */}
            {(() => {
              const A = parseFloat(myBreakdown.A_i);
              const W = parseFloat(myBreakdown.W_i);
              const C = parseFloat(myBreakdown.C_i);
              const D = W + C;
              const effort = parseFloat(myBreakdown.effort_score);
              return (
                <div className="mt-1 pt-2 border-t border-green-200 dark:border-green-800 space-y-1 text-xs">
                  {[
                    { label: "עומס שנצבר", sub: "סכום (חלק×נוכחות) לכל רבעון", value: `${(A * 100).toFixed(2)}%`, cls: "text-indigo-700 dark:text-indigo-300" },
                    { label: "היסטוריה כוללת (W)", sub: "רבעונות מלאים של היסטוריה", value: W.toFixed(2), cls: "text-amber-700 dark:text-amber-300" },
                    { label: "רבעון נוכחי (C)", sub: "קבוע 1 — מכנה בלבד", value: C.toFixed(2), cls: "text-green-700 dark:text-green-300" },
                    { label: "מכנה (W + C)", sub: "", value: D.toFixed(2), cls: "text-gray-700 dark:text-gray-300", border: true },
                  ].map(({ label, sub, value, cls, border }) => (
                    <div key={label} className={`flex items-start justify-between gap-2 ${border ? "border-t border-green-200 dark:border-green-800 pt-1" : ""}`}>
                      <div className="min-w-0">
                        <span className="text-gray-700 dark:text-gray-300 font-medium">{label}</span>
                        {sub && <span className="text-gray-400 dark:text-gray-500"> — {sub}</span>}
                      </div>
                      <span className={`shrink-0 font-semibold tabular-nums ${cls}`}>{value}</span>
                    </div>
                  ))}
                  <div className="border-t border-green-200 dark:border-green-800 pt-1">
                    <p className="text-gray-600 dark:text-gray-400 font-medium">עומס = עומס שנצבר ÷ מכנה</p>
                    <p className="font-bold text-green-700 dark:text-green-300 tabular-nums">
                      {(A * 100).toFixed(2)}% ÷ {D.toFixed(2)} = {(effort * 100).toFixed(2)}%
                    </p>
                  </div>
                </div>
              );
            })()}
            <div className="flex justify-between items-center pt-1 border-t border-green-200 dark:border-green-800">
              <span className="text-xs text-gray-500 dark:text-gray-400">עומס רבעוני מצטבר:</span>
              <span className="text-lg font-bold text-green-700 dark:text-green-300">
                {(parseFloat(myBreakdown.effort_score) * 100).toFixed(2)}%
              </span>
            </div>
          </>
        )}
      </div>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📝 דוגמה מספרית</p>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-2 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן — 3 שנים בשירות</p>
            <p>ניקוד ממוצע ברבעון: 4</p>
            <p>ניקוד יחידה ממוצע: 100</p>
            <p className="text-green-700 dark:text-green-400 font-medium">עומס: 4% לרבעון</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg p-2 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל — חדשה, רבעון ראשון</p>
            <p>ניקוד ברבעון עד כה: 0</p>
            <p>ניקוד יחידה: 100</p>
            <p className="text-red-600 dark:text-red-400 font-medium">עומס: 0% — תקבל עדיפות!</p>
          </div>
        </div>
        <p className="text-xs text-indigo-700 dark:text-indigo-300">האלגוריתם יעדיף את יעל כי יש לה עומס אפסי — היא תצבור תורנויות עד שהיא מגיעה לרמת דן.</p>
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 שקיפות</p>
        {[
          { icon: "📊", title: "דף השקיפות", desc: "כל חייל רואה את העומס הרבעוני שלו ושל שאר חברי היחידה — כולל טבלה שניתן למיין לפי עומס. לחץ על הערך לפירוט רבעוני." },
          { icon: "📅", title: "תאריך איפוס", desc: "מנהל המערכת יכול לקבוע מאיזה תאריך מחשבים היסטוריה. מומלץ: תחילת רבעון. תורנויות לפני תאריך זה לא נלקחות בחשבון." },
          { icon: "⚖️", title: "הגינות לחדשים", desc: "חייל שהצטרף לאחרונה מושווה רק לתקופה שבה שירת — הוא לא נפגע מכך שהיחידה הייתה פחות עסוקה לפני שהצטרף." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GimelimTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-red-700 dark:text-red-400">🏥 מה זה גימלים?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        גימלים הוא שחרור רפואי זמני מתורנות. כדי למנוע ניצול לרעה, המערכת מגלגלת את החייל שוחרר לתורנות העתידית הקרובה המתאימה — ומחליפה חייל ראשוני קרוב היררכית.
      </p>
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="🏥" text="חייל מדווח גימלים — מפקד מפעיל שחרור גימלים" color="red" />
        <Arrow />
        <FlowStep icon="📋" text="המערכת מציגה הצעה: מי מוקפץ, לאיזו תורנות ישובץ החייל" color="blue" />
        <Arrow />
        <FlowStep icon="✅" text="המפקד מאשר" color="indigo" />
        <Arrow />
        <FlowStep icon="⬆️" text="הרזרבה מוקפצת לכיסוי התורנות הנוכחית" color="amber" />
        <Arrow />
        <FlowStep icon="🔄" text="חייל קרוב היררכית ממומר לרזרבה בתורנות העתידית, החייל שוחרר נכנס כראשוני" color="amber" />
        <Arrow />
        <FlowStep icon="📲" text="כל הצדדים מקבלים הודעה" color="green" />
      </div>
      <ul className="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
        <li>הסיבה הרפואית נשמרת לצפייה של מנהלי תורניות בלבד — לא מועברת לחיילים אחרים.</li>
        <li>אם לא נמצאת תורנות עתידית מתאימה, הגימלים מבוצע בלי שיבוץ מחדש.</li>
        <li>החייל שמומר לרזרבה שומר את הרזרבה המקורית שלו כרזרבה כללית.</li>
      </ul>
    </div>
  );
}

function DeepDiveTab() {
  return (
    <div className="space-y-5 text-sm leading-relaxed" dir="rtl">

      {/* ── Math warning ── */}
      <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 text-amber-800 dark:text-amber-300 text-xs">
        ⚠️ <strong>הסבר מתמטי</strong> — הסעיף הזה מכיל נוסחאות. כל מושג מוסבר גם במילים פשוטות — קראו לפי הנוח לכם.
      </div>

      {/* ── Section 1: הבעיה ── */}
      <section className="space-y-2">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">⚖️ הבעיה: למה לספור תורנויות לא מספיק?</h3>
        <p className="text-gray-700 dark:text-gray-300">
          נניח ששני חיילים עשו כל אחד 10 תורנויות השנה. האם הם שוויוניים?
          לא בהכרח — אחד שירת 300 ימים, השני רק 30. ביחס לזמן שכל אחד היה זמין,
          השני נשא עומס כפול פי 10.
        </p>
        <p className="text-gray-700 dark:text-gray-300">
          ספירת תורנויות גולמית מתעלמת משלושה גורמים:
        </p>
        <ul className="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-400 pr-2">
          <li><strong>זמן שירות</strong> — חייל חדש לא ניתן להשוואה לוותיק ישירות.</li>
          <li><strong>משקל התורנות</strong> — תורנות ארוכה שווה יותר מקצרה.</li>
          <li><strong>גודל היחידה</strong> — אם היחידה צמחה, מאגר התורנויות גדל איתה.</li>
        </ul>
        <p className="text-gray-700 dark:text-gray-300">
          הפתרון: במקום לספור, מודדים <strong>חלק יחסי</strong> — איזה אחוז מסך עומס היחידה נשא החייל,
          יחסית לכמה זמן הוא היה פעיל.
        </p>
      </section>

      {/* ── Section 2: effort_score ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">📐 ניקוד עומס — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">effort_score = A / D</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          לכל חייל מחושב ציון אחד — <strong>עומס רבעוני ממוצע</strong>. הוא מייצג: מתוך כל התורנויות שהיחידה עשתה,
          כמה אחוז נשא החייל בכל רבעון שהיה פעיל בו, בממוצע משוקלל.
        </p>

        {/* Term table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse" style={{ minWidth: "420px" }}>
            <thead>
              <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                <th className="text-right py-1 pr-2 font-medium w-20">סמל</th>
                <th className="text-right py-1 pr-2 font-medium w-32">שם</th>
                <th className="text-right py-1 font-medium">הסבר</th>
              </tr>
            </thead>
            <tbody className="text-gray-700 dark:text-gray-300">
              {[
                { sym: "shareq", name: "חלק רבעוני", def: "ניקוד החייל ברבעון q ÷ ניקוד כלל היחידה ברבעון q. מספר בין 0 ל-1." },
                { sym: "active_fracq", name: "שבר נוכחות", def: "חלק הרבעון שבו החייל היה פעיל (0–1). רבעון מלא = 1." },
                { sym: "A", name: "עומס שנצבר", def: "Σ(shareq × active_fracq) על כל הרבעונים ההיסטוריים. ממוצע משוקלל של החלקים." },
                { sym: "W", name: "היסטוריה כוללת", def: "Σ(active_fracq) על הרבעונים ההיסטוריים. סכום משקלי הנוכחות." },
                { sym: "C", name: "רבעון נוכחי", def: "תמיד 1. מייצג סיבוב התכנון הנוכחי. נכנס למכנה בלבד — אין לו עדיין תרומה לעומס שנצבר." },
                { sym: "D", name: "מכנה", def: "W + C" },
                { sym: "effort_score", name: "עומס רבעוני", def: "A / D — ממוצע החלק הרבעוני על פני כל התקופה שבה שירת החייל." },
              ].map(({ sym, name, def }) => (
                <tr key={sym} className="border-b border-gray-100 dark:border-gray-700">
                  <td className="py-1.5 pr-2 font-mono text-indigo-700 dark:text-indigo-300">{sym}</td>
                  <td className="py-1.5 pr-2 font-medium">{name}</td>
                  <td className="py-1.5">{def}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs space-y-1">
          <p className="font-medium text-indigo-800 dark:text-indigo-200">💡 למה C תמיד 1?</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            לפני כל סיבוב, המכנה של <em>כולם</em> גדל ב-1 — גם אם עוד לא שובצו תורנויות.
            זה &quot;מדלל&quot; את הציון הנוכחי של כולם, ומכריח ותיקים להרוויח מחדש את חלקם.
            חייל שישב בחופשה כל הרבעון לא יכול לנוח על ניקוד עבר.
          </p>
        </div>

        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-xs space-y-1">
          <p className="font-medium text-gray-800 dark:text-gray-200">📝 דוגמה</p>
          <p className="text-gray-600 dark:text-gray-300">
            חייל שירת 4 רבעונות מלאים, ותמיד נשא 5% מעומס היחידה:
          </p>
          <ul className="list-none space-y-0.5 text-gray-600 dark:text-gray-300 pr-2">
            <li>A = 4 × 0.05 = 0.20</li>
            <li>W = 4.0, C = 1.0, D = 5.0</li>
            <li className="font-semibold text-indigo-700 dark:text-indigo-300">effort_score = 0.20 / 5.0 = 0.04 (4%)</li>
          </ul>
        </div>
      </section>

      {/* ── Section 3: Integer bridge ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🔢 מהמספר לשלם — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">effort_offset</code> ו-<code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">effort_per_milli</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          פותר ה-CP-SAT עובד עם <strong>מספרים שלמים בלבד</strong> — לא עשרוניים.
          לכן לפני שמעבירים לו את הנתונים, מחשבים מראש שני קבועים שלמים לכל חייל:
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse" style={{ minWidth: "420px" }}>
            <thead>
              <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                <th className="text-right py-1 pr-2 font-medium w-36">שם</th>
                <th className="text-right py-1 pr-2 font-medium w-48">נוסחה</th>
                <th className="text-right py-1 font-medium">משמעות</th>
              </tr>
            </thead>
            <tbody className="text-gray-700 dark:text-gray-300">
              {[
                {
                  name: "EFFORT_SCALE",
                  formula: "10⁹",
                  meaning: "גורם קנה-מידה. ממיר עשרוניים לשלמים בלי אובדן דיוק.",
                },
                {
                  name: "effort_offset",
                  formula: "int(effort_score × EFFORT_SCALE)",
                  meaning: "ניקוד העומס ההיסטורי כשלם קבוע. לא משתנה בזמן הפתרון.",
                },
                {
                  name: "unit_score_milli",
                  formula: "Σ block_score(d) × 1000 לכל תורנויות החלון",
                  meaning: "סך ניקוד כל התורנויות שהפותר יכול לשבץ — קבוע.",
                },
                {
                  name: "C_over_D",
                  formula: "C / D",
                  meaning: "כמה מהמשקל הכולל מיוחס לסיבוב הנוכחי. גבוה לחיילים חדשים (W קטן), נמוך לוותיקים.",
                },
                {
                  name: "effort_per_milli",
                  formula: "int(C_over_D / unit_score_milli × EFFORT_SCALE)",
                  meaning: "כמה כל מילי-ניקוד אחד של תורנות מזיז את עומס החייל. קבוע — מחושב לפני הפתרון.",
                },
              ].map(({ name, formula, meaning }) => (
                <tr key={name} className="border-b border-gray-100 dark:border-gray-700">
                  <td className="py-1.5 pr-2 font-mono text-indigo-700 dark:text-indigo-300">{name}</td>
                  <td className="py-1.5 pr-2 font-mono text-gray-600 dark:text-gray-400">{formula}</td>
                  <td className="py-1.5">{meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs space-y-1">
          <p className="font-medium text-indigo-800 dark:text-indigo-200">💡 האינרציה של הוותיק</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            לחייל ותיק עם W=8 יש C_over_D = 1/(8+1) ≈ 0.11.
            לחייל חדש עם W=0 יש C_over_D = 1/(0+1) = 1.0.
            כלומר: אותה תורנות בדיוק מזיזה את ניקוד החדש פי 9 יותר מאשר את הוותיק.
            לחייל ותיק יש &quot;עמידות&quot; גבוהה יותר לשינויים — צריך הרבה תורנויות כדי להזיז אותו.
          </p>
        </div>
      </section>

      {/* ── Section 4: projected_effort ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🎯 הניקוד הצפוי — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">projected_effort</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          בתוך הפותר, לכל חייל נבנית <strong>ביטוי לינארי</strong> שמחשב מה יהיה ניקוד העומס שלו
          לאחר שיבוץ:
        </p>

        <pre className="font-mono text-xs bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto leading-relaxed text-gray-800 dark:text-gray-200 whitespace-pre">{`projected_effort[i] =
    effort_offset[i]
  + effort_per_milli[i] × Σ( block_score(d) × x[d,i] )`}</pre>

        <div className="space-y-2 text-xs text-gray-700 dark:text-gray-300">
          {[
            {
              term: "x[d, i]",
              desc: "משתנה בינארי של הפותר: 1 אם תורנות d שובצה לחייל i, 0 אחרת. זה מה שהפותר בוחר.",
            },
            {
              term: "block_score(d)",
              desc: "ניקוד תורנות d (משך ימים × משקל סוג התורנות), ביחידות מילי. קבוע.",
            },
            {
              term: "Σ block_score(d) × x[d,i]",
              desc: "סך הניקוד של כל התורנויות ששובצו לחייל i. ביטוי לינארי — סכום של קבועים כפול משתנים.",
            },
          ].map(({ term, desc }) => (
            <div key={term} className="flex gap-2 bg-gray-50 dark:bg-gray-700 rounded p-2 border border-gray-200 dark:border-gray-600">
              <code className="shrink-0 text-indigo-700 dark:text-indigo-300 font-mono">{term}</code>
              <span>{desc}</span>
            </div>
          ))}
        </div>

        <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800 text-xs space-y-1">
          <p className="font-medium text-green-800 dark:text-green-200">✅ למה זה חשוב — לינאריות</p>
          <p className="text-green-700 dark:text-green-300">
            <code>effort_per_milli</code> ו-<code>block_score(d)</code> הם קבועים שלמים — רק <code>x[d,i]</code> הם משתנים.
            הביטוי כולו לינארי לחלוטין — אין חילוק, אין ריבועים.
            CP-SAT פותר בעיות לינאריות מהר מאוד.
          </p>
          <p className="text-green-700 dark:text-green-300 mt-1">
            בגרסה הקודמת, הניקוד חולק ב-<code>active_days</code> בתוך הפותר — אילוץ חילוק שהאט את הפתרון.
            כאן, החילוק מתבצע פעם אחת מחוץ לפותר (בחישוב <code>effort_per_milli</code>) — וזה מה שהופך את הגישה לסקלאבילית.
          </p>
        </div>
      </section>

    </div>
  );
}

export default function HelpModal({ onClose, gimelimEnabled = false }: Props) {
  const [activeTab, setActiveTab] = useState("swaps");
  const TABS = buildTabs(gimelimEnabled);

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b dark:border-gray-600" dir="rtl">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">מדריך המערכת</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b dark:border-gray-600 px-2 pt-1 overflow-x-auto" dir="rtl">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === "swaps" && <SwapsTab />}
          {activeTab === "algorithm" && <AlgorithmTab />}
          {activeTab === "fairness" && <FairnessTab />}
          {activeTab === "deep" && <DeepDiveTab />}
          {activeTab === "gimelim" && <GimelimTab />}
        </div>
      </div>
    </div>
  );
}

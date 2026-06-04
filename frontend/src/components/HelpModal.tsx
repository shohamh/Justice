import { useState } from "react";

interface Props {
  onClose: () => void;
}

const TABS = [
  { id: "swaps", label: "🔄 החלפות" },
  { id: "algorithm", label: "⚙️ האלגוריתם" },
  { id: "fairness", label: "⚖️ הוגנות ושקיפות" },
];

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
      <h3 className="text-base font-semibold text-indigo-700">איך עובדות החלפות?</h3>
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
      <h3 className="text-base font-semibold text-indigo-700">איך האלגוריתם מחלק תורנויות?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        האלגוריתם מחלק תורנויות באופן אוטומטי ועובר על כל משמרת לפי הסדר:
      </p>

      {/* Flow diagram */}
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="📋" text="משמרת ממתינה לשיבוץ" color="gray" />
        <Arrow />
        <FlowStep icon="🔍" text="מוצאים את כל החיילים הכשירים" color="indigo" />
        <Arrow />
        <FlowStep icon="🚫" text="מסננים: פטורים, אילוצים, דרישות המשמרת" color="amber" />
        <Arrow />
        <FlowStep icon="📊" text="ממיינים לפי ניקוד מנורמל — הנמוך ביותר קודם" color="blue" />
        <Arrow />
        <FlowStep icon="🎲" text="מגרילים מתוך קבוצת המועמדים העליונים" color="indigo" />
        <Arrow />
        <FlowStep icon="✅" text="שיבוץ בוצע!" color="green" />
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 מה האלגוריתם לוקח בחשבון?</p>
        {[
          { icon: "📊", title: "ניקוד מנורמל", desc: "מי שעשה פחות תורנויות ביחס לאחרים מקבל עדיפות. ראו הסבר מלא בטאב הוגנות." },
          { icon: "🚫", title: "פטורים ואילוצים", desc: "חיילים עם פטור רלוונטי מוסרים. אילוצים אישיים (תאריכים) גם מסננים." },
          { icon: "🎖️", title: "דרישות המשמרת", desc: "חוגרים/קצינים, בה\"ד 1, מין — כל משמרת מגדירה את הדרישות שלה." },
          { icon: "🔢", title: "מכסת עתודאים", desc: "האלגוריתם שובץ גם עתודאים שיוקפצו לכשהזכאי לא יוכל להגיע." },
          { icon: "🎲", title: "אקראיות מבוקרת", desc: "כשיש כמה מועמדים בעלי ניקוד דומה — מגרילים ביניהם לשוויון טוב יותר לאורך זמן." },
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
          נניח שיש 3 חיילים: דן (ניקוד מנורמל 0.8), יעל (1.0), ורוני (1.4).
          משמרת חדשה צריכה מישהו עם תג "חוגרים". דן ורוני מתאימים — יעל פטורה.
          האלגוריתם ממיין לפי ניקוד: דן (0.8) ← קודם.
          אם K=3 (עומק הגרלה), הוא מגריל מתוך שני המועמדים: סיכוי גבוה יותר לדן.
        </p>
        <div className="grid grid-cols-3 gap-2 text-xs text-center">
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן</p>
            <p>ניקוד: 0.8</p>
            <p className="text-green-600">⬆ עדיפות גבוהה</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל</p>
            <p>ניקוד: 1.0</p>
            <p className="text-gray-500">✗ פטור חל</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-orange-700 dark:text-orange-300">רוני</p>
            <p>ניקוד: 1.4</p>
            <p className="text-orange-600">⬇ עדיפות נמוכה</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function FairnessTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700">הוגנות ושקיפות</h3>
      <p className="text-gray-700 dark:text-gray-300">
        המערכת מספקת שקיפות מלאה — כל חייל יכול לראות את הניקוד שלו ושל שאר חברי היחידה בדף השקיפות.
      </p>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📊 מהו ניקוד מנורמל?</p>
        <p className="text-indigo-700 dark:text-indigo-300">
          הניקוד המנורמל משווה את העומס שנשאת ביחס לממוצע היחידה, תוך התחשבות בכמה זמן כל חייל משרת.
        </p>

        {/* Formula */}
        <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700">
          <div className="flex items-center justify-center gap-2 text-sm flex-wrap">
            <div className="bg-indigo-100 rounded px-2 py-1 text-indigo-800 font-medium">הניקוד שלך ÷ הימים הפעילים שלך</div>
            <div className="text-gray-500 font-bold">÷</div>
            <div className="bg-purple-100 rounded px-2 py-1 text-purple-800 font-medium">ממוצע יחידה ÷ ממוצע ימים פעילים</div>
          </div>
        </div>

        {/* Score scale cards with person indicators */}
        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <div className="bg-orange-100 border border-orange-300 rounded-lg p-2 space-y-0.5">
            <p className="text-lg font-bold text-orange-700 flex items-end justify-center gap-1">
              <span className="flex flex-col items-center leading-none">
                <span>👤</span>
                <span className="text-[8px] text-orange-400 font-normal mt-0.5">את/ה כאן</span>
              </span>
              <span>{"< 1"}</span>
            </p>
            <p className="text-orange-700 font-medium">עשית פחות מהממוצע</p>
            <p className="text-orange-600">תשובץ יותר בעתיד</p>
          </div>
          <div className="bg-blue-100 border border-blue-300 rounded-lg p-2 space-y-0.5">
            <p className="text-lg font-bold text-blue-700">= 1</p>
            <div className="h-4" />
            <p className="text-blue-700 font-medium">בדיוק כמו הממוצע</p>
            <p className="text-blue-600">מצב אידיאלי</p>
          </div>
          <div className="bg-green-100 border border-green-300 rounded-lg p-2 space-y-0.5">
            <p className="text-lg font-bold text-green-700 flex items-end justify-center gap-1">
              <span className="flex flex-col items-center leading-none">
                <span>👤</span>
                <span className="text-[8px] text-green-400 font-normal mt-0.5">את/ה כאן</span>
              </span>
              <span>{"> 1"}</span>
            </p>
            <p className="text-green-700 font-medium">עשית יותר מהממוצע</p>
            <p className="text-green-600">תשובץ פחות בעתיד</p>
          </div>
        </div>

        {/* Gradient bar */}
        <div className="space-y-1">
          <div className="h-3 rounded-full bg-gradient-to-l from-green-300 via-blue-300 to-orange-300" />
          <div className="grid grid-cols-3 text-center text-xs text-gray-400">
            <span>ניקוד נמוך</span>
            <span className="text-blue-600 font-medium">= 1</span>
            <span>ניקוד גבוה</span>
          </div>
        </div>
      </div>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📝 דוגמה: חישוב ניקוד מנורמל</p>
        <div className="text-xs space-y-2 text-indigo-700">
          <p>נניח יחידה עם 3 חיילים לאחר 60 יום:</p>
          <div className="overflow-x-auto">
            <table className="w-full text-center border-collapse text-xs">
              <thead>
                <tr className="bg-indigo-100 dark:bg-indigo-900">
                  <th className="p-1 border border-indigo-200">חייל</th>
                  <th className="p-1 border border-indigo-200">ניקוד מצטבר</th>
                  <th className="p-1 border border-indigo-200">ימים פעילים</th>
                  <th className="p-1 border border-indigo-200">ניקוד מנורמל</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="p-1 border border-indigo-200">דן</td>
                  <td className="p-1 border border-indigo-200">30</td>
                  <td className="p-1 border border-indigo-200">60</td>
                  <td className="p-1 border border-indigo-200 font-bold text-orange-600">0.75</td>
                </tr>
                <tr className="bg-white dark:bg-gray-800">
                  <td className="p-1 border border-indigo-200">יעל</td>
                  <td className="p-1 border border-indigo-200">40</td>
                  <td className="p-1 border border-indigo-200">60</td>
                  <td className="p-1 border border-indigo-200 font-bold text-blue-600">1.00</td>
                </tr>
                <tr>
                  <td className="p-1 border border-indigo-200">רוני</td>
                  <td className="p-1 border border-indigo-200">50</td>
                  <td className="p-1 border border-indigo-200">60</td>
                  <td className="p-1 border border-indigo-200 font-bold text-green-600">1.25</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p>ממוצע ניקוד: (30+40+50)÷3 = 40. ממוצע ימים: 60. ניקוד מנורמל יעל: (40÷60)÷(40÷60) = <strong>1.00</strong>.</p>
          <p>דן עשה פחות (0.75) → <strong>יקבל תורנות הבאה</strong>. רוני עשה יותר (1.25) → <strong>יחכה</strong>.</p>
        </div>
      </div>

      <div className="bg-amber-50 dark:bg-amber-950 rounded-xl p-4 border border-amber-200 dark:border-amber-800 space-y-2">
        <p className="font-semibold text-amber-800 dark:text-amber-200">🚩 מתי לפנות למפקד?</p>
        <p className="text-amber-700 dark:text-amber-300">בדקו בדף השקיפות. אם אתם רואים אחד מאלה — כדאי לפנות:</p>
        <div className="space-y-2">
          {[
            { n: "❶", text: "הניקוד שלכם גבוה משמעותית (מעל 1.3) ואתם עדיין מקבלים הרבה תורנויות — ייתכן שגיאה באלגוריתם." },
            { n: "❷", text: "חייל ספציפי תמיד בעל ניקוד נמוך מאוד (מתחת ל-0.7) — ייתכן שיש פטור/אילוץ קבוע שאינו מוצדק." },
            { n: "❸", text: "הניקוד שלכם לא השתנה למרות ביצוע תורנויות — ייתכן שגיאה בשיבוץ." },
          ].map(({ n, text }) => (
            <div key={n} className="flex gap-2 text-amber-700 dark:text-amber-300">
              <span className="font-bold flex-shrink-0">{n}</span>
              <span>{text}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
        <p className="font-medium text-gray-700 dark:text-gray-200 mb-1">🔍 איפה לבדוק?</p>
        <p className="text-gray-600 dark:text-gray-300">
          עברו ל<b>דף השקיפות</b> (מהתפריט: שקיפות) — שם תמצאו את הניקוד של כל חיילי היחידה לצד שלכם, ממוין ומסנן.
        </p>
      </div>
    </div>
  );
}

export default function HelpModal({ onClose }: Props) {
  const [activeTab, setActiveTab] = useState("swaps");

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
        <div className="flex border-b dark:border-gray-600 px-2 pt-1" dir="rtl">
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
        </div>
      </div>
    </div>
  );
}

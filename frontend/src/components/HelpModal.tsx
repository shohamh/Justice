import { useState } from "react";

interface Props {
  onClose: () => void;
  gimelimEnabled?: boolean;
}

function buildTabs(gimelimEnabled: boolean) {
  const tabs = [
    { id: "swaps", label: "🔄 החלפות" },
    { id: "algorithm", label: "⚙️ האלגוריתם" },
    { id: "fairness", label: "⚖️ הוגנות ושקיפות" },
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
        </div>

        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
          <p className="font-medium mb-1">🔑 למה זה פותר את בעיית הוותיקות?</p>
          <p>אם ביחידה היו מעט תורנויות לפני 5 שנים — כולם קיבלו חלק קטן. זה לא פוגע בחייל ותיק, כי היחס (חלק/כלל) נשאר הוגן בכל רבעון. חייל חדש מושווה <em>רק לתקופה שהוא שירת בה</em>.</p>
        </div>
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
          { icon: "📊", title: "דף השקיפות", desc: "כל חייל רואה את העומס הרבעוני שלו ושל שאר חברי היחידה — כולל טבלה שניתן למיין לפי עומס." },
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
          {activeTab === "gimelim" && <GimelimTab />}
        </div>
      </div>
    </div>
  );
}

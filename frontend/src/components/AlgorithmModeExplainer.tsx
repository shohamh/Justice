export default function AlgorithmModeExplainer() {
  return (
    <div className="space-y-3">
      <div className="bg-amber-50 dark:bg-amber-950 rounded p-3">
        <p className="font-semibold text-amber-700 dark:text-amber-300 mb-1">מצב טיוטה (ברירת מחדל)</p>
        <p className="text-gray-600 dark:text-gray-400">
          תוצאות האלגוריתם נשמרות כטיוטה בלבד. החיילים לא רואים שינוי. אפשר לסקור את השיבוצים המוצעים,
          לדחות חלקם, ולפרסם רק אחרי אישור. מומלץ לשימוש רגיל.
        </p>
      </div>

      <div className="bg-green-50 dark:bg-green-950 rounded p-3">
        <p className="font-semibold text-green-700 dark:text-green-300 mb-1">מצב פרסום ישיר</p>
        <p className="text-gray-600 dark:text-gray-400">
          תוצאות האלגוריתם מתפרסמות מיד ללא שלב ביניים. החיילים רואים את השיבוצים החדשים מיידית.
          השתמש רק כאשר אתה בטוח בתוצאות מראש.
        </p>
      </div>
    </div>
  );
}

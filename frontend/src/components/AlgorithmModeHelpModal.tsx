import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  onClose: () => void;
}

export default function AlgorithmModeHelpModal({ onClose }: Props) {
  useModalBackClose(onClose);
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 space-y-4 text-sm"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold">מצבי הרצה</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

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

        <button
          className="w-full border border-gray-300 dark:border-gray-600 py-2 rounded text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
          onClick={onClose}
        >
          סגור
        </button>
      </div>
    </div>
  );
}

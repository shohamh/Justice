import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { usePublicSettings } from "../hooks/usePublicSettings";

export default function HeaderSearch() {
  const { t } = useTranslation();
  useAuth();
  usePublicSettings();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function openPanel() {
    setOpen(true);
  }

  function closePanel() {
    setOpen(false);
    setQuery("");
  }

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        openPanel();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <button
        onClick={openPanel}
        aria-label={t("search.placeholder")}
        className="text-gray-500 hover:text-indigo-600"
      >
        <Search size={22} />
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/30" onClick={closePanel}>
          <div
            className="bg-white dark:bg-gray-800 mx-auto mt-16 max-w-xl rounded-lg shadow-lg p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              role="combobox"
              aria-expanded={open}
              aria-label={t("search.placeholder")}
              placeholder={t("search.placeholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") closePanel();
              }}
              className="w-full border rounded px-3 py-2 bg-transparent dark:text-gray-100"
            />
            {query.trim() === "" ? null : (
              <div className="mt-2 text-sm text-gray-500">{t("search.no_results")}</div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

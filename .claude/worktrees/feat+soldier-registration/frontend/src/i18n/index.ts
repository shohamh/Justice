import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import he from "./he.json";

i18n
  .use(initReactI18next)
  .init({
    resources: { he: { translation: he } },
    lng: "he",
    fallbackLng: "he",
    interpolation: { escapeValue: false },
  });

export default i18n;

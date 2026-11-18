import { translate } from "./translation.mjs";
import { createContext, useContext, useEffect, useState } from "react";
import { Languages } from "lucide-react";
import french from "./fr.json";

export type Language = "en" | "fr";
const key = "cortex-language";
let current: Language = "fr";
try {
  current = localStorage.getItem(key) === "en" ? "en" : "fr";
} catch {
  /* Storage can be disabled. */
}
const dictionary: Record<string, string> = french;
export const getLocale = () => (current === "fr" ? "fr-FR" : "en-GB");
export function t(value: string): string {
  return translate(value, current, dictionary);
}
const LanguageContext = createContext<{
  language: Language;
  setLanguage: (language: Language) => void;
}>({ language: current, setLanguage: () => {} });
export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setValue] = useState<Language>(current);
  const setLanguage = (language: Language) => {
    current = language;
    setValue(language);
    try {
      localStorage.setItem(key, language);
    } catch {
      /* Continue with this session. */
    }
  };
  useEffect(() => {
    document.documentElement.lang = language;
    document.title =
      language === "fr" ? "Cortex School · Espace scolaire" : "Cortex School";
  }, [language]);
  return (
    <LanguageContext.Provider value={{ language, setLanguage }}>
      {children}
    </LanguageContext.Provider>
  );
}
export const useLanguage = () => useContext(LanguageContext);
export function LanguageSwitch() {
  const { language, setLanguage } = useLanguage();
  return (
    <label className="language-switch">
      <Languages size={15} />
      <span className="sr-only">{t("Language")}</span>
      <select
        aria-label={t("Language")}
        value={language}
        onChange={(e) => setLanguage(e.target.value as Language)}
      >
        <option value="fr">Français</option>
        <option value="en">English</option>
      </select>
    </label>
  );
}

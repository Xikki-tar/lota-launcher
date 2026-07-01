import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from "react";
import { useBackend } from "./BackendContext";

type Strings = Record<string, string>;

interface I18nCtx {
  t: (key: string, fallback?: string) => string;
  refresh: () => void;
  language: string;
}

const I18nContext = createContext<I18nCtx>({
  t: (key, fallback) => fallback ?? key,
  refresh: () => {},
  language: "Русский",
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const port = useBackend();
  const [strings, setStrings] = useState<Strings>({});
  const [language, setLanguage] = useState("Русский");

  const load = useCallback(async () => {
    if (!port) return;
    try {
      const res = await fetch(`http://127.0.0.1:${port}/i18n`);
      const data = await res.json();
      setStrings(data.strings ?? {});
      setLanguage(data.language ?? "Русский");
    } catch { /* ignore */ }
  }, [port]);

  useEffect(() => { load(); }, [load]);

  const t = useCallback((key: string, fallback?: string): string => {
    return strings[key] ?? fallback ?? key;
  }, [strings]);

  return (
    <I18nContext.Provider value={{ t, refresh: load, language }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

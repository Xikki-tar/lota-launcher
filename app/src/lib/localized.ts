export type Localized = { en?: string; ru?: string; uk?: string; [k: string]: string | undefined };

export type LangCode = "ru" | "uk" | "en";

export function langCode(language: string): LangCode {
  if (language === "Українська") return "uk";
  if (language === "English") return "en";
  return "ru";
}

export function loc(v: string | Localized | undefined, lang: LangCode = "ru"): string {
  if (!v) return "";
  if (typeof v === "string") return v;
  const candidate = v[lang] ?? v.ru ?? v.en ?? v.uk ?? Object.values(v).find(Boolean);
  if (candidate === undefined) return "";
  if (typeof candidate === "string") return candidate;
  return loc(candidate as Localized, lang);
}

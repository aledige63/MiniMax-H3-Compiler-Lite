import { captureStaticLabels, setUiLanguage } from "./i18n.js";

export const appearanceKey = "minimax.studio.appearance";

export function readAppearance(win) {
  let settings;
  try { settings = JSON.parse(win.localStorage.getItem(appearanceKey)); } catch {}
  return {
    theme: settings?.theme === "dark" ? "dark" : "light",
    language: settings?.language === "en" ? "en" : "it"
  };
}

export function createAppearance(doc, win, languageChanged) {
  const settings = readAppearance(win);
  const renderStatic = captureStaticLabels(doc);
  const root = doc.documentElement;
  const theme = doc.getElementById("color-scheme");
  const language = doc.getElementById("ui-language");
  function applyLanguage() {
    root.lang = settings.language;
    setUiLanguage(settings.language);
    renderStatic();
  }
  function save() {
    try { win.localStorage.setItem(appearanceKey, JSON.stringify(settings)); } catch {}
  }
  root.dataset.theme = theme.value = settings.theme;
  language.value = settings.language;
  applyLanguage();
  theme.addEventListener("change", () => {
    root.dataset.theme = settings.theme = theme.value === "dark" ? "dark" : "light";
    save();
  });
  language.addEventListener("change", () => {
    settings.language = language.value === "en" ? "en" : "it";
    applyLanguage();
    save();
    languageChanged();
  });
}

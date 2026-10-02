export const THEME_STORAGE_KEY = "ga-theme";
export const THEME_CHANGE_EVENT = "ga-theme-change";
export const THEME_CHOICES = ["light", "dark", "system"];
export const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function normalizeThemeChoice(value) {
  return THEME_CHOICES.includes(value) ? value : "system";
}

export function resolveTheme(choice, prefersDark) {
  const normalized = normalizeThemeChoice(choice);
  if (normalized === "system") {
    return prefersDark ? "dark" : "light";
  }
  return normalized;
}

// Inlined into <head> so the stored theme is applied before first paint.
export const THEME_INIT_SCRIPT = `(function(){try{var c=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(c!=="light"&&c!=="dark")c="system";var d=c==="dark"||(c==="system"&&window.matchMedia(${JSON.stringify(
  DARK_MEDIA_QUERY,
)}).matches);document.documentElement.dataset.theme=d?"dark":"light";}catch(e){}})();`;

"use client";

import { useEffect, useSyncExternalStore } from "react";

import {
  DARK_MEDIA_QUERY,
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  normalizeThemeChoice,
  resolveTheme,
} from "../lib/theme";
import { MonitorIcon, MoonIcon, SunIcon } from "./icons";

const OPTIONS = [
  { value: "light", label: "Light theme", Icon: SunIcon },
  { value: "dark", label: "Dark theme", Icon: MoonIcon },
  { value: "system", label: "Match system theme", Icon: MonitorIcon },
];

function subscribe(onChange) {
  window.addEventListener("storage", onChange);
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(THEME_CHANGE_EVENT, onChange);
  };
}

function readChoice() {
  try {
    return normalizeThemeChoice(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function applyChoice(choice) {
  const prefersDark = window.matchMedia(DARK_MEDIA_QUERY).matches;
  document.documentElement.dataset.theme = resolveTheme(choice, prefersDark);
}

export default function ThemeToggle() {
  const choice = useSyncExternalStore(subscribe, readChoice, () => "system");

  useEffect(() => {
    function onStorage(event) {
      if (event.key === THEME_STORAGE_KEY) {
        applyChoice(readChoice());
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (choice !== "system") {
      return undefined;
    }
    const media = window.matchMedia(DARK_MEDIA_QUERY);
    const onMediaChange = () => applyChoice("system");
    media.addEventListener("change", onMediaChange);
    return () => media.removeEventListener("change", onMediaChange);
  }, [choice]);

  function select(next) {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
    applyChoice(next);
    window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
  }

  return (
    <div
      role="group"
      aria-label="Color theme"
      className="inline-flex gap-0.5 rounded-lg border border-line bg-surface-muted p-0.5"
    >
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.label}
          aria-label={option.label}
          aria-pressed={choice === option.value}
          onClick={() => select(option.value)}
          className={`grid size-8 place-items-center rounded-md transition ${
            choice === option.value
              ? "bg-surface text-fg shadow-xs"
              : "text-fg-muted hover:text-fg-secondary"
          }`}
        >
          <option.Icon />
        </button>
      ))}
    </div>
  );
}

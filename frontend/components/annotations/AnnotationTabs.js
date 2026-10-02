"use client";

import { useRef } from "react";

const KEY_OFFSETS = { ArrowRight: 1, ArrowLeft: -1 };

export default function AnnotationTabs({ tabs, active, onChange }) {
  const tabRefs = useRef({});

  function onKeyDown(event, index) {
    let next = null;
    if (event.key in KEY_OFFSETS) next = (index + KEY_OFFSETS[event.key] + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    onChange(tabs[next].id);
    tabRefs.current[tabs[next].id]?.focus();
  }

  return (
    <div role="tablist" aria-label="Annotation sections" className="mt-6 flex gap-6 overflow-x-auto border-b border-line">
      {tabs.map((tab, index) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              tabRefs.current[tab.id] = node;
            }}
            type="button"
            role="tab"
            id={`annotation-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`annotation-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-1 pb-3 text-sm font-semibold transition ${
              selected
                ? "border-brand-fg text-brand-fg"
                : "border-transparent text-fg-muted hover:border-line-strong hover:text-fg-secondary"
            }`}
          >
            {tab.label}
            {tab.count != null ? (
              <span
                className={`rounded-full px-2 text-xs font-medium leading-[18px] ${
                  selected ? "bg-brand-tint text-brand-fg" : "bg-surface-sunken text-fg-secondary"
                }`}
              >
                {tab.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

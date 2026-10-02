"use client";

import Link from "next/link";
import { useEffect, useRef, useSyncExternalStore } from "react";

import { SearchIcon } from "../icons";

const subscribeNever = () => () => {};
const isApplePlatform = () => /Mac|iPhone|iPad/.test(navigator.platform);

function versionLabel(match) {
  const count = (match.version_count || 0) + 1;
  return `${count} version${count === 1 ? "" : "s"}`;
}

export default function ResultsRail({
  query,
  onQueryChange,
  onSearch,
  isSearching,
  message,
  searchedQuery,
  totalCount,
  organisms,
  organism,
  onOrganismChange,
  matches,
  hiddenCount,
  onShowAll,
  selectedId,
  onSelect,
}) {
  const inputRef = useRef(null);
  const apple = useSyncExternalStore(subscribeNever, isApplePlatform, () => true);

  useEffect(() => {
    function onKeyDown(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <aside className="flex flex-col border-b border-line bg-surface lg:sticky lg:top-16 lg:h-[calc(100vh-4rem)] lg:border-r lg:border-b-0">
      <div className="border-b border-line px-4 pt-5 pb-3">
        <form
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            onSearch();
          }}
        >
          <label htmlFor="annotation-search" className="sr-only">
            Search annotations
          </label>
          <div className="flex h-10 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-fg-muted shadow-xs focus-within:border-brand-line focus-within:ring-4 focus-within:ring-focus-ring">
            <SearchIcon size={18} />
            <input
              id="annotation-search"
              ref={inputRef}
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Locus, gene name, or term"
              className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
            />
            {isSearching ? (
              <span className="text-xs text-fg-muted">Searching…</span>
            ) : (
              <kbd className="rounded border border-line px-1 font-sans text-xs text-fg-subtle">
                {apple ? "⌘K" : "Ctrl K"}
              </kbd>
            )}
          </div>
        </form>
        <p className={message ? "mt-3 text-sm text-warning-fg" : "sr-only"} role="status">
          {message}
        </p>
        {searchedQuery ? (
          <div className="mt-3 flex items-center justify-between gap-2 text-xs text-fg-muted">
            <span>
              {totalCount} result{totalCount === 1 ? "" : "s"}
            </span>
            {organisms.length > 1 ? (
              <label className="flex min-w-0 items-center">
                <span className="sr-only">Filter by organism</span>
                <select
                  value={organism}
                  onChange={(event) => onOrganismChange(event.target.value)}
                  className="max-w-44 truncate bg-transparent font-semibold text-fg-secondary outline-none"
                >
                  <option value="">All organisms</option>
                  {organisms.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="max-h-80 overflow-y-auto p-2 lg:max-h-none lg:flex-1">
        {!searchedQuery ? (
          <p className="px-3 py-6 text-sm text-fg-muted">
            Search by locus, gene name, or organism to find stored annotations.
          </p>
        ) : null}

        {searchedQuery && totalCount === 0 && !isSearching ? (
          <div className="px-3 py-6">
            <p className="text-sm font-semibold text-fg">No annotation found</p>
            <p className="mt-1 text-sm text-fg-muted">
              Nothing stored matches “{searchedQuery}” yet. Submit it as a new job and come back when it
              finishes.
            </p>
            <Link
              href={`/jobs?locus=${encodeURIComponent(searchedQuery)}`}
              className="workbench-button workbench-button-primary mt-4"
            >
              Submit this gene for annotation
            </Link>
          </div>
        ) : null}

        <ul className="grid grid-cols-1 gap-0.5">
          {matches.map((match) => {
            const isSelected = match.id === selectedId;
            return (
              <li key={match.id}>
                <button
                  type="button"
                  onClick={() => onSelect(match.id)}
                  aria-current={isSelected ? "true" : undefined}
                  className={`block w-full rounded-lg border px-3 py-2.5 text-left transition ${
                    isSelected ? "border-brand-line bg-brand-tint" : "border-transparent hover:bg-surface-muted"
                  }`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate font-semibold text-fg">
                      {match.gene_name || match.normalized_locus}
                    </span>
                    <span className="shrink-0 text-xs text-fg-muted">{versionLabel(match)}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-fg-muted">
                    <span className="font-mono text-fg-secondary">{match.normalized_locus}</span> ·{" "}
                    {match.canonical_name}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {hiddenCount > 0 ? (
          <button
            type="button"
            onClick={onShowAll}
            className="mt-1 w-full rounded-lg px-3 py-2 text-left text-sm font-semibold text-brand-fg hover:bg-surface-muted"
          >
            Show {hiddenCount} more
          </button>
        ) : null}
      </div>

      <p className="mt-auto hidden border-t border-line px-4 py-3 text-xs text-fg-muted lg:block">
        Not finding a gene?{" "}
        <Link href="/jobs" className="font-semibold text-brand-fg">
          Submit it for annotation →
        </Link>
      </p>
    </aside>
  );
}

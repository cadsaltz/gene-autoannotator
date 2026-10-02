"use client";

import { motion } from "framer-motion";
import { useRef, useState } from "react";

import {
  generateRegexFromDescription,
  generateRegexFromExamples,
} from "../lib/api";

const TABS = [
  { id: "examples", label: "From examples" },
  { id: "description", label: "From description" },
];

function GenerateButtonLabel({ isGenerating, idleLabel }) {
  if (!isGenerating) {
    return idleLabel;
  }
  return (
    <span className="inline-flex items-center gap-2">
      <motion.span
        aria-hidden="true"
        className="inline-block size-4 rounded-full border-2 border-white/40 border-t-white"
        animate={{ rotate: 360 }}
        transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
      />
      Generating...
    </span>
  );
}

export default function RegexHelper({ onApply }) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("examples");
  const [examplesText, setExamplesText] = useState("");
  const [description, setDescription] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  // Identifies the latest request so a slow response from a previous tab or
  // click cannot overwrite newer state after the user has moved on.
  const requestRef = useRef(0);

  function resetOutput() {
    setResult(null);
    setError("");
  }

  function cancelPendingRequest() {
    requestRef.current += 1;
  }

  async function runGenerate(validationError, call) {
    resetOutput();
    if (validationError) {
      setError(validationError);
      return;
    }
    const token = (requestRef.current += 1);
    setIsGenerating(true);
    try {
      const payload = await call();
      if (requestRef.current === token) {
        setResult(payload);
      }
    } catch (err) {
      if (requestRef.current === token) {
        setError(err.message);
      }
    } finally {
      if (requestRef.current === token) {
        setIsGenerating(false);
      }
    }
  }

  function handleGenerateExamples() {
    const examples = examplesText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    return runGenerate(
      examples.length === 0 ? "Enter at least one example locus." : "",
      () => generateRegexFromExamples({ examples }),
    );
  }

  function handleGenerateDescription() {
    return runGenerate(
      description.trim().length === 0 ? "Describe the locus format first." : "",
      () => generateRegexFromDescription({ description }),
    );
  }

  function handleApply() {
    if (result?.regex && typeof onApply === "function") {
      onApply(result.regex);
    }
  }

  return (
    <div className="rounded-xl border border-dashed workbench-border bg-surface p-4">
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        aria-expanded={isOpen}
        className="workbench-button workbench-button-secondary cursor-pointer"
      >
        {isOpen ? "Hide regex helper" : "Don't know the exact regex?"}
      </button>

      {isOpen ? (
        <div className="mt-4 grid gap-4">
          <div className="flex gap-2">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  cancelPendingRequest();
                  setActiveTab(tab.id);
                  resetOutput();
                  setIsGenerating(false);
                }}
                className={`workbench-button cursor-pointer ${
                  activeTab === tab.id
                    ? "workbench-button-primary"
                    : "workbench-button-secondary"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === "examples" ? (
            <div className="grid gap-2 text-sm font-medium">
              <label className="grid gap-2">
                Example loci (one per line)
                <textarea
                  value={examplesText}
                  onChange={(event) => setExamplesText(event.target.value)}
                  className="workbench-input min-h-28"
                  placeholder={"Rv1000\nRv2070c\nRv3415A"}
                />
              </label>
              <button
                type="button"
                onClick={handleGenerateExamples}
                disabled={isGenerating}
                className="workbench-button workbench-button-primary cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              >
                <GenerateButtonLabel
                  isGenerating={isGenerating}
                  idleLabel="Generate from examples"
                />
              </button>
              <span className="workbench-muted text-xs">
                Three or more varied examples give the best results.
              </span>
            </div>
          ) : (
            <div className="grid gap-2 text-sm font-medium">
              <label className="grid gap-2">
                Describe the locus format
                <input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  className="workbench-input"
                  placeholder="Rv followed by 4 digits, then a c, A, or nothing"
                />
              </label>
              <button
                type="button"
                onClick={handleGenerateDescription}
                disabled={isGenerating}
                className="workbench-button workbench-button-primary cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              >
                <GenerateButtonLabel
                  isGenerating={isGenerating}
                  idleLabel="Generate from description"
                />
              </button>
              <span className="workbench-muted text-xs">
                Uses a local model. If it is unavailable, try the examples tab.
              </span>
            </div>
          )}

          {error ? (
            <p
              role="alert"
              className="workbench-amber-bg rounded-xl border workbench-border p-3 text-sm text-warning-fg"
            >
              {error}
            </p>
          ) : null}

          {result?.regex ? (
            <div className="grid gap-3 rounded-xl border workbench-border bg-surface p-4">
              <code className="break-all rounded bg-surface-sunken px-2 py-1 text-sm">
                {result.regex}
              </code>
              {result.explanation ? (
                <p className="workbench-muted text-sm leading-6">
                  {result.explanation}
                </p>
              ) : null}
              {result.matched?.length ? (
                <ul className="grid gap-1 text-sm">
                  {result.matched.map((entry) => (
                    <li key={entry.value} className="flex items-center gap-2">
                      <span aria-hidden="true">{entry.ok ? "✓" : "✗"}</span>
                      <span className="sr-only">
                        {entry.ok ? "matches" : "does not match"}
                      </span>
                      <code>{entry.value}</code>
                    </li>
                  ))}
                </ul>
              ) : null}
              <button
                type="button"
                onClick={handleApply}
                className="workbench-button workbench-button-primary cursor-pointer"
              >
                Use this regex
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

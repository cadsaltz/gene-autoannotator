"use client";

import {
  BUILTIN_OPTIONAL_FIELD_TEMPLATES,
  REQUIRED_DEFAULT_FIELDS,
  canEnableOrthologAllowed,
  createEmptyCustomField,
  customFieldFromTemplate,
} from "../lib/profileStore";

const FIELD_TYPES = [
  { value: "string", label: "Text" },
  { value: "boolean", label: "True / false / null" },
  { value: "array:string", label: "List of text values" },
];

const INFERENCE_STRATEGIES = [
  { value: "paper_llm", label: "Literature LLM extraction" },
  { value: "go_terms", label: "GO / category mapping (future)" },
  { value: "essentiality_db", label: "Curated essentiality (future)" },
];

function updateFieldAtIndex(fields, index, patch) {
  return fields.map((field, fieldIndex) =>
    fieldIndex === index ? { ...field, ...patch } : field,
  );
}

export default function CustomFieldsEditor({
  customFields,
  defaultFieldOrtholog,
  keggOrganismCode,
  onChange,
  onDefaultFieldOrthologChange,
  goResolutionEnabled,
  onGoResolutionEnabledChange,
}) {
  const orthologEnabled = canEnableOrthologAllowed(keggOrganismCode);
  const usedKeys = new Set((customFields || []).map((field) => field.key));

  function updateDefaultOrtholog(key, enabled) {
    onDefaultFieldOrthologChange({
      ...(defaultFieldOrtholog || {}),
      [key]: enabled,
    });
  }

  function addBlankField() {
    onChange([...(customFields || []), createEmptyCustomField()]);
  }

  function addTemplate(template) {
    if (usedKeys.has(template.key)) {
      return;
    }
    onChange([...(customFields || []), customFieldFromTemplate(template)]);
  }

  function removeField(index) {
    onChange((customFields || []).filter((_, fieldIndex) => fieldIndex !== index));
  }

  function updateField(index, patch) {
    onChange(updateFieldAtIndex(customFields || [], index, patch));
  }

  return (
    <section className="grid gap-4 rounded-2xl border workbench-border bg-white/40 p-4">
      <div>
        <h3 className="workbench-foreground text-lg font-bold tracking-[-0.02em]">
          Annotation fields
        </h3>
        <p className="workbench-muted mt-2 text-sm leading-6">
          Function and functional category are required defaults on every profile. Add or
          remove optional custom fields independently for this profile.
        </p>
      </div>

      <div className="grid gap-3">
        <p className="workbench-muted text-xs font-bold uppercase tracking-[0.12em]">
          Required defaults
        </p>
        {REQUIRED_DEFAULT_FIELDS.map((field) => (
          <div
            key={field.key}
            className="grid gap-3 rounded-xl border workbench-border bg-white/70 p-3 text-sm"
          >
            <div>
              <p className="workbench-foreground font-semibold">{field.label}</p>
              <p className="workbench-muted mt-1 text-xs">{field.key}</p>
              <p className="workbench-muted mt-2 text-xs leading-5">{field.description}</p>
            </div>
            <label className="flex items-start gap-3 text-sm font-medium">
              <input
                type="checkbox"
                checked={Boolean(defaultFieldOrtholog?.[field.key])}
                disabled={!orthologEnabled}
                onChange={(event) => updateDefaultOrtholog(field.key, event.target.checked)}
                className="mt-1"
              />
              <span>
                Allow ortholog fallback for this field
                {!orthologEnabled ? (
                  <span className="workbench-muted mt-1 block text-xs font-normal">
                    Set a KEGG organism code above to enable ortholog fallback.
                  </span>
                ) : null}
              </span>
            </label>
          </div>
        ))}
        <label className="flex items-start gap-3 rounded-xl border workbench-border bg-white/70 p-3 text-sm font-medium">
          <input
            type="checkbox"
            checked={Boolean(goResolutionEnabled)}
            onChange={(event) =>
              onGoResolutionEnabledChange(event.target.checked)
            }
            className="mt-1"
          />
          <span>
            Resolve GO terms after aggregation
            <span className="workbench-muted mt-1 block text-xs font-normal leading-5">
              {"Runs after target and ortholog aggregation using the job's summary models; free-text categories are still extracted."}
            </span>
          </span>
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={addBlankField}
          className="workbench-button workbench-button-secondary"
        >
          Add blank field
        </button>
        {BUILTIN_OPTIONAL_FIELD_TEMPLATES.map((template) => (
          <button
            key={template.key}
            type="button"
            disabled={usedKeys.has(template.key)}
            onClick={() => addTemplate(template)}
            className="workbench-button workbench-button-secondary disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add {template.label}
          </button>
        ))}
      </div>

      {(customFields || []).length === 0 ? (
        <p className="workbench-muted rounded-xl border border-dashed workbench-border p-4 text-sm">
          No custom fields configured. Optional fields such as drug susceptibility or
          essentiality can be added from templates or defined manually.
        </p>
      ) : (
        <div className="grid gap-4">
          {(customFields || []).map((field, index) => (
            <article
              key={`${field.key || "field"}-${index}`}
              className="grid gap-3 rounded-xl border workbench-border bg-white/70 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="workbench-foreground text-sm font-semibold">
                  Custom field {index + 1}
                </p>
                <button
                  type="button"
                  onClick={() => removeField(index)}
                  className="workbench-button workbench-button-secondary workbench-red"
                >
                  Remove
                </button>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium">
                  Key
                  <input
                    value={field.key}
                    onChange={(event) => updateField(index, { key: event.target.value })}
                    className="workbench-input"
                    placeholder="virulence_factor"
                    required
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  Label
                  <input
                    value={field.label}
                    onChange={(event) => updateField(index, { label: event.target.value })}
                    className="workbench-input"
                    placeholder="Virulence factor"
                    required
                  />
                </label>
              </div>

              <label className="grid gap-2 text-sm font-medium">
                Description (guides LLM extraction)
                <textarea
                  value={field.description}
                  onChange={(event) =>
                    updateField(index, { description: event.target.value })
                  }
                  className="workbench-input min-h-24"
                  placeholder="What should the model extract from each paper excerpt?"
                  required
                />
              </label>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium">
                  Type
                  <select
                    value={field.type}
                    onChange={(event) => updateField(index, { type: event.target.value })}
                    className="workbench-input"
                  >
                    {FIELD_TYPES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  Inference strategy
                  <select
                    value={field.inference_strategy}
                    onChange={(event) =>
                      updateField(index, { inference_strategy: event.target.value })
                    }
                    className="workbench-input"
                  >
                    {INFERENCE_STRATEGIES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="flex items-start gap-3 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={Boolean(field.ortholog_allowed)}
                  disabled={!orthologEnabled || field.inference_strategy !== "paper_llm"}
                  onChange={(event) =>
                    updateField(index, { ortholog_allowed: event.target.checked })
                  }
                  className="mt-1"
                />
                <span>
                  Allow ortholog fallback for this field
                  {!orthologEnabled ? (
                    <span className="workbench-muted mt-1 block text-xs font-normal">
                      Set a KEGG organism code above to enable ortholog fallback.
                    </span>
                  ) : field.inference_strategy !== "paper_llm" ? (
                    <span className="workbench-muted mt-1 block text-xs font-normal">
                      Ortholog fallback applies only to literature LLM fields.
                    </span>
                  ) : null}
                </span>
              </label>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

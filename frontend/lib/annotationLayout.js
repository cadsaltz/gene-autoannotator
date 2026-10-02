export const NO_DATA = "No supported data";

const COMPACT_MAX_LENGTH = 80;
const BOOLEAN_VALUES = new Set(["True", "False"]);

export function isBooleanValue(value) {
  return BOOLEAN_VALUES.has(value);
}

export function isNoData(value) {
  return value === NO_DATA;
}

// Flags and short labels fit the side card; anything sentence-like gets a wide tile.
export function isCompactValue(value) {
  const text = String(value ?? "").trim();
  if (!text || isBooleanValue(text) || isNoData(text)) {
    return true;
  }
  return text.length <= COMPACT_MAX_LENGTH && !/[.;:!?](\s|$)/.test(text) && !text.includes("(");
}

export function planAnnotationGrid(rows) {
  const compact = [];
  const prose = [];
  for (const row of rows) {
    (isCompactValue(row.value) ? compact : prose).push(row);
  }
  const pairedCount = prose.length - 1;
  const tiles = prose.map((row, index) => {
    if (index === 0) {
      return { row, span: "full", lead: true };
    }
    const unpaired = pairedCount % 2 === 1 && index === prose.length - 1;
    return { row, span: unpaired ? "full" : "half", lead: false };
  });
  return { tiles, compact };
}

export function splitListValue(value) {
  return String(value ?? "")
    .split(/\s*,\s*/)
    .map((item) => item.trim())
    .filter(Boolean);
}

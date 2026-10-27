// Statistics are based on measured files, never inferred code ownership.
export const metricKeys = ["code", "comments", "blanks", "lines"];

export function sourceFiles(data) {
  return [...new Map(
    (data.inventory || data.files || [])
      .filter((file) => file.category !== "config")
      .map((file) => [file.path || file.id, file]),
  ).values()];
}

export function isCounted(file) {
  return file.countStatus === "counted" &&
    metricKeys.every((key) => Number.isFinite(file.metrics?.[key]));
}

export function aggregateFiles(files, ready = true) {
  const counted = files.filter(isCounted);
  const available = counted.length > 0 || (ready && files.length === 0);
  return {
    files: files.length,
    countedFiles: counted.length,
    status: !available ? "unavailable" : counted.length < files.length ? "partial" : "complete",
    ...Object.fromEntries(metricKeys.map((key) => [key,
      available ? counted.reduce((sum, file) => sum + file.metrics[key], 0) : null,
    ])),
  };
}

export function fileMedian(files) {
  const values = files.filter(isCounted).map((file) => file.metrics.code).sort((a, b) => a - b);
  if (!values.length) return null;
  const middle = Math.floor(values.length / 2);
  return values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

export function languageRows(files, ready = true) {
  const groups = new Map();
  for (const file of files) {
    const key = file.language || "unknown";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(file);
  }
  return [...groups].map(([name, members]) => ({ name, ...aggregateFiles(members, ready) }));
}

export function directoryRows(files, directory = "", ready = true) {
  const prefix = directory ? `${directory}/` : "";
  const groups = new Map();
  for (const file of files) {
    if (!file.path.startsWith(prefix)) continue;
    const relative = file.path.slice(prefix.length);
    const [name, ...rest] = relative.split("/");
    const path = `${prefix}${name}`;
    const key = `${rest.length ? "directory" : "file"}:${path}`;
    if (!groups.has(key)) groups.set(key, { name, path, kind: rest.length ? "directory" : "file", members: [] });
    groups.get(key).members.push(file);
  }
  return [...groups.values()].map(({ members, ...row }) => ({ ...row, ...aggregateFiles(members, ready) }));
}

export function ranked(rows, unit = "code") {
  return [...rows].sort((a, b) =>
    (b[unit] ?? -1) - (a[unit] ?? -1) || a.name.localeCompare(b.name),
  );
}

export function ratio(value, total) {
  return Number.isFinite(value) && Number.isFinite(total) && total > 0 ? value / total : null;
}

export function percent(value, total) {
  const result = ratio(value, total);
  return result == null ? "—" : `${(result * 100).toFixed(2)}%`;
}

export function parserSummary(data) {
  if (!data.coverage?.parsing) return null;
  const parsing = data.coverage.parsing;
  return { ...parsing, supported: parsing.total - (parsing.unsupported || 0) };
}

export const needsAttention = (file) =>
  !["parsed", "unsupported"].includes(file.parseStatus) || file.countStatus !== "counted";

export const languageName = (name) => ({
  typescript: "TypeScript", javascript: "JavaScript", python: "Python", css: "CSS", html: "HTML",
})[name] || name;

export function parents(path) {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}
export function makeTree(files) {
  const root = { children: new Map() };
  for (const file of files) {
    let at = root;
    const parts = file.path.split("/");
    parts.forEach((name, i) => {
      const id = parts.slice(0, i + 1).join("/");
      if (!at.children.has(name))
        at.children.set(name, {
          id,
          name,
          file: i === parts.length - 1 ? file : null,
          children: new Map(),
        });
      at = at.children.get(name);
    });
  }
  return root;
}
export function selectionInfo(data, selection) {
  let groups = [],
    files = [],
    evidence = [];
  if (selection?.kind === "group") {
    groups = data.groups.filter((g) => g.id === selection.id);
    files = groups.flatMap((g) => g.files);
  } else if (selection?.kind === "file") {
    files = [selection.id];
    groups = data.groups.filter((g) => g.files.includes(selection.id));
  } else if (selection?.kind === "edge") {
    const edge = data.edges.find((e) => e.id === selection.id);
    if (edge) {
      groups = data.groups.filter(
        (g) => g.id === edge.source || g.id === edge.target,
      );
      evidence = edge.evidence;
      files = evidence.flatMap((r) => [r.from, r.to]);
    }
  }
  return { groups, files: [...new Set(files)], evidence };
}
export function searchProject(data, query) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const byId = new Map(data.files.map((f) => [f.id, f]));
  return [
    ...data.groups
      .filter((g) => g.title.toLowerCase().includes(q))
      .map((g) => ({
        kind: "group",
        id: g.id,
        label: g.title,
        detail: "架构模块",
      })),
    ...(data.inventory || data.files)
      .filter((f) => f.category !== "config")
      .filter(
        (f) =>
          f.path.toLowerCase().includes(q) ||
          (byId.get(f.id)?.symbols || []).some((s) =>
            s.name.toLowerCase().includes(q),
          ),
      )
      .map((f) => ({
        kind: "file",
        id: f.id,
        label: f.path.split("/").at(-1),
        detail: f.path,
      })),
  ].slice(0, 10);
}

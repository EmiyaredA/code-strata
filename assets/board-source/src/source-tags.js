export function namePrefixes(names, minimum = 3) {
  return names.map(name => {
    const chars = Array.from(name);
    let length = Math.min(minimum, chars.length);
    while (length < chars.length && names.some(other => other !== name && Array.from(other).slice(0, length).join('') === chars.slice(0, length).join(''))) length++;
    return chars.slice(0, length).join('') + (length < chars.length ? '…' : '');
  });
}
export function sourceGroups(refs = []) {
  const files = new Map();
  for (const ref of refs) {
    if (!ref.path) continue;
    if (!files.has(ref.path)) files.set(ref.path, { path: ref.path, name: ref.path.split('/').at(-1), refs: [], functions: [] });
    const file = files.get(ref.path);file.refs.push(ref);
    if (ref.symbol) {
      const key = ref.symbol.id + ':' + (ref.association || ref.locationKind || 'source');
      if (!file.functions.some(f => f.key === key)) file.functions.push({ key, name: ref.symbol.name + (ref.symbol.name.endsWith(')') ? '' : '()'), ref });
    }
  }
  const groups = [...files.values()];
  const labels = groups.map(g => groups.filter(x => x.name === g.name).length > 1 ? g.path : g.name);
  const prefixes = namePrefixes(labels);
  groups.forEach((g, i) => {
    g.prefix = prefixes[i];
    const names = g.functions.map(f => g.functions.filter(x=>x.name===f.name).length>1 ? `${f.name}:${f.ref.startLine}` : f.name);
    const short = namePrefixes(names);
    g.functions.forEach((f, j) => { f.prefix = short[j]; });
  });
  return groups;
}
export function locationLabel(ref) {
  return ref.association === 'target-definition' ? (ref.status==='candidate'?'候选目标定义':'被调用函数定义') : ref.locationKind === 'definition' ? '函数定义' : ref.association === 'callsite' || ref.locationKind === 'call' ? '调用处' : '源码依据';
}
export function sameEvidence(a, b) {
  return a?.path === b?.path && a?.startLine === b?.startLine && a?.endLine === b?.endLine && a?.locationKind === b?.locationKind && a?.association === b?.association;
}
export function mergeSourceFile(current, requested, file) {
  // Symbol annotations may finish while a source-page request is in flight.
  // A page response supplies text, not permission to discard newer metadata.
  const same=current&&current.snapshotId===requested.snapshotId&&current.diagramId===requested.diagramId&&current.revision===requested.revision&&current.element?.id===requested.element?.id;
  return {...requested,...(same?current:{}),file};
}

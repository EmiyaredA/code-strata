// Only native, successfully read values may stand in for an unset override.
export function resolvedModel(catalog, model) {
  return model || catalog?.defaults?.model?.value || "";
}
export function catalogModel(catalog, model) {
  const id = resolvedModel(catalog, model);
  return catalog?.models?.find(item => item.id === id || item.resolvedId === id);
}
export function inheritedParameter(catalog, model, key) {
  if (!catalog) return null;
  if (catalog.defaults?.[key]) return catalog.defaults[key];
  if (catalog.inheritModelDefaults?.includes(key)) return catalogModel(catalog, model)?.defaults?.[key] || null;
  return null;
}
export function parameterLabel(field, setting) {
  if (!setting) return "未能读取，请选择";
  return setting.label || field.options.find(item => item.value === setting.value)?.label || setting.value;
}

// A value appears once, regardless of whether it was read or explicitly saved.
export function parameterSelection(field, configured, inherited) {
  const value = configured || inherited?.value || "";
  const options = field.options.filter((item, index, all) => all.findIndex(other => other.value === item.value) === index);
  if (!options.some(item => item.value === value)) {
    options.unshift({ value, label: configured ? `${configured}（待确认）` : parameterLabel(field, inherited) });
  }
  return { value, options };
}

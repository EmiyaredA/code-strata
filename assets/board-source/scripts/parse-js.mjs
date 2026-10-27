import ts from 'typescript';
import path from 'node:path';
import { readFileSync } from 'node:fs';
const raw = readFileSync(0, 'utf8');
const { files, configs } = JSON.parse(raw);
const sources = new Map(files.map(f => [f.id, f.content]));
const normalize = p => path.posix.normalize(p).replace(/^\/?repo\//, '');
const packages = new Map();
const diagnostics = [], imports = [], symbols = {}, externalReferences = [];
let external = 0;
for (const [name, text] of Object.entries(configs)) {
  if (!name.endsWith('package.json')) continue;
  try { const p = JSON.parse(text); if (p.name) packages.set(p.name, {root: path.posix.dirname(name), config:p}); } catch { /* invalid config reported by its own tooling */ }
}
function resolveCandidate(candidate) {
  candidate = normalize(candidate);
  const noJs = candidate.replace(/\.(m?js|cjs)$/, '');
  for (const base of [candidate, noJs]) {
    for (const suffix of ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts', '.d.ts', '/index.ts', '/index.tsx', '/index.js', '/src/index.ts']) {
      if (sources.has(base + suffix)) return base + suffix;
    }
  }
}
function compilerOptions(file) {
  let dir = path.posix.dirname(file);
  while (true) {
    const config = dir === '.' ? 'tsconfig.json' : `${dir}/tsconfig.json`;
    if (configs[config]) {
      const parsed = ts.parseConfigFileTextToJson(config, configs[config]);
      if (parsed.error) diagnostics.push({kind:'config', path:config, message:'tsconfig 解析失败'});
      if (parsed.config?.extends) diagnostics.push({kind:'config',path:config,message:'tsconfig extends 未展开；受其影响的别名可能无法解析'});
      return {dir, options: parsed.config?.compilerOptions || {}};
    }
    if (dir === '.') return {dir:'.', options:{}};
    dir = path.posix.dirname(dir);
  }
}
function resolve(spec, file, settings) {
  if (spec.startsWith('.')) return {target:resolveCandidate(path.posix.join(path.posix.dirname(file), spec)), internal:true};
  if (spec.startsWith('/')) return {internal:true};
  for (const [key, replacements] of Object.entries(settings.options.paths || {})) {
    const [pre, post = ''] = key.split('*');
    if (key.includes('*') ? spec.startsWith(pre) && spec.endsWith(post) : spec === key) {
      const middle = key.includes('*') ? spec.slice(pre.length, post ? -post.length : undefined) : '';
      for (const replacement of replacements) {
        const target = resolveCandidate(path.posix.join(settings.dir, settings.options.baseUrl || '.', replacement.replace('*', middle)));
        if (target) return {target, internal:true};
      }
      return {internal:true};
    }
  }
  for (const [name, item] of packages) {
    if (spec !== name && !spec.startsWith(name + '/')) continue;
    const suffix = spec.slice(name.length + 1);
    let entry = item.config.exports?.['.'] || item.config.exports;
    if (typeof entry === 'object') entry = entry?.source || entry?.types || entry?.import || entry?.default;
    const candidates = suffix ? [suffix, `src/${suffix}`] : [typeof entry === 'string' ? entry : '', item.config.source, item.config.types, item.config.module, item.config.main, 'src/index.ts', 'index.ts'];
    for (const candidate of candidates.filter(Boolean)) {
      const target = resolveCandidate(path.posix.join(item.root, candidate));
      if (target) return {target, internal:true};
    }
    return {internal:true};
  }
  if (settings.options.baseUrl) {
    const target = resolveCandidate(path.posix.join(settings.dir, settings.options.baseUrl, spec));
    if (target) return {target, internal:true};
  }
  return {internal:false};
}
for (const file of files) {
  const source = ts.createSourceFile(file.id, file.content, ts.ScriptTarget.Latest, true);
  symbols[file.id] = [];
  for (const error of source.parseDiagnostics || []) diagnostics.push({kind:'syntax',path:file.id,line:source.getLineAndCharacterOfPosition(error.start || 0).line+1,message:ts.flattenDiagnosticMessageText(error.messageText, ' ')});
  const settings = compilerOptions(file.id);
  function record(expr, node, kind='import') {
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    if (!expr || !ts.isStringLiteralLike(expr)) { diagnostics.push({kind:'dynamic',path:file.id,line,message:'动态导入未静态展开'}); return; }
    const spec = expr.text, resolved = resolve(spec, file.id, settings);
    if (resolved.target && resolved.target !== file.id) imports.push({from:file.id,to:resolved.target,line,specifier:spec,kind,text:node.getText(source)});
    else if (!resolved.target && resolved.internal) diagnostics.push({kind:'unresolved',path:file.id,line,message:`未解析项目导入：${spec}`});
    else if (!resolved.target) { external++; externalReferences.push({path:file.id,line,specifier:spec,ecosystem:'node',text:node.getText(source)}); }
  }
  function visit(node) {
    if (ts.isImportDeclaration(node) || (ts.isExportDeclaration(node) && node.moduleSpecifier)) record(node.moduleSpecifier,node);
    else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) record(node.moduleReference.expression,node);
    else if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === 'require'))) record(node.arguments[0],node,'dynamic-import');
    if (node.parent === source && node.name && ts.isIdentifier(node.name)) symbols[file.id].push({name:node.name.text,line:source.getLineAndCharacterOfPosition(node.getStart(source)).line+1,kind:ts.SyntaxKind[node.kind]});
    ts.forEachChild(node,visit);
  }
  visit(source);
}
const uniqueDiagnostics = [...new Map(diagnostics.map(d => [JSON.stringify(d),d])).values()];
process.stdout.write(JSON.stringify({imports,diagnostics:uniqueDiagnostics,external,symbols,externalReferences}));

import ts from "typescript";
import path from "node:path";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const input = JSON.parse(readFileSync(0, "utf8"));
const files = new Map(input.files.map((f) => [f.id, f]));
const configs = input.configs || {};
const nodes = /* @__PURE__ */ new Map(), relations = [], diagnostics = [];
const declarationIds = /* @__PURE__ */ new Map();
const sources = new Map([...files].map(([id, f]) => [id, ts.createSourceFile(id, f.content, ts.ScriptTarget.Latest, true)]));
const hash = (s) => createHash("sha256").update(s).digest("hex").slice(0, 20);
const normalize = (p) => path.posix.normalize(p).replace(/^\/?repo(?:\/|$)/, "") || ".";
const functionKinds = /* @__PURE__ */ new Set(["function", "method", "constructor", "lambda"]);
function range(n, s = n.getSourceFile()) {
  const a = s.getLineAndCharacterOfPosition(n.getStart(s)), b = s.getLineAndCharacterOfPosition(n.end);
  return { start: [a.line + 1, a.character], end: [b.line + 1, b.character] };
}
function identity(file, kind, r) {
  return kind + ":" + hash(`${file}\0${kind}\0${r.start[0]}:${r.start[1]}\0${r.end[0]}:${r.end[1]}`);
}
function edge(kind, source, target, extra = {}) {
  relations.push({ id: hash(`${kind}\0${source}\0${target}\0${extra.siteId || ""}`), kind, source, target, ...extra });
}
function add(kind, name, n, ownerId, extra = {}) {
  const s = n.getSourceFile(), r = range(n, s), id = identity(s.fileName, kind, r);
  const obj = { id, kind, name, path: s.fileName, language: /\.[cm]?tsx?$/.test(s.fileName) ? "typescript" : "javascript", range: r, ownerId, status: "resolved", ...extra };
  nodes.set(id, obj);
  if (ownerId && !["reference", "call"].includes(kind)) edge("contains", ownerId, id);
  return obj;
}
function fnName(n) {
  if (n.name) return n.name.getText(n.getSourceFile());
  if (ts.isConstructorDeclaration(n)) return "constructor";
  if (ts.isVariableDeclaration(n.parent) || ts.isPropertyAssignment(n.parent)) return n.parent.name.getText();
  if (ts.isBinaryExpression(n.parent) && n.parent.right === n) return n.parent.left.getText();
  return `<匿名函数 L${range(n).start[0]}>`;
}
const isFunction = (n) => ts.isFunctionLike(n) && !!n.body;
const kindOfFunction = (n) => ts.isConstructorDeclaration(n) ? "constructor" : ts.isMethodDeclaration(n) || ts.isGetAccessor(n) || ts.isSetAccessor(n) ? "method" : ts.isArrowFunction(n) || ts.isFunctionExpression(n) ? "lambda" : "function";
function bindingNames(n) {
  if (ts.isIdentifier(n)) return [n];
  if (ts.isObjectBindingPattern(n) || ts.isArrayBindingPattern(n)) return n.elements.flatMap((e) => ts.isBindingElement(e) ? bindingNames(e.name) : []);
  return [];
}
function declarations(n, owner, functionId) {
  if (ts.isClassDeclaration(n) || ts.isClassExpression(n)) {
    const obj = add("class", n.name?.text || "<匿名类>", n, owner);
    declarationIds.set(n, obj.id);
    for (const member of n.members) declarations(member, obj.id, functionId);
    return;
  }
  if (isFunction(n)) {
    const obj = add(kindOfFunction(n), fnName(n), n, owner, { asyncFunction: !!n.modifiers?.some((m) => m.kind === ts.SyntaxKind.AsyncKeyword) });
    declarationIds.set(n, obj.id);
    for (const p of n.parameters) for (const name of bindingNames(p.name)) {
      const v = add("parameter", name.text, name, obj.id, { functionId: obj.id, access: "declaration", typeLabel: p.type?.getText() || null });
      declarationIds.set(name, v.id);
      if (p.name === name) declarationIds.set(p, v.id);
    }
    for (const p of n.parameters) if (p.initializer) declarations(p.initializer, owner, functionId);
    declarations(n.body, obj.id, obj.id);
    return;
  }
  if (ts.isVariableDeclaration(n) || ts.isBindingElement(n)) {
    for (const name of bindingNames(n.name)) {
      if (!declarationIds.has(name)) {
        const v = add("variable", name.text, name, owner, { functionId, access: n.initializer ? "declaration-write" : "declaration", typeLabel: n.type?.getText() || null });
        declarationIds.set(name, v.id);
        if (n.name === name) declarationIds.set(n, v.id);
      }
    }
  }
  ts.forEachChild(n, (child) => declarations(child, owner, functionId));
}
for (const [id, source] of sources) {
  for (const e of source.parseDiagnostics || []) diagnostics.push({ kind: "syntax", path: id, line: source.getLineAndCharacterOfPosition(e.start || 0).line + 1, message: ts.flattenDiagnosticMessageText(e.messageText, " ") });
  const file = add("file", id, source, null);
  declarations(source, file.id, null);
}
function structural() {
  const wanted = input.function;
  const source = sources.get(wanted.path);
  let target;
  function find(n) {
    if (isFunction(n) && identity(wanted.path, kindOfFunction(n), range(n)) === wanted.id) target = n;
    ts.forEachChild(n, find);
  }
  if (source) find(source);
  nodes.clear();
  relations.length = 0;
  function block(statements, owner, branch = "body") {
    let previous;
    for (const n of statements) {
      const folded = isFunction(n) || ts.isClassDeclaration(n);
      const obj = add("statement", n.getText(source).split("\n")[0].slice(0, 160), n, owner, { nodeType: ts.SyntaxKind[n.kind], branch, folded });
      if (previous) edge("structure-next", previous, obj.id, { simplified: true });
      previous = [ts.SyntaxKind.ReturnStatement, ts.SyntaxKind.ThrowStatement, ts.SyntaxKind.BreakStatement, ts.SyntaxKind.ContinueStatement].includes(n.kind) ? null : obj.id;
      if (folded) continue;
      const descend = (body, title) => {
        if (body) block(ts.isBlock(body) ? body.statements : [body], obj.id, title);
      };
      if (ts.isIfStatement(n)) {
        descend(n.thenStatement, "条件成立");
        descend(n.elseStatement, "否则");
      } else if (ts.isTryStatement(n)) {
        descend(n.tryBlock, "try");
        descend(n.catchClause?.block, "异常处理");
        descend(n.finallyBlock, "finally · 始终清理");
      } else if (ts.isSwitchStatement(n)) for (const c of n.caseBlock.clauses) block(c.statements, obj.id, c.expression ? `case ${c.expression.getText(source)}` : "default");
      else if (ts.isBlock(n)) block(n.statements, obj.id, "代码块");
      else if (n.statement) descend(n.statement, "循环 / 主体");
    }
  }
  if (target) block(ts.isBlock(target.body) ? target.body.statements : [target.body], wanted.id);
}
if (input.mode === "logic") structural();
else {
  let configFor = function(file) {
    let dir = path.posix.dirname(file);
    while (true) {
      const key = dir === "." ? "tsconfig.json" : `${dir}/tsconfig.json`;
      if (configs[key]) return key;
      if (dir === ".") return "";
      dir = path.posix.dirname(dir);
    }
  }, optionsFor = function(key, seen = /* @__PURE__ */ new Set()) {
    if (!key || seen.has(key)) return {};
    seen.add(key);
    const parsed = ts.parseConfigFileTextToJson(key, configs[key]);
    if (parsed.error) {
      diagnostics.push({ kind: "config", path: key, message: "tsconfig 解析失败" });
      return {};
    }
    let inherited = {};
    const exts = parsed.config?.extends;
    for (const ext of typeof exts === "string" ? [exts] : Array.isArray(exts) ? exts : []) {
      const base = normalize(path.posix.join(path.posix.dirname(key), ext));
      const resolved = [base, base + ".json", base + "/tsconfig.json"].find((x) => configs[x]);
      if (resolved) inherited = { ...inherited, ...optionsFor(resolved, seen) };
      else diagnostics.push({ kind: "config", path: key, message: `未捕获 extends 配置：${ext}` });
    }
    const converted = ts.convertCompilerOptionsFromJson(parsed.config?.compilerOptions || {}, "/repo/" + path.posix.dirname(key));
    return { ...inherited, ...converted.options };
  };
  const groups = /* @__PURE__ */ new Map();
  for (const id of files.keys()) {
    const key = configFor(id);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(id);
  }
  const imported = new Map((input.imports || []).map((r) => [r.from + "\0" + r.specifier, r.to]));
  for (const [key, roots] of groups) {
    let trackWrites = function(n) {
      if (ts.isBinaryExpression(n) && n.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && n.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
        const s = checker.getSymbolAtLocation(n.left);
        if (s) rebound.add(s);
      }
      ts.forEachChild(n, trackWrites);
    }, symbolAt = function(n, follow = true) {
      try {
        let s = checker.getSymbolAtLocation(n);
        if (follow && s && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
        return s;
      } catch {
        return null;
      }
    }, mappedDeclaration = function(s, callable = false) {
      if (!s) return null;
      for (const d of [s.valueDeclaration, ...s.declarations || []].filter(Boolean)) {
        if (callable && ts.isVariableDeclaration(d) && d.initializer && isFunction(d.initializer)) return declarationIds.get(d.initializer);
        const id = declarationIds.get(d) || declarationIds.get(d.name);
        if (id && (!callable || functionKinds.has(nodes.get(id)?.kind) || nodes.get(id)?.kind === "class")) return id;
      }
      return null;
    }, walk = function(n, owner, functionId) {
      if (declarationIds.has(n) && (isFunction(n) || ts.isClassDeclaration(n) || ts.isClassExpression(n))) {
        owner = declarationIds.get(n);
        if (isFunction(n)) functionId = owner;
      }
      if (ts.isCallExpression(n) || ts.isNewExpression(n)) {
        const label = n.expression.getText(n.getSourceFile());
        if (n.expression.kind !== ts.SyntaxKind.ImportKeyword && label !== "require") {
          const rawSymbol = symbolAt(n.expression, false);
          const typeOnly = rawSymbol?.declarations?.some((d) => ts.isImportSpecifier(d) && d.isTypeOnly || ts.isImportClause(d) && d.isTypeOnly || ts.isImportSpecifier(d) && d.parent.parent.isTypeOnly);
          const symbol = typeOnly ? null : symbolAt(n.expression);
          let target = mappedDeclaration(symbol, true);
          try {
            const signature = checker.getResolvedSignature(n), d = signature?.declaration;
            if (!typeOnly && d && isFunction(d)) target = declarationIds.get(d) || target;
          } catch {
          }
          if (ts.isNewExpression(n) && nodes.get(target)?.kind === "class") {
            target = [...nodes.values()].find((x) => x.ownerId === target && x.kind === "constructor")?.id || target;
          }
          const dynamic = ts.isElementAccessExpression(n.expression) || ts.isPropertyAccessExpression(n.expression) && n.expression.expression.kind !== ts.SyntaxKind.ThisKeyword && !symbol?.declarations?.some((d) => ts.isFunctionDeclaration(d) || ts.isMethodDeclaration(d) || ts.isVariableDeclaration(d));
          const mutable = rebound.has(symbol) || symbol?.declarations?.some((d) => ts.isVariableDeclaration(d) && !(d.parent.flags & ts.NodeFlags.Const));
          const decorated = symbol?.declarations?.some((d) => ts.canHaveDecorators(d) && ts.getDecorators(d)?.length);
          const classOnly = nodes.get(target)?.kind === "class";
          let status = target ? classOnly || dynamic || decorated || mutable || ts.isPropertyAccessExpression(n.expression) ? "candidate" : "resolved" : "unresolved";
          if (target && !decorated && !mutable && ts.isPropertyAccessExpression(n.expression)) {
            const base = symbolAt(n.expression.expression, false);
            if (base?.declarations?.some((d) => ts.isNamespaceImport(d)) || symbol?.declarations?.some((d) => ts.isMethodDeclaration(d) && ts.isObjectLiteralExpression(d.parent))) status = "resolved";
          }
          const obj = add("call", label, n, owner, { functionId, targetId: target || null, status, reason: typeOnly ? "仅类型导入不建立运行时调用目标" : !target ? "仅有类型签名、外部依赖或动态表达式，未定位到源码实现" : status === "candidate" ? "源码声明可定位；属性派发、装饰器、重赋值或构造实现仍可能变化" : "由捕获源码中的符号及调用签名定位" });
          if (target) edge("calls", functionId || owner, target, { siteId: obj.id, status, path: obj.path, range: obj.range });
        }
      }
      if (ts.isIdentifier(n)) {
        const parent = n.parent;
        const definition = declarationIds.has(n) || parent.name === n && (ts.isDeclarationStatement(parent) || isFunction(parent)) || ts.isImportSpecifier(parent) || ts.isImportClause(parent) || ts.isNamespaceImport(parent);
        const propertyName = ts.isPropertyAccessExpression(parent) && parent.name === n || (ts.isPropertyAssignment(parent) || ts.isMethodDeclaration(parent)) && parent.name === n || ts.isBindingElement(parent) && parent.propertyName === n;
        const typeOnly = (() => {
          let p = parent;
          while (p && !ts.isStatement(p)) {
            if (ts.isTypeNode(p)) return true;
            p = p.parent;
          }
          return false;
        })();
        if (!definition && !propertyName && !typeOnly) {
          let symbol = ts.isShorthandPropertyAssignment(parent) ? checker.getShorthandAssignmentValueSymbol(parent) : symbolAt(n);
          const target = mappedDeclaration(symbol);
          const write = ts.isBinaryExpression(parent) && parent.left === n && parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment;
          const rw = write && parent.operatorToken.kind !== ts.SyntaxKind.EqualsToken || (ts.isPostfixUnaryExpression(parent) || ts.isPrefixUnaryExpression(parent)) && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(parent.operator);
          const access = rw ? "readwrite" : write ? "write" : "read";
          const variable = nodes.get(target);
          const obj = add("reference", n.text, n, owner, { functionId, symbolId: target, access, capture: !!(variable?.functionId && variable.functionId !== functionId), status: target ? "resolved" : "unresolved" });
          if (target) edge("references", obj.id, target, { access, capture: obj.capture });
        }
      }
      ts.forEachChild(n, (child) => walk(child, owner, functionId));
    };
    const options = { ...optionsFor(key), allowJs: true, checkJs: true, noLib: true, skipLibCheck: true, noEmit: true, target: ts.ScriptTarget.Latest };
    const host = {
      getSourceFile: (name) => sources.get(normalize(name)),
      getDefaultLibFileName: () => "",
      writeFile: () => {
      },
      getCurrentDirectory: () => "/repo",
      getDirectories: () => [],
      directoryExists: (d) => {
        const p = normalize(d);
        return p === "." || [...files.keys(), ...Object.keys(configs)].some((x) => x.startsWith(p + "/"));
      },
      fileExists: (p) => files.has(normalize(p)) || Object.hasOwn(configs, normalize(p)),
      readFile: (p) => files.get(normalize(p))?.content ?? configs[normalize(p)],
      getCanonicalFileName: (p) => normalize(p),
      useCaseSensitiveFileNames: () => true,
      getNewLine: () => "\n",
      realpath: (p) => normalize(p)
    };
    host.resolveModuleNames = (names, containing) => names.map((spec) => {
      const from = normalize(containing);
      const found = ts.resolveModuleName(spec, "/repo/" + from, options, host).resolvedModule;
      const target = found ? normalize(found.resolvedFileName) : imported.get(from + "\0" + spec);
      return target && files.has(target) ? { resolvedFileName: target, extension: target.endsWith(".tsx") ? ts.Extension.Tsx : /\.tsx?$/.test(target) ? ts.Extension.Ts : target.endsWith(".jsx") ? ts.Extension.Jsx : ts.Extension.Js, isExternalLibraryImport: false } : void 0;
    });
    const program = ts.createProgram(roots, options, host), checker = program.getTypeChecker();
    const rebound = /* @__PURE__ */ new Set();
    for (const id of roots) trackWrites(sources.get(id));
    for (const id of roots) {
      const s = sources.get(id), file = [...nodes.values()].find((n) => n.kind === "file" && n.path === id);
      if (s && file) walk(s, file.id, null);
    }
  }
}
process.stdout.write(JSON.stringify({ version: 1, nodes: [...nodes.values()], relations: [...new Map(relations.map((r) => [r.id, r])).values()], diagnostics, resources: { peakRssBytes: process.resourceUsage().maxRSS * 1024 }, engine: { name: "typescript", version: ts.version } }));

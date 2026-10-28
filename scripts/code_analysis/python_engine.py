"""Python AST + symtable adapter. Never imports or executes analyzed modules."""
import ast
import symtable
from pathlib import PurePosixPath
from .model import identity, edge, empty, FUNCTIONS


class Analyzer:
    def __init__(self, files):
        self.files = {f['id']: f for f in files}
        self.lines = {p: f['content'].splitlines() or [''] for p, f in self.files.items()}
        self.result = empty()
        self.nodes = {}
        self.trees = {}
        self.scopes = {}
        self.bindings = {}
        self.imports = {}
        self.decorated = set()
        self.writes = {}
        self.value_targets = {}
        self.aliases = {}
        self.tables = {}
        self.used_tables = set()
        self.module_names = {}
        self.file_ids = {}
        for path in self.files:
            parts = PurePosixPath(path).with_suffix('').parts
            variants = [parts]
            for prefix in ('src', 'backend'):
                if prefix in parts:
                    variants.append(parts[parts.index(prefix) + 1:])
            for variant in variants:
                name = '.'.join(variant[:-1] if variant[-1:] == ('__init__',) else variant)
                self.module_names.setdefault(name, []).append(path)
        for path, f in self.files.items():
            try:
                self.trees[path] = ast.parse(f['content'], filename=path)
                self.tables[path] = symtable.symtable(f['content'], path, 'exec')
            except (SyntaxError, ValueError) as exc:
                self.trees.pop(path, None)
                self.tables.pop(path, None)
                self.result['diagnostics'].append(dict(kind='syntax', path=path, line=getattr(exc, 'lineno', 1), message=str(exc)))
        for path, tree in self.trees.items():
            self.path = path
            root = self.add('file', path, tree, None)
            self.root = root['id']
            self.file_ids[path] = self.root
            self.scopes[self.root] = dict(parent=None, kind='module', table=self.tables[path], path=path)
            self.bindings[self.root] = {}
            self.declarations(tree, self.root)
        for path, tree in self.trees.items():
            def writes(n, scope):
                scope = self.aliases.get(id(n), scope)
                if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Lambda):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for target in targets:
                        if isinstance(target, ast.Name): self.value_targets[self.lookup(scope, target.id)] = self.aliases.get(id(n.value))
                if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                    binding = self.lookup(scope, n.id)
                    self.writes.setdefault(binding, []).append(n)
                for child in ast.iter_child_nodes(n): writes(child, scope)
            writes(tree, self.file_id(path))
        self.annotation_refs = set()
        for tree in self.trees.values():
            for node in ast.walk(tree):
                annotations = [getattr(node, 'annotation', None), getattr(node, 'returns', None)]
                for annotation in annotations:
                    if annotation: self.annotation_refs.update(id(x) for x in ast.walk(annotation) if isinstance(x, ast.Name))
        self.augmented = {id(n.target) for tree in self.trees.values() for n in ast.walk(tree) if isinstance(n, ast.AugAssign)}
        for path, tree in self.trees.items():
            self.path = path
            self.references(tree, self.file_id(path))
        self.result['nodes'] = list(self.nodes.values())

    def file_id(self, path):
        return self.file_ids[path]

    def position(self, n):
        lines = self.lines[self.path]
        if isinstance(n, ast.Module):
            return [1, 0], [len(lines), len(lines[-1].encode('utf-16-le')) // 2]
        def col(line, offset):
            return len(lines[max(0, min(line - 1, len(lines) - 1))].encode('utf8')[:offset].decode('utf8').encode('utf-16-le')) // 2
        line, last = getattr(n, 'lineno', 1), getattr(n, 'end_lineno', getattr(n, 'lineno', 1))
        return [line, col(line, getattr(n, 'col_offset', 0))], [last, col(last, getattr(n, 'end_col_offset', 0) or 0)]

    def add(self, kind, name, n, owner, **extra):
        start, end = self.position(n)
        obj = dict(id=identity(self.path, kind, start, end), kind=kind, name=name,
                   path=self.path, language='python', range=dict(start=start, end=end),
                   ownerId=owner, status='resolved', **extra)
        self.nodes[obj['id']] = obj
        if owner and kind not in ('reference', 'call'):
            self.result['relations'].append(edge('contains', owner, obj['id']))
        return obj

    def table_for(self, parent, node, name):
        table = self.scopes[parent].get('table')
        if table:
            # Python 3.14+ annotation scopes may precede function/class scopes.
            expected = 'class' if isinstance(node, ast.ClassDef) else 'function'
            def kind(t):
                k = t.get_type()
                return getattr(k, 'value', k)
            def candidates(parent):
                for child in parent.get_children():
                    if child.get_name() == name and child.get_lineno() == node.lineno and kind(child) == expected:
                        yield child
                    elif kind(child) not in ('function', 'class'):
                        yield from candidates(child)
            selected = next((t for t in candidates(table) if t.get_id() not in self.used_tables), None)
            if selected: self.used_tables.add(selected.get_id())
            return selected
        return None

    def declare(self, scope, name, n, kind='variable'):
        table = self.scopes[scope].get('table')
        if table:
            try:
                sym = table.lookup(name)
                if (sym.is_global() or sym.is_nonlocal()) and self.scopes[scope]['parent']:
                    parent = self.scopes[scope]['parent']
                    if sym.is_global():
                        while self.scopes[parent]['parent']:
                            parent = self.scopes[parent]['parent']
                    else:
                        while self.scopes[parent]['parent'] and (name not in self.bindings[parent] or self.scopes[parent]['kind'] == 'class'):
                            parent = self.scopes[parent]['parent']
                    scope = parent
            except KeyError:
                pass
        if name not in self.bindings[scope]:
            obj = self.add(kind, name, n, scope, functionId=self.owner_function(scope), access='declaration' if kind == 'parameter' else 'declaration-write', typeLabel=ast.unparse(n.annotation) if getattr(n, 'annotation', None) else None)
            self.bindings[scope][name] = obj['id']
        return self.bindings[scope][name]

    def declarations(self, n, scope):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            name = getattr(n, 'name', '<lambda>')
            kind = 'class' if isinstance(n, ast.ClassDef) else 'lambda' if isinstance(n, ast.Lambda) else 'constructor' if name == '__init__' else 'method' if self.scopes[scope]['kind'] == 'class' else 'function'
            obj = self.add(kind, name, n, scope, asyncFunction=isinstance(n, ast.AsyncFunctionDef))
            if getattr(n, 'decorator_list', []):
                self.decorated.add(obj['id'])
                obj['decorated'] = True
            if not isinstance(n, ast.Lambda):
                self.bindings[scope][name] = obj['id']
            else:
                self.aliases[id(n)] = obj['id']
            self.aliases[id(n)] = obj['id']
            self.scopes[obj['id']] = dict(parent=scope, kind='class' if kind == 'class' else 'function', table=self.table_for(scope, n, 'lambda' if isinstance(n, ast.Lambda) else name), path=self.path)
            self.bindings[obj['id']] = {}
            if not isinstance(n, ast.ClassDef):
                args = n.args.posonlyargs + n.args.args + n.args.kwonlyargs + ([n.args.vararg] if n.args.vararg else []) + ([n.args.kwarg] if n.args.kwarg else [])
                for arg in args:
                    self.declare(obj['id'], arg.arg, arg, 'parameter')
                for default in n.args.defaults + [x for x in n.args.kw_defaults if x]:
                    self.declarations(default, scope)
            for decorator in getattr(n, 'decorator_list', []):
                self.declarations(decorator, scope)
            for child in ([n.body] if isinstance(n, ast.Lambda) else n.body):
                self.declarations(child, obj['id'])
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            obj = self.add('scope', type(n).__name__, n, scope)
            self.aliases[id(n)] = obj['id']
            self.scopes[obj['id']] = dict(parent=scope, kind='comprehension', table=None, path=self.path)
            self.bindings[obj['id']] = {}
            # The first iterable evaluates in the enclosing scope.
            self.declarations(n.generators[0].iter, scope)
            for gen in n.generators:
                self.declarations(gen.target, obj['id'])
                if gen is not n.generators[0]: self.declarations(gen.iter, obj['id'])
                for item in gen.ifs: self.declarations(item, obj['id'])
            for attr in ('elt', 'key', 'value'):
                if hasattr(n, attr): self.declarations(getattr(n, attr), obj['id'])
            return
        if isinstance(n, ast.NamedExpr) and self.scopes[scope]['kind'] == 'comprehension':
            parent = scope
            while self.scopes[parent]['kind'] == 'comprehension': parent = self.scopes[parent]['parent']
            self.declarations(n.target, parent)
            self.declarations(n.value, scope)
            return
        if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            self.declare(scope, n.name, n)
        if isinstance(n, ast.MatchMapping) and n.rest:
            self.declare(scope, n.rest, n)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            self.declare(scope, n.id, n)
        if isinstance(n, ast.ExceptHandler) and n.name:
            self.declare(scope, n.name, n)
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                name = a.asname or (a.name.split('.')[0] if isinstance(n, ast.Import) else a.name)
                if name == '*':
                    self.result['diagnostics'].append(dict(kind='unsupported', path=self.path, line=n.lineno, message='星号导入不展开符号绑定'))
                    continue
                symbol = self.declare(scope, name, a)
                self.nodes[symbol]['imported'] = True
                if isinstance(n, ast.Import):
                    self.imports[symbol] = (a.name if a.asname else a.name.split('.')[0], None)
                else:
                    module = n.module or ''
                    if n.level:
                        parent = list(PurePosixPath(self.path).parent.parts)
                        if n.level > len(parent):
                            self.result['diagnostics'].append(dict(kind='unresolved', path=self.path, line=n.lineno, message='相对导入超出包范围'))
                            continue
                        module = '.'.join(parent[:len(parent) - n.level + 1] + ([module] if module else []))
                    self.imports[symbol] = (module, a.name)
        for child in ast.iter_child_nodes(n):
            self.declarations(child, scope)

    def lookup(self, scope, name):
        initial = scope
        while scope:
            info = self.scopes[scope]
            table = info.get('table')
            if scope == initial and table:
                try:
                    sym = table.lookup(name)
                    if sym.is_global() and info['parent']:
                        while self.scopes[scope]['parent']: scope = self.scopes[scope]['parent']
                        return self.bindings[scope].get(name)
                    if sym.is_free() or sym.is_nonlocal():
                        scope = info['parent']
                        while scope and self.scopes[scope]['kind'] == 'class': scope = self.scopes[scope]['parent']
                        continue
                except KeyError:
                    pass
            if name in self.bindings[scope]:
                return self.bindings[scope][name]
            scope = info['parent']
            # Function/comprehension lexical lookup skips class namespaces.
            while scope and self.scopes[initial]['kind'] != 'class' and self.scopes[scope]['kind'] == 'class':
                scope = self.scopes[scope]['parent']
        return None

    def imported(self, binding, seen=None):
        seen = set() if seen is None else seen
        if binding in seen: return None
        seen.add(binding)
        if binding not in self.imports: return binding
        module, member = self.imports[binding]
        paths = list(set(self.module_names.get(module, [])))
        if len(paths) != 1: return None
        root = self.file_id(paths[0])
        if member is None: return root
        target = self.bindings[root].get(member)
        return self.imported(target, seen) if target else None

    def target(self, expr, scope):
        if isinstance(expr, ast.Name):
            raw = self.lookup(scope, expr.id)
            target = self.imported(raw) if raw else None
            if target in self.value_targets and len(self.writes.get(target, [])) == 1:
                target = self.value_targets[target]
                return target, 'candidate'
            return target, 'candidate' if target and self.writes.get(target) else 'resolved' if target else 'unresolved'
        if isinstance(expr, ast.Lambda): return self.aliases.get(id(expr)), 'resolved'
        if isinstance(expr, ast.Attribute):
            base, status = self.target(expr.value, scope)
            if base in self.bindings and self.nodes[base]['kind'] in ('file', 'class'):
                member = self.bindings[base].get(expr.attr)
                return self.imported(member) if member else None, 'candidate' if self.nodes[base]['kind'] == 'class' else status
            # self/cls only yields a candidate: descriptors and overrides can intervene.
            if isinstance(expr.value, ast.Name) and expr.value.id in ('self', 'cls'):
                root = scope
                while root and self.scopes[root]['kind'] != 'class': root = self.scopes[root]['parent']
                if root: return self.bindings[root].get(expr.attr), 'candidate'
        return None, 'unresolved'

    def owner_function(self, scope):
        while scope:
            if self.nodes[scope]['kind'] in FUNCTIONS: return scope
            scope = self.scopes[scope]['parent']
        return None

    def references(self, n, scope):
        if id(n) in self.aliases:
            own = self.aliases[id(n)]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                for d in getattr(n, 'decorator_list', []): self.references(d, scope)
                if not isinstance(n, ast.ClassDef):
                    for d in n.args.defaults + [x for x in n.args.kw_defaults if x]: self.references(d, scope)
                for child in ([n.body] if isinstance(n, ast.Lambda) else n.body): self.references(child, own)
                return
            if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                self.references(n.generators[0].iter, scope)
                for gen in n.generators:
                    self.references(gen.target, own)
                    if gen is not n.generators[0]: self.references(gen.iter, own)
                    for item in gen.ifs: self.references(item, own)
                for attr in ('elt', 'key', 'value'):
                    if hasattr(n, attr): self.references(getattr(n, attr), own)
                return
        if isinstance(n, ast.Name):
            target = self.lookup(scope, n.id)
            obj = self.add('reference', n.id, n, scope, functionId=self.owner_function(scope),
                           access='type' if id(n) in self.annotation_refs else 'readwrite' if id(n) in self.augmented else 'write' if isinstance(n.ctx, ast.Store) else 'delete' if isinstance(n.ctx, ast.Del) else 'read',
                           symbolId=target, capture=bool(target and self.nodes[target]['ownerId'] != scope and self.scopes.get(self.nodes[target]['ownerId'], {}).get('kind') in ('function','comprehension') and self.nodes[target]['kind'] in ('variable', 'parameter')))
            if target: self.result['relations'].append(edge('references', obj['id'], target, access=obj['access'], capture=obj['capture']))
            else: obj['status'] = 'unresolved'
        if isinstance(n, ast.Call):
            target, status = self.target(n.func, scope)
            if target and self.nodes[target]['kind'] == 'class':
                ctor = self.bindings[target].get('__init__')
                target = ctor or target
                if not ctor: status = 'candidate'
            if target and self.nodes[target]['kind'] not in FUNCTIONS | {'class'}: target = None
            if target in self.decorated: status = 'candidate'
            label = ast.get_source_segment(self.files[self.path]['content'], n.func) or '<call>'
            obj = self.add('call', label, n, scope, functionId=self.owner_function(scope), targetId=target)
            obj['status'] = status if target else 'unresolved'
            obj['reason'] = ('源码声明可定位；方法派发、装饰器或构造实现仍可能变化' if obj['status'] == 'candidate' else '外部依赖、回调参数或动态接收者未解析' if not target else '由捕获源码中的词法绑定及导入链定位')
            if target: self.result['relations'].append(edge('calls', obj['functionId'] or scope, target, siteId=obj['id'], status=obj['status'], path=self.path, range=obj['range']))
        for child in ast.iter_child_nodes(n): self.references(child, scope)


def analyze(files):
    return Analyzer(files).result


def logic(file, function):
    engine = Analyzer([file])
    tree = engine.trees.get(file['id'])
    if tree is None: return engine.result
    engine.path = file['id']
    engine.result = empty()
    engine.nodes = {}
    target = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            start, end = engine.position(n)
            if start == function['range']['start'] and end == function['range']['end']:
                target = n
                break
    if target is None: return engine.result
    def block(items, parent, label='body'):
        previous = None
        for n in items:
            text = ast.get_source_segment(file['content'], n) or type(n).__name__
            nested = isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            obj = engine.add('statement', text.splitlines()[0][:160], n, parent,
                             nodeType=type(n).__name__, branch=label, folded=nested)
            if previous:
                engine.result['relations'].append(edge('structure-next', previous, obj['id'], simplified=True))
            previous = None if isinstance(n, (ast.Return, ast.Raise, ast.Break, ast.Continue)) else obj['id']
            if nested: continue
            for attr, title in [('body','主体'), ('orelse','否则 / 正常结束'), ('finalbody','finally · 始终清理')]:
                body = getattr(n, attr, None)
                if isinstance(body, list) and body: block(body, obj['id'], title)
            for handler in getattr(n, 'handlers', []):
                block([handler], obj['id'], '异常处理')
            if isinstance(n, ast.Match):
                for case in n.cases: block(case.body, obj['id'], 'case ' + ast.unparse(case.pattern))
    block([target.body] if isinstance(target, ast.Lambda) else target.body, function['id'])
    engine.result['nodes'] = list(engine.nodes.values())
    return engine.result

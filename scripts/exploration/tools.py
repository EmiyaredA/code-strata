"""Tool contracts and server-side graph validation. No AI-supplied call facts."""
from .store import encoded


def tool(name, description, properties, required=()):
    return dict(name=name, description=description, inputSchema=dict(type='object', properties=properties,
                required=list(required), additionalProperties=False),
                annotations=dict(readOnlyHint=name != 'save_view', destructiveHint=False, openWorldHint=False,
                                 idempotentHint=True))


STRING = dict(type='string')
INTEGER = dict(type='integer')
READ_TOOLS = [
    tool('get_conversation', '按应用会话 ID 分页读取已保存的聊天历史与当前图摘要。',
         dict(id=STRING, cursor=dict(type='integer', minimum=0), limit=dict(type='integer', minimum=1, maximum=100)), ['id']),
    tool('get_view', '读取此会话当前已保存的完整阅读图及其源码快照 ID。', dict(id=STRING), ['id']),
    tool('read_snapshot_source', '读取会话历史快照中已保存的源码或配置正文（每次最多 300 行），不读取实时磁盘。',
         dict(id=STRING, snapshotId=STRING, path=STRING, startLine=INTEGER, endLine=INTEGER), ['id', 'snapshotId', 'path']),
]
RUN_TOOLS = [
    tool('search_code', '在本轮绑定的 Python/TS 静态分析快照中搜索文件、类、函数、变量；支持分页。',
         dict(text=STRING, offset=INTEGER, limit=dict(type='integer', minimum=1, maximum=100)), ['text']),
    tool('query_code', '查询静态代码关系。functions 为函数间调用；logic 为单函数结构简图，非运行轨迹或完整 CFG。返回节点/关系 ID 可交给 save_view。',
         dict(view=dict(type='string', enum=['files', 'symbols', 'functions', 'logic', 'references']),
              focusId=STRING, hops=dict(type='integer', minimum=1, maximum=5), offset=INTEGER, edgeOffset=INTEGER,
              limit=dict(type='integer', minimum=1, maximum=100)), ['view']),
    tool('read_source', '读取本轮快照中的源码或配置正文（包括 HTML、CSS、package.json 等已捕获文本），不要求支持语义解析，不能读取实时磁盘文件。最多 300 行。',
         dict(path=STRING, startLine=INTEGER, endLine=INTEGER), ['path']),
    tool('save_view', '提交本轮阅读图草稿。nodes/relations 只能填写本轮查询返回的 ID，调用确定性和源码由应用保留。任务正常完成后才替换旧图。分组仅为业务阅读说明。',
         dict(title=STRING, view=dict(type='string', enum=['functions', 'files', 'logic']),
              nodes=dict(type='array', items=STRING, minItems=1, maxItems=100),
              relations=dict(type='array', items=STRING, maxItems=300),
              groups=dict(type='array', maxItems=20, items=dict(type='object', additionalProperties=False,
                  properties=dict(title=STRING, nodeIds=dict(type='array', items=STRING, maxItems=100)), required=['title', 'nodeIds'])),
              explanation=STRING), ['title', 'view', 'nodes', 'relations']),
]


def validate_arguments(name, args, definitions):
    definition = next((t for t in definitions if t['name'] == name), None)
    if not definition or not isinstance(args, dict):
        raise ValueError('未知工具或无效参数')
    schema = definition['inputSchema']
    if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
        raise ValueError('工具参数字段无效')
    for key, value in args.items():
        spec = schema['properties'][key]
        if spec['type'] == 'string' and (not isinstance(value, str) or len(value) > 16000):
            raise ValueError(f'{key} 必须是有界字符串')
        if spec['type'] == 'integer' and (type(value) is not int or value < spec.get('minimum', 0) or value > spec.get('maximum', 1000000)):
            raise ValueError(f'{key} 范围无效')
        if 'enum' in spec and value not in spec['enum']:
            raise ValueError(f'{key} 类型无效')
        if spec['type'] == 'array' and (not isinstance(value, list) or not spec.get('minItems', 0) <= len(value) <= spec['maxItems']):
            raise ValueError(f'{key} 数量无效')
    return args


def validate_view(store, run_id, snapshot_id, args):
    validate_arguments('save_view', args, RUN_TOOLS)
    if not args['title'].strip() or len(args['title']) > 200 or len(args.get('explanation', '')) > 16000:
        raise ValueError('图标题或解释过长')
    for key in ('nodes', 'relations'):
        if any(not isinstance(x, str) or len(x) > 256 for x in args[key]) or len(set(args[key])) != len(args[key]):
            raise ValueError('图中的 ID 无效或重复')
    known_nodes, known_relations = store.facts(run_id, 'node'), store.facts(run_id, 'relation')
    if any(x not in known_nodes for x in args['nodes']) or any(x not in known_relations for x in args['relations']):
        raise ValueError('图包含未经本轮工具查询提供的节点或关系')
    nodes, relations = [known_nodes[x] for x in args['nodes']], [known_relations[x] for x in args['relations']]
    node_ids = set(args['nodes'])
    allowed = {'functions': {'calls', 'unresolved-call'}, 'files': {'imports'}, 'logic': {'structure-next', 'structure-contains'}}[args['view']]
    for relation in relations:
        if relation['source'] not in node_ids or relation['target'] not in node_ids or relation['kind'] not in allowed:
            raise ValueError('关系端点不在当前图中，或混合了调用与结构关系')
    kinds = {'functions': {'function', 'method', 'constructor', 'lambda', 'class', 'call'},
             'files': {'file'}, 'logic': {'statement'}}[args['view']]
    if any(n['kind'] not in kinds for n in nodes):
        raise ValueError('此视图包含了不匹配的节点类型')
    groups, grouped = [], set()
    for index, group in enumerate(args.get('groups', [])):
        if not isinstance(group, dict) or set(group) != {'title', 'nodeIds'} or not isinstance(group['title'], str) or not 1 <= len(group['title']) <= 100:
            raise ValueError('阅读分组格式无效')
        ids = group['nodeIds']
        if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(x, str) or x not in node_ids or x in grouped for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('阅读分组包含未知或重复节点')
        grouped.update(ids)
        groups.append(dict(id=f'group:{index}', title=group['title'], nodeIds=ids))
    # Copy canonical facts, never accept AI edits to endpoints, statuses or ranges.
    return dict(version=1, title=args['title'], view=args['view'], nodes=nodes, relations=relations,
                groups=groups, explanation=args.get('explanation', ''), snapshotId=snapshot_id, runId=run_id)


def read_tool(store, name, args):
    validate_arguments(name, args, READ_TOOLS)
    conv = store.conversation(args['id'])
    if name == 'get_conversation':
        return store.history(args['id'], args.get('cursor', 0), args.get('limit', 100))
    if name == 'get_view':
        return dict(id=args['id'], view=conv['view'])
    # Membership prevents reading arbitrary snapshots by guessing a digest.
    with store.connect() as db:
        member = db.execute('SELECT 1 FROM runs WHERE conversation_id=? AND snapshot_id=? LIMIT 1',
                            (args['id'], args['snapshotId'])).fetchone()
    if not member:
        raise ValueError('此快照不属于该会话')
    return store.source(args['snapshotId'], args['path'], args.get('startLine', 1), args.get('endLine'))

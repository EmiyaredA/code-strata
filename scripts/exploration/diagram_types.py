"""Source-backed notation contracts; visual notation is distinct from evidence."""
KINDS = ('flowchart','swimlane','class','object','package','component','composite','deployment','profile','activity','state','usecase','sequence','communication','timing','interaction-overview')
CONTROL = {'action','decision','merge','start','end','fork','join','note'}
ROLES = {
 'flowchart': CONTROL | {'input','output','document','database'}, 'swimlane': CONTROL | {'lane'},
 'activity': CONTROL, 'interaction-overview': CONTROL | {'interaction'},
 'sequence': {'participant','actor','boundary','control','entity','note'},
 'communication': {'object','actor','note'}, 'timing': {'signal','state-event','note'},
 'class': {'class','interface','enum','package','note'},
 'object': {'object','note'}, 'package': {'package','class','interface','note'},
 'component': {'component','interface','package','note'},
 'composite': {'structured-class','part','port','interface','note'},
 'profile': {'profile','stereotype','metaclass','note'},
 'state': {'state','choice','start','end','fork','join','note'},
 'usecase': {'actor','usecase','system','note'},
 'deployment': {'device','execution','artifact','component','note'},
}
EDGE_TYPES = {
 'flowchart': {'flow'}, 'swimlane': {'flow'}, 'activity': {'flow'}, 'interaction-overview': {'flow'},
 'sequence': {'message','return','async','create','destroy'},
 'communication': {'message','return','async'}, 'timing': {'transition','message'},
 'class': {'association','dependency','inheritance','implementation','composition','aggregation'},
 'object': {'link'}, 'package': {'dependency','package-import','package-merge'},
 'component': {'association','dependency','implementation','composition','aggregation','communication'},
 'composite': {'connector','delegation','assembly','dependency'},
 'profile': {'extension','inheritance','dependency'},
 'state': {'transition','flow'}, 'usecase': {'association','include','extend','inheritance'},
 'deployment': {'communication','dependency','association','composition'},
}
EDGE_ROLES = set().union(*EDGE_TYPES.values())
CONTAINERS = {'class': {'package'}, 'package': {'package'}, 'component': {'package','component'},
 'deployment': {'device','execution'}, 'usecase': {'system'}, 'swimlane': {'lane'},
 'composite': {'structured-class','part'}, 'profile': {'profile'}, 'timing': {'signal'}}
NODE_FIELDS = {'classifier','slots','portKind','side','order','time','interaction'}

def node_details(node, kind, clean, text):
    allowed = {'object': {'classifier','slots'}, 'port': {'portKind','side'}, 'lane': {'order'},
               'state-event': {'order','time'}, 'interaction': {'interaction'}}.get(node['role'], set())
    if (set(node) & NODE_FIELDS) - allowed:
        raise ValueError('节点专用字段与图形角色不一致')
    for key in ('classifier','interaction'):
        if key in node: clean[key] = text(node[key], key, 300)
    if 'slots' in node:
        if not isinstance(node['slots'],list) or len(node['slots'])>100: raise ValueError('对象槽位无效')
        clean['slots'] = [text(s,'对象槽位',300) for s in node['slots']]
    for key in ('order','time'):
        if key in node:
            value=node[key]
            if type(value) not in ((int,) if key=='order' else (int,float)) or not 0<=value<=1000000:
                raise ValueError('顺序或时间值无效')
            clean[key]=value
    for key, values in [('portKind',('provided','required','bidirectional')),('side',('left','right','top','bottom'))]:
        if key in node:
            if node[key] not in values: raise ValueError('端口属性无效')
            clean[key]=node[key]
    if node['role']=='port' and 'portKind' not in clean: raise ValueError('端口需要 portKind')
    if node['role']=='state-event' and 'order' not in clean: raise ValueError('定时状态需要 order')
    if node['role']=='interaction' and 'interaction' not in clean: raise ValueError('交互引用需要 interaction')

def validate_notation(model):
    kind=model['type']; nodes=model['nodes']; by_id={n['id']:n for n in nodes}
    if kind=='swimlane':
        lanes=[n for n in nodes if n['role']=='lane']
        if not lanes or any(n['role']!='lane' and n.get('parentId') not in {l['id'] for l in lanes} for n in nodes):
            raise ValueError('泳道必须有责任分区，所有流程节点必须属于泳道')
        orders=[n.get('order',i) for i,n in enumerate(lanes)]
        if len(set(orders))!=len(orders): raise ValueError('泳道顺序不能重复')
    if kind=='timing':
        signals=[n for n in nodes if n['role']=='signal']
        events=[n for n in nodes if n['role']=='state-event']
        if not signals or not events: raise ValueError('定时图需要信号和有依据的状态事件')
        for signal in signals:
            items=[n for n in events if n.get('parentId')==signal['id']]
            if not items or len({n['order'] for n in items})!=len(items): raise ValueError('每个信号需要顺序唯一的状态事件')
        if any(n.get('parentId') not in {s['id'] for s in signals} for n in events): raise ValueError('状态事件缺少信号归属')
        if model.get('timeUnit'):
            if any('time' not in n for n in events): raise ValueError('真实时间轴的所有状态必须提供时间')
            for signal in signals:
                items=sorted((n for n in events if n['parentId']==signal['id']),key=lambda n:n['order'])
                if any(a['time']>=b['time'] for a,b in zip(items,items[1:])): raise ValueError('时间必须随状态顺序递增')
        elif any('time' in n for n in events): raise ValueError('时间数值必须附带 timeUnit 和源码依据')
    for edge in model['edges']:
        a,b=by_id[edge['source']],by_id[edge['target']]
        if a['role']=='lane' or b['role']=='lane': raise ValueError('流程边不能连接责任分区本身')
        if kind=='profile' and edge['role']=='extension' and (a['role']!='stereotype' or b['role']!='metaclass'):
            raise ValueError('Profile 扩展必须从 stereotype 指向 metaclass')
        if kind=='composite' and edge['role'] in ('assembly','delegation') and (a['role']!='port' or b['role']!='port'):
            raise ValueError('装配和委派连接必须连接端口')
        if kind=='timing' and (a['role']!='state-event' or b['role']!='state-event'):
            raise ValueError('定时关系必须连接状态事件')
    required = {'object': {'object'}, 'package': {'package'}, 'composite': {'structured-class'},
                'profile': {'profile'}, 'communication': {'object','actor'}, 'interaction-overview': {'interaction'}}
    if kind in required and not any(n['role'] in required[kind] for n in nodes):
        raise ValueError('图缺少对应类型的主要语义元素')
    for n in nodes:
        if n['role']=='port' and (not n.get('parentId') or by_id[n['parentId']]['role'] not in ('structured-class','part')):
            raise ValueError('端口必须归属结构化分类器或部件')
    if kind=='timing':
        for e in model['edges']:
            if e['role']=='transition':
                a,b=by_id[e['source']],by_id[e['target']]
                if a['parentId']!=b['parentId'] or a['order']>=b['order']:
                    raise ValueError('状态变化必须沿同一信号的时间顺序')

"""Deterministic, source-ID-preserving PlantUML adapters and restricted SVG."""
import hashlib
import re
import xml.etree.ElementTree as ET

VERSION = 1


class UnsupportedDiagram(ValueError):
    pass


def label(value):
    # Encode PlantUML/Creole control characters, rather than allowing labels to
    # introduce directives, markup, URLs, statements or additional diagrams.
    return ''.join('\\n' if c == '\n' else f'<U+{ord(c):04X}>' if c in '"\\[]{}<>@!#|:;~' or ord(c) < 32 else c for c in str(value or ''))


def serialize(model):
    if model.get('type') not in ('activity', 'sequence', 'class', 'component', 'state', 'usecase', 'deployment'):
        raise UnsupportedDiagram('旧版阅读图请使用交互视图')
    if len(model['nodes']) > 100 or len(model['edges']) > 300:
        raise ValueError('图超过 100 节点／300 关系预算')
    aliases = {n['id']: 'n'+str(i) for i, n in enumerate(model['nodes'])}
    mapping = {}

    def link(item):
        token = 'uml_' + hashlib.sha256(item['id'].encode()).hexdigest()[:24]
        mapping[token] = item['id']
        return '#'+token

    def title(item):
        return f'[[{link(item)} {label(item.get("label") or "查看依据")}]]'

    lines = ['@startuml', '!pragma layout smetana', 'skinparam backgroundColor transparent',
             'skinparam shadowing false', 'skinparam defaultFontName SansSerif',
             'skinparam defaultFontSize 13', 'skinparam hyperlinkColor #344763',
             'skinparam hyperlinkUnderline false', 'skinparam ArrowColor #7894B6',
             'skinparam roundcorner 8']
    kind = model['type']
    if kind == 'activity':
        lines += activity(model, title)
    elif kind == 'sequence':
        for n in model['nodes']:
            role = n['role'] if n['role'] in ('actor', 'boundary', 'control', 'entity') else 'participant'
            lines.append(f'{role} "{label(n["label"])}" as {aliases[n["id"]]} [[{link(n)}]]')
        for e in sorted(model['edges'], key=lambda x: x['order']):
            a, b = aliases[e['source']], aliases[e['target']]
            if e['role'] == 'create':
                # All lifelines are declared once; "create" references their alias.
                lines.append(f'create {b}')
            arrow = '-->' if e['role'] == 'return' else '->>' if e['role'] == 'async' else '->'
            style = '[#B17B26,dashed]' if e.get('status') in ('candidate', 'unresolved') else ''
            if style:
                arrow = '-'+style+('>>' if e['role'] == 'async' else '>')
            lines.append(f'{a} {arrow} {b} : [[{link(e)} {label(e.get("label") or "查看依据")}]]')
            if e['role'] == 'destroy':
                lines.append(f'destroy {b}')
    else:
        by_id = {n['id']: n for n in model['nodes']}
        children = {}
        for n in model['nodes']:
            children.setdefault(n.get('parentId'), []).append(n)

        def emit(n):
            role = n['role']
            alias = aliases[n['id']]
            if role in ('start', 'end'):
                # State pseudostates are addressed through [*], not a fake class.
                return
            keywords = {'system': 'rectangle', 'device': 'node', 'execution': 'node',
                        'choice': 'state', 'fork': 'state', 'join': 'state'}
            keyword = keywords.get(role, role)
            if keyword not in ('class', 'interface', 'enum', 'package', 'note', 'component', 'state', 'actor', 'usecase', 'rectangle', 'node', 'artifact'):
                raise UnsupportedDiagram('此元素暂不能无损转换为标准 UML：'+role)
            stereo = ' <<choice>>' if role == 'choice' else ' <<fork>>' if role == 'fork' else ' <<join>>' if role == 'join' else ' <<executionEnvironment>>' if role == 'execution' else ''
            declaration = f'{keyword} "{label(n["label"])}" as {alias}{stereo} [[{link(n)}]]'
            nested = children.get(n['id'], [])
            members = n.get('members', [])
            if nested or members:
                lines.append(declaration+' {')
                for member in members:
                    lines.append('  '+label(member))
                for child in nested:
                    emit(child)
                lines.append('}')
            else:
                lines.append(declaration)
        for n in children.get(None, []):
            emit(n)
        arrows = {'inheritance': '--|>', 'implementation': '..|>', 'composition': '*--', 'aggregation': 'o--',
                  'dependency': '..>', 'include': '..>', 'extend': '..>', 'association': '--', 'communication': '--', 'transition': '-->', 'flow': '-->'}
        for e in model['edges']:
            a = '[*]' if by_id[e['source']]['role'] == 'start' else aliases[e['source']]
            b = '[*]' if by_id[e['target']]['role'] == 'end' else aliases[e['target']]
            arrow = arrows[e['role']]
            if e.get('status') in ('candidate', 'unresolved'):
                arrow = '-[#B17B26,dashed]->'
            caption = label(e.get('label') or '查看依据')
            if e.get('guard'):
                caption = label('['+e['guard']+']')+' '+caption
            if e['role'] in ('include', 'extend'):
                caption = '<<'+e['role']+'>> '+caption
            # Linked captions work across state/component/deployment as well as
            # types; they also provide keyboard targets for otherwise bare edges.
            lines.append(f'{a} {arrow} {b} : [[{link(e)} {caption}]]')
    lines.append('@enduml')
    return dict(source='\n'.join(lines)+'\n', elements=mapping, converterVersion=VERSION)


def activity(model, title):
    """Compile reducible chains, choices, natural loops and fork/join regions.

    A failed structural proof is a visible unsupported state, not permission to
    redraw an arbitrary graph as a different execution order.
    """
    nodes = {n['id']: n for n in model['nodes']}
    if any(n.get('parentId') or n['role'] == 'note' for n in model['nodes']):
        raise UnsupportedDiagram('此活动图的注释／嵌套范围暂不能无损转换，请使用交互视图')
    outgoing, incoming = {k: [] for k in nodes}, {k: [] for k in nodes}
    for e in model['edges']:
        outgoing[e['source']].append(e)
        incoming[e['target']].append(e)
    roots = [k for k in nodes if not incoming[k]]
    if len(roots) != 1:
        raise UnsupportedDiagram('活动图需要唯一入口；原始拓扑已保留在交互视图')
    rendered, emitted = set(), set()
    result = []

    def edge(e):
        emitted.add(e['id'])
        text = dict(e, label=e.get('guard') or e.get('label') or '查看依据')
        return title(text)

    def distances(start, stop=None):
        found, queue = {}, [(start, 0)]
        while queue:
            k, distance = queue.pop(0)
            if k in found or k == stop:
                continue
            found[k] = distance
            queue += [(e['target'], distance+1) for e in outgoing[k]]
        return found

    def run(k, stop=None):
        while k is not None and k != stop:
            if k in rendered:
                raise UnsupportedDiagram('活动图存在非结构化回边，请使用交互视图')
            n, links = nodes[k], outgoing[k]
            rendered.add(k)
            if n['role'] in ('decision', 'fork'):
                if len(links) != 2 and n['role'] == 'decision' or len(links) < 2:
                    raise UnsupportedDiagram('活动分支需要可识别的分支与汇合')
                reaches = [distances(e['target'], k) for e in links]
                # A natural pre-test loop has exactly one successor reaching its
                # decision again; compile it only when the other cannot reach it.
                loops = [i for i,e in enumerate(links) if k in distances(e['target'])]
                if n['role'] == 'decision' and len(loops) == 1:
                    i = loops[0]; body, after = links[i], links[1-i]
                    result.append(f'while ({title(n)}) is ({edge(body)})')
                    run(body['target'], k)
                    result.append(f'endwhile ({edge(after)})')
                    k = after['target']; continue
                common = set.intersection(*(set(r) for r in reaches))
                join = min(common, key=lambda x: (max(r[x] for r in reaches), sum(r[x] for r in reaches), x)) if common else None
                if join and nodes[join]['role'] not in ('merge', 'join', 'end', 'action'):
                    raise UnsupportedDiagram('活动分支的汇合位置不明确')
                if n['role'] == 'decision':
                    result.append(f'if ({title(n)}) then ({edge(links[0])})')
                    run(links[0]['target'], join)
                    result.append(f'else ({edge(links[1])})')
                    run(links[1]['target'], join)
                    result.append('endif')
                else:
                    for i,e in enumerate(links):
                        result.append('fork' if i == 0 else 'fork again')
                        result.append('-> '+edge(e)+';')
                        run(e['target'], join)
                    result.append('end fork')
                k = join; continue
            if n['role'] == 'start':
                result.append('start')
            elif n['role'] == 'end':
                if links:
                    raise UnsupportedDiagram('结束节点仍有后继，不能无损转换')
                result.append('stop')
            elif n['role'] in ('merge', 'join'):
                # Structural symbol already represented by endif/end fork.
                pass
            else:
                result.append(':'+title(n)+';')
            if len(links) > 1:
                raise UnsupportedDiagram('普通活动有多个后继，请补充明确的决策或并行语义')
            if not links:
                k = None
            else:
                e = links[0]
                result.append('-> '+edge(e)+';')
                k = e['target']
    run(roots[0])
    if rendered != set(nodes) or emitted != {e['id'] for e in model['edges']}:
        raise UnsupportedDiagram('此活动拓扑暂不能完整表达，已保留交互视图')
    return result


SVG_TAGS = {'svg','g','defs','marker','path','rect','circle','ellipse','line','polyline','polygon','text','tspan','a','title','desc','clipPath','linearGradient','stop'}
SVG_ATTRS = {'id','class','viewBox','width','height','x','y','x1','x2','y1','y2','cx','cy','r','rx','ry','d','points','transform','fill','fill-opacity','stroke','stroke-width','stroke-dasharray','stroke-linecap','stroke-linejoin','opacity','font-family','font-size','font-weight','font-style','text-anchor','textLength','lengthAdjust','preserveAspectRatio','dominant-baseline','style','refX','refY','markerWidth','markerHeight','orient','marker-end','marker-start','offset','stop-color','stop-opacity','clip-path'}


def sanitize_svg(raw, elements):
    if len(raw) > 8_000_000 or re.search(r'<!DOCTYPE|<!ENTITY', raw, re.I):
        raise ValueError('SVG 内容无效或超过预算')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('渲染器未返回 SVG')
    for parent in root.iter():
        for child in list(parent):
            if child.tag.split('}')[-1] not in SVG_TAGS:
                parent.remove(child)
        for key in list(parent.attrib):
            name = key.split('}')[-1]
            value = parent.attrib[key]
            if name == 'href':
                if value.startswith('#') and value[1:] in elements:
                    parent.attrib['data-element'] = elements[value[1:]]
                    parent.attrib['tabindex'] = '0'
                    parent.attrib['role'] = 'button'
                    parent.attrib['aria-label'] = '查看 UML 元素源码'
                del parent.attrib[key]
            elif name not in SVG_ATTRS or re.search(r'url\(\s*(?!#[\w-]+\))|javascript:|expression\(|@import|https?:|file:', value, re.I):
                del parent.attrib[key]
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    return ET.tostring(root, encoding='unicode')

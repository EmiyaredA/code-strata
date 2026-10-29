"""Authenticated application routes; the run tool bridge has a separate capability."""
import re
from urllib.parse import parse_qs

from .service import ConflictError
from .diagrams import DiagramConflict
from .tools import read_tool

DIAGRAM = re.compile(r'/api/explore/diagrams/([a-f0-9]{32})(?:/(versions|source|check|source-map|render))?')

CONVERSATION = re.compile(r'/api/explore/conversations/([a-f0-9]{32})(?:/(messages|cancel|check))?')


def handles(path):
    return path in ('/api/explore/conversations', '/api/explore/read', '/api/explore/uml-runtime') or path in ('/api/explore/diagrams', '/api/explore/diagrams/drafts', '/api/explore/diagrams/check') or bool(DIAGRAM.fullmatch(path)) or bool(CONVERSATION.fullmatch(path))


def dispatch(service, method, path, current, body=None, query=''):
    try:
        if path == '/api/explore/uml-runtime':
            if method == 'GET':
                return 200, service.uml_runtime.status()
            if method == 'POST' and body == {'install': True}:
                return 202, service.uml_runtime.install()
            raise ValueError('运行时安装参数无效')
        if path.startswith('/api/explore/diagrams'):
            if not current or not current.get('project', {}).get('root'):
                return 422, dict(error='请先打开本地项目')
            project = current['project']['root']
            params = parse_qs(query)
            if path == '/api/explore/diagrams' and method == 'GET':
                return 200, service.store.list_diagrams(project, int(params.get('offset', ['0'])[0]), int(params.get('limit', ['50'])[0]))
            if path == '/api/explore/diagrams/check' and method == 'POST':
                items = body.get('diagrams')
                if not isinstance(items,list) or len(items)>100:
                    raise ValueError('每次最多检查 100 张图')
                cache, checks = {}, []
                for item in items:
                    if not isinstance(item,dict) or set(item)-{'id','revision'}:
                        raise ValueError('检查参数无效')
                    checks.append(service.store.check_diagram(project,item.get('id'),item.get('revision'),cache))
                return 200,dict(checks=checks)
            if path == '/api/explore/diagrams/drafts' and method == 'GET':
                return 200, dict(drafts=service.store.diagram_drafts(project))
            match = DIAGRAM.fullmatch(path)
            if not match:
                return 405, dict(error='不支持的图操作')
            identifier, action = match.groups()
            revision = int(params['revision'][0]) if 'revision' in params else None
            if revision is not None and revision < 1:
                raise ValueError('版本号无效')
            if not action and method == 'GET':
                return 200, service.store.diagram(project, identifier, revision)
            if action == 'versions' and method == 'GET':
                return 200, dict(versions=service.store.diagram_versions(project, identifier))
            if action == 'source' and method == 'POST':
                return 200, service.store.diagram_source(project, identifier, body.get('revision'), body.get('path'), body.get('startLine', 1), body.get('endLine'))
            if action == 'source-map' and method == 'GET':
                return 200, service.source_maps.get(project, identifier, revision, params.get('retry') == ['1'])
            if action == 'render' and method == 'POST':
                if set(body) != {'revision'} or type(body['revision']) is not int or body['revision'] < 1:
                    raise ValueError('渲染只接受已保存的图版本')
                document = service.store.diagram(project, identifier, body['revision'])
                return 200, service.uml_runtime.render(document)
            if action == 'check' and method == 'POST':
                return 200, service.store.check_diagram(project, identifier, body.get('revision'))
            return 405, dict(error='不支持的图操作')
        if path == '/api/explore/conversations':
            if not current or not current.get('project', {}).get('root'):
                return 422, dict(error='请先打开本地项目')
            project = current['project']['root']
            if method == 'GET':
                return 200, dict(conversations=service.store.list(project))
            if set(body) - {'agentId', 'title'}:
                raise ValueError('创建会话参数无效')
            return 201, service.create(project, body.get('agentId'), body.get('title', '新的代码阅读'))
        if path == '/api/explore/read' and method == 'POST':
            return 200, read_tool(service.store, body.get('name'), body.get('arguments'))
        match = CONVERSATION.fullmatch(path)
        if not match:
            return 404, dict(error='会话接口不存在')
        identifier, action = match.groups()
        if method == 'GET' and not action:
            cursor = int(parse_qs(query).get('cursor', ['0'])[0])
            return 200, service.detail(identifier, cursor)
        if method == 'POST':
            if action == 'messages':
                if set(body) - {'text', 'update', 'diagramId', 'expectedRevision'}:
                    raise ValueError('发送参数无效；会话的 Agent 不可更改')
                return 202, service.start(identifier, body.get('text'), body.get('update', False),
                    current.get('mappingPath') if current else None, body.get('diagramId'), body.get('expectedRevision'))
            if action == 'cancel':
                return 200, service.cancel(identifier)
            if action == 'check':
                return 202, service.check(identifier)
        return 405, dict(error='不支持的会话操作')
    except LookupError as exc:
        return 404, dict(error=str(exc))
    except (ConflictError, DiagramConflict) as exc:
        return 409, dict(error=str(exc))
    except (ValueError, TypeError) as exc:
        return 422, dict(error=str(exc))

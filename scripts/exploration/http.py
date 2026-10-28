"""Authenticated application routes; the run tool bridge has a separate capability."""
import re
from urllib.parse import parse_qs

from .service import ConflictError
from .tools import read_tool

CONVERSATION = re.compile(r'/api/explore/conversations/([a-f0-9]{32})(?:/(messages|cancel|check))?')


def handles(path):
    return path in ('/api/explore/conversations', '/api/explore/read') or bool(CONVERSATION.fullmatch(path))


def dispatch(service, method, path, current, body=None, query=''):
    try:
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
                if set(body) - {'text', 'update'}:
                    raise ValueError('发送参数无效；会话的 Agent 不可更改')
                return 202, service.start(identifier, body.get('text'), body.get('update', False),
                    current.get('mappingPath') if current else None)
            if action == 'cancel':
                return 200, service.cancel(identifier)
            if action == 'check':
                return 202, service.check(identifier)
        return 405, dict(error='不支持的会话操作')
    except LookupError as exc:
        return 404, dict(error=str(exc))
    except ConflictError as exc:
        return 409, dict(error=str(exc))
    except (ValueError, TypeError) as exc:
        return 422, dict(error=str(exc))

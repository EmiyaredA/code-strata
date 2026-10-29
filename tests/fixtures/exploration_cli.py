"""Native protocol fixture exercising the real MCP bridge, without an LLM."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
mode = os.environ.get('STRATA_EXPLORATION_FIXTURE', 'success')
if args == ['--version']:
    print('exploration-fixture 1.0')
    raise SystemExit


def emit(value):
    print(json.dumps(value), flush=True)


def tools():
    script = os.environ['STRATA_EXPLORATION_MCP']
    with subprocess.Popen([sys.executable, script, '--stdio'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
        serial = 0
        def rpc(method, params):
            nonlocal serial
            serial += 1
            child.stdin.write(json.dumps(dict(jsonrpc='2.0', id=serial, method=method, params=params)) + '\n')
            child.stdin.flush()
            response = json.loads(child.stdout.readline())
            assert response['id'] == serial and 'error' not in response, response
            return response['result']
        rpc('initialize', dict(protocolVersion='2024-11-05'))
        names = [item['name'] for item in rpc('tools/list', {})['tools']]
        assert 'save_view' in names and 'get_conversation' not in names
        def call(name, arguments):
            if args[:2] == ['--profile', 'acp']:
                emit(dict(jsonrpc='2.0', method='session/update', params=dict(sessionId='fixture-acp-session',
                    update=dict(sessionUpdate='tool_call', toolCallId='fixture-tool', title='mcp__strata__' + name))))
                emit(dict(jsonrpc='2.0', id='tool-permission', method='session/request_permission', params=dict(
                    toolCall=dict(toolCallId='fixture-tool'), options=[dict(optionId='once', kind='allow_once')])))
                assert json.loads(sys.stdin.readline())['result']['outcome'] == dict(outcome='selected', optionId='once')
            result = rpc('tools/call', dict(name=name, arguments=arguments))
            assert not result.get('isError'), result
            return json.loads(result['content'][0]['text'])
        found = call('search_code', dict(text='complete'))
        focus = next(n for n in found['nodes'] if n['kind'] == 'function' and n['name'] == 'complete'
                     and (not os.environ.get('STRATA_EXPLORATION_TS') or n['path'].endswith('.ts')))
        graph = call('query_code', dict(view='functions', focusId=focus['id'], hops=2))
        source = call('read_source', dict(path=focus['path'], startLine=1, endLine=12))
        view = dict(title='完成处理的调用关系', view='functions', nodes=[n['id'] for n in graph['nodes']],
                    relations=[r['id'] for r in graph['relations']], explanation='入口调用校验函数，边均来自源码。')
        if mode.startswith('uml'):
            docs = []
            for kind, roles in [('activity', ('action', 'action', 'flow')), ('sequence', ('participant', 'participant', 'message'))]:
                docs.append(dict(type=kind, title='完成处理 '+kind, purpose='核对真实 MCP 生成和多图原子发布。',
                    nodes=[dict(id=n, label=n, role=role, evidenceIds=[source['evidenceId']], explanation='依据已读取的函数源码。') for n,role in zip(('complete','validate'),roles[:2])],
                    edges=[dict(id='call', source='complete', target='validate', role=roles[2], evidenceIds=[source['evidenceId']], explanation='源码推导。', order=0)]))
            if os.environ.get('STRATA_EXPLORATION_DIAGRAM'):
                target = call('get_diagram', dict(diagramId=os.environ['STRATA_EXPLORATION_DIAGRAM']))
                docs = docs[:1]
                docs[0].update(id=target['id'],expectedRevision=target['revision'])
            call('save_diagrams', dict(diagrams=docs))
        elif mode == 'invalid':
            view['relations'] = ['fabricated-call']
            result = rpc('tools/call', dict(name='save_view', arguments=view))
            assert result['isError']
        else:
            call('save_view', view)
        child.stdin.close()
        child.wait(timeout=3)
    if mode in ('hold', 'uml_hold'):
        time.sleep(30)
    if mode in ('failure', 'uml_failure'):
        raise RuntimeError('failure after graph draft')


if args[:2] == ['--profile', 'acp']:
    session = 'fixture-acp-session'
    for raw in sys.stdin:
        message = json.loads(raw)
        method = message['method']
        if method == 'initialize':
            result = dict(agentCapabilities=dict(sessionCapabilities=dict(resume={})))
        elif method in ('session/new', 'session/load', 'session/resume'):
            assert message['params']['mcpServers'][0]['name'] == 'strata'
            result = dict(sessionId=session)
        elif method == 'session/prompt':
            tools()
            emit(dict(jsonrpc='2.0', method='session/update', params=dict(sessionId=session,
                 update=dict(sessionUpdate='agent_message_chunk', content=dict(type='text', text='已查询源码并生成阅读图。')))))
            result = dict(stopReason='end_turn')
        else:
            result = {}
        if 'id' in message:
            emit(dict(jsonrpc='2.0', id=message['id'], result=result))
elif args[:2] == ['--mode', 'rpc']:
    assert '--extension' in args and 'save_view' in args[args.index('--tools')+1]
    for raw in sys.stdin:
        message = json.loads(raw)
        if message['type'] == 'get_state':
            emit(dict(type='response', command='get_state', id=message['id'], success=True, data=dict(sessionId='fixture-pi-session')))
        elif message['type'] == 'prompt':
            tools()
            emit(dict(type='message_update', assistantMessageEvent=dict(type='text_delta', delta='已查询源码并生成阅读图。')))
            emit(dict(type='agent_end', willRetry=False))
            emit(dict(type='agent_settled', aborted=False))
else:
    prompt = sys.stdin.read()
    assert '本轮唯一源码快照' in prompt
    tools()
    if args[0] == 'exec':
        assert '--ephemeral' not in args and any('mcp_servers=' in a for a in args)
        emit(dict(type='thread.started', thread_id='fixture-codex-session'))
        emit(dict(type='item.completed', item=dict(type='agent_message', text='已查询源码并生成阅读图。')))
        emit(dict(type='turn.completed'))
    elif args[0] == 'run':
        assert json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])['mcp']['strata']['enabled']
        emit(dict(type='text', sessionID='fixture-opencode-session', part=dict(text='已查询源码并生成阅读图。')))
        emit(dict(type='step_finish', part=dict(reason='stop')))
    else:
        assert '--strict-mcp-config' in args and 'strata' in args[args.index('--mcp-config') + 1]
        emit(dict(type='assistant', session_id='fixture-claude-session', message=dict(content=[dict(type='text', text='已查询源码并生成阅读图。')])))
        emit(dict(type='result', subtype='success', is_error=False))

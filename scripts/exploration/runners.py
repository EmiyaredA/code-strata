"""Native CLI transports. Only real process output is forwarded to the chat."""
import json
from pathlib import Path
import re
import sys

from agents.acp import AcpTest
from agents.adapters import failure
from agents.runtime import AgentError, Process
from .tools import RUN_TOOLS

SCRIPTS = Path(__file__).resolve().parents[1]


def mcp_config(env):
    return dict(command=sys.executable, args=[str(SCRIPTS / 'exploration_mcp.py'), '--stdio'],
                env={key: env[key] for key in ('CODE_STRATA_TOOL_URL', 'CODE_STRATA_RUN_ID', 'CODE_STRATA_TOOL_TOKEN')})


def toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + '=' + toml(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(toml(x) for x in value) + ']'
    return json.dumps(value)


def arguments(agent, config, native_id, env, session_dir):
    model, params = config['model'], config.get('parameters', {})
    server = mcp_config(env)
    if agent == 'codex':
        args = ['exec', *(['resume'] if native_id else []), '--json', '--skip-git-repo-check',
                '-c', 'sandbox_mode="read-only"', '-c', 'features.shell_tool=false', '-c', 'features.unified_exec=false',
                '-c', 'mcp_servers=' + toml({'strata': server})]
        for key, option in (('reasoningEffort', 'model_reasoning_effort'), ('serviceTier', 'service_tier')):
            if params.get(key):
                args += ['-c', option + '=' + toml(params[key])]
        if model:
            args += ['--model', model]
        return args + ([native_id] if native_id else []) + ['-']
    if agent == 'opencode':
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(dict(mcp={'strata': dict(type='local',
            command=[server['command'], *server['args']], environment=server['env'], enabled=True)},
            permission={'*': 'deny', 'strata_*': 'allow'}))
        args = ['run', '--format', 'json']
        if native_id:
            args += ['--session', native_id]
        if model:
            args += ['--model', model]
        if params.get('variant'):
            args += ['--variant', params['variant']]
        return args
    if agent == 'claude':
        args = ['-p', '--verbose', '--output-format', 'stream-json', '--tools', '',
                '--strict-mcp-config', '--mcp-config', json.dumps({'mcpServers': {'strata': server}}),
                '--allowedTools', 'mcp__strata__*']
        if native_id:
            args += ['--resume', native_id]
        if model:
            args += ['--model', model]
        if params.get('reasoningEffort'):
            args += ['--effort', params['reasoningEffort']]
        if params.get('fastMode'):
            args += ['--settings', json.dumps({'fastMode': params['fastMode'] == 'true'})]
        return args
    if agent == 'pi':
        env['CODE_STRATA_TOOL_DEFINITIONS'] = json.dumps(RUN_TOOLS, ensure_ascii=False)
        args = ['--mode', 'rpc', '--tools', ','.join(t['name'] for t in RUN_TOOLS), '--no-mcp', '--no-extensions', '--no-skills', '--no-prompt-templates',
                '--extension', str(SCRIPTS / 'exploration/pi-tools.ts'),
                '--session', str(session_dir / 'pi-session.jsonl')]
        if model:
            args += ['--model', model]
        if params.get('thinking'):
            args += ['--thinking', params['thinking']]
        return args
    return ['--profile', 'acp']


class AcpRun(AcpTest):
    """Reuse model/config negotiation, with real conversation text and MCP tools."""
    def __init__(self, process, cwd, on_text, on_native):
        super().__init__(process, cwd)
        self.on_text, self.on_native = on_text, on_native
        self.tool_names = {}
        self.active_prompt = False

    def call(self, method, params):
        # AcpTest.call handles requests/updates, but calls below use the full
        # reader to stream text and reject filesystem/terminal client requests.
        expected = self.send(method, params)
        while True:
            record = self.process.read()
            if record is None:
                if len(self.process.eof) == 2:
                    raise AgentError('protocol', 'ACP 在完成前退出')
                continue
            if record[0] != 'stdout':
                continue
            clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', record[1]).strip()
            if not clean or re.match(r'^\[[A-Za-z0-9_.:-]+\]\s', clean):
                continue
            message = json.loads(clean)
            if message.get('method') == 'session/update':
                update = (message.get('params') or {}).get('update') or {}
                if update.get('sessionUpdate') == 'tool_call':
                    self.tool_names[update.get('toolCallId')] = update.get('title')
                if self.active_prompt and update.get('sessionUpdate') == 'agent_message_chunk':
                    content = update.get('content') or {}
                    if content.get('type') == 'text':
                        self.text += content.get('text', '')
                        self.on_text(self.text)
            elif 'method' in message and 'id' in message:
                if message['method'] == 'session/request_permission':
                    params = message.get('params') or {}
                    name = self.tool_names.get((params.get('toolCall') or {}).get('toolCallId'))
                    option = next((x for x in params.get('options', []) if x.get('kind') == 'allow_once'), None)
                    known = name in {'mcp__strata__' + t['name'] for t in RUN_TOOLS}
                    outcome = dict(outcome='selected', optionId=option['optionId']) if known and option else dict(outcome='cancelled')
                    self.process.send(json.dumps(dict(jsonrpc='2.0', id=message['id'], result={'outcome': outcome})) + '\n')
                else:
                    self.process.send(json.dumps(dict(jsonrpc='2.0', id=message['id'], error={'code': -32601, 'message': 'Use code-strata snapshot tools'})) + '\n')
            elif message.get('id') == expected:
                if 'error' in message:
                    raise failure(json.dumps(message['error']))
                return message.get('result') or {}

    def run_conversation(self, config, native_id, env, prompt):
        initialized = self.call('initialize', {'protocolVersion': 1, 'clientCapabilities': {},
            'clientInfo': {'name': 'code-strata', 'version': '1'}})
        server = mcp_config(env)
        servers = [dict(name='strata', command=server['command'], args=server['args'],
                        env=[dict(name=k, value=v) for k, v in server['env'].items()])]
        params = dict(cwd=self.cwd, mcpServers=servers)
        capabilities = initialized.get('agentCapabilities', {})
        if native_id and 'resume' in capabilities.get('sessionCapabilities', {}):
            created = self.call('session/resume', dict(params, sessionId=native_id))
            self.session = native_id
        elif native_id and capabilities.get('loadSession'):
            created = self.call('session/load', dict(params, sessionId=native_id))
            self.session = native_id
        else:
            created = self.call('session/new', params)
            self.session = created.get('sessionId')
        if not self.session:
            raise AgentError('protocol', 'ACP 未返回会话 ID')
        self.on_native(self.session)
        if config['model']:
            self.set_model(created, config['model'])
        effort = config.get('parameters', {}).get('reasoningEffort')
        if effort:
            selector = next((x for x in created.get('configOptions', []) if x.get('category') == 'thought_level' or x.get('id') == 'reasoning_effort'), None)
            if selector:
                self.call('session/set_config_option', dict(sessionId=self.session, configId=selector['id'], value=effort))
        self.text, self.active_prompt = '', True
        result = self.call('session/prompt', dict(sessionId=self.session, prompt=[dict(type='text', text=prompt)]))
        if result.get('stopReason') != 'end_turn':
            raise AgentError('response', 'Agent 未正常完成本轮对话')


def execute(agent, launch, config, native_id, cwd, session_dir, prompt, cancel, on_text, on_native, timeout=900):
    env = launch['env']
    args = arguments(agent, config, native_id, env, session_dir)
    process = Process(launch, args, cwd, cancel, timeout, max_output=8*1024*1024, max_line=1024*1024)
    try:
        if agent == 'dsh':
            acp = AcpRun(process, cwd, on_text, on_native)
            try:
                acp.run_conversation(config, native_id, env, prompt)
            finally:
                acp.cleanup()
            return
        if agent == 'pi':
            process.send(json.dumps(dict(id='state', type='get_state')) + '\n')
            process.send(json.dumps(dict(id='prompt', type='prompt', message=prompt)) + '\n')
        else:
            process.send(prompt)
            process.finish_input()
        text, completed, errors = '', False, []
        while len(process.eof) < 2 or process.child.poll() is None:
            record = process.read()
            if record is None:
                continue
            if record[0] != 'stdout' or not record[1].strip():
                continue
            try:
                event = json.loads(record[1])
            except ValueError:
                continue
            kind = event.get('type')
            chunk = None
            if agent == 'codex':
                if kind == 'thread.started':
                    on_native(event.get('thread_id'))
                if kind == 'item.completed' and (event.get('item') or {}).get('type') == 'agent_message':
                    chunk = event['item'].get('text', '')
                completed = completed or kind == 'turn.completed'
                if kind in ('error', 'turn.failed'):
                    errors.append(event)
            elif agent == 'opencode':
                if event.get('sessionID'):
                    on_native(event['sessionID'])
                if kind == 'text':
                    chunk = (event.get('part') or {}).get('text', '')
                if kind == 'step_finish':
                    reason = (event.get('part') or {}).get('reason')
                    completed = reason in ('stop', 'end_turn')
                if kind == 'error':
                    errors.append(event)
            elif agent == 'claude':
                if event.get('session_id'):
                    on_native(event['session_id'])
                if kind == 'assistant':
                    chunk = '\n'.join(x.get('text', '') for x in event.get('message', {}).get('content', []) if x.get('type') == 'text')
                if kind == 'result':
                    completed = not event.get('is_error') and event.get('subtype') == 'success'
                    if not completed:
                        errors.append(event)
            else:
                if kind == 'response' and event.get('command') == 'get_state':
                    on_native((event.get('data') or {}).get('sessionId'))
                if kind == 'message_update':
                    change = event.get('assistantMessageEvent') or {}
                    if change.get('type') == 'text_delta':
                        text += change.get('delta', '')
                        on_text(text)
                if kind == 'message_end':
                    message = event.get('message') or {}
                    if message.get('role') == 'assistant' and message.get('stopReason') in ('error', 'aborted'):
                        errors.append(message)
                if kind == 'response' and event.get('success') is False:
                    raise failure(json.dumps(event, ensure_ascii=False))
                if kind == 'agent_settled':
                    completed = not event.get('aborted')
                    break
            if chunk:
                text += ('\n\n' if text else '') + chunk
                on_text(text)
        if errors or (agent != 'pi' and process.child.returncode):
            raise failure(json.dumps(errors, ensure_ascii=False) + json.dumps(process.diagnostics()))
        if not completed:
            raise AgentError('protocol', 'CLI 未返回完整的完成事件')
    except Exception as exc:
        # Retain bounded real diagnostics for the app's expandable error record.
        exc.details = process.diagnostics()
        raise
    finally:
        process.close()

#!/usr/bin/env python3
"""Code Strata tools over MCP stdio. Without run credentials exposes history reads only."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exploration.store import Store
from exploration.tools import READ_TOOLS, RUN_TOOLS, read_tool, validate_arguments

MAX_MESSAGE = 131072


def invoke(name, arguments, store=None):
    url, run_id, token = (os.environ.get(k) for k in ('CODE_STRATA_TOOL_URL', 'CODE_STRATA_RUN_ID', 'CODE_STRATA_TOOL_TOKEN'))
    if url and run_id and token:
        validate_arguments(name, arguments, RUN_TOOLS)
        request = Request(url + '/api/explore/tools', data=json.dumps(dict(runId=run_id, name=name, arguments=arguments)).encode(),
                          headers={'Content-Type': 'application/json', 'X-Code-Strata-Run': token})
        try:
            with urlopen(request, timeout=120) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                message = json.load(exc).get('error', '工具调用失败')
            finally:
                exc.close()
            raise ValueError(message) from None
    return read_tool(store or Store(readonly=True), name, arguments)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--database', help='应用历史 SQLite 路径；省略使用 XDG 数据目录')
    cli.add_argument('--stdio', action='store_true', help='启动 MCP stdio 服务')
    cli.add_argument('--call', help='直接调用一个只读历史工具，参数为 --arguments JSON')
    cli.add_argument('--arguments', default='{}')
    args = cli.parse_args(argv)
    store = Store(args.database, readonly=True)
    if args.call:
        print(json.dumps(read_tool(store, args.call, json.loads(args.arguments)), ensure_ascii=False))
        return
    tools = RUN_TOOLS if all(os.environ.get(k) for k in ('CODE_STRATA_TOOL_URL', 'CODE_STRATA_RUN_ID', 'CODE_STRATA_TOOL_TOKEN')) else READ_TOOLS
    while True:
        raw = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not raw:
            break
        if len(raw) > MAX_MESSAGE:
            return
        request = None
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or 'id' not in request:
                continue
            method, params = request.get('method'), request.get('params') or {}
            if method == 'initialize':
                result = dict(protocolVersion=params.get('protocolVersion', '2024-11-05'),
                              capabilities=dict(tools={}), serverInfo=dict(name='code-strata', version='1.0.0'))
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = dict(tools=tools)
            elif method == 'tools/call':
                try:
                    value = invoke(params.get('name'), params.get('arguments', {}), store)
                    result = dict(content=[dict(type='text', text=json.dumps(value, ensure_ascii=False))], isError=False)
                except (ValueError, LookupError, OSError) as exc:
                    result = dict(content=[dict(type='text', text=str(exc))], isError=True)
            else:
                print(json.dumps(dict(jsonrpc='2.0', id=request['id'], error=dict(code=-32601, message='Unknown method'))), flush=True)
                continue
            response = dict(jsonrpc='2.0', id=request['id'], result=result)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            response = dict(jsonrpc='2.0', id=request.get('id') if isinstance(request, dict) else None,
                            error=dict(code=-32602, message=str(exc)))
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

"""Independent source syntax checks: a successful CPG exit is not a parse guarantee."""

import ast
import json
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from node_runtime import resolve_node


def syntax_checks(languages,configs):
    diagnostics=[]
    for path,content in languages['python'].items():
        try:
            ast.parse(content,filename=path)
        except SyntaxError as exc:
            diagnostics.append(dict(language='python',kind='syntax',path=path,line=exc.lineno,message=exc.msg))
    python=dict(status='checked',grammar=sys.version.split()[0])
    javascript=dict(status='no-input')
    if languages['javascript']:
        runtime=resolve_node()
        javascript=dict(status='unavailable',runtime=runtime)
        if runtime['status']=='ready':
            parser=Path(__file__).resolve().parents[1]/'parse-js.cjs'
            command=[runtime['executable'],str(parser)]
            if platform.system()=='Darwin':
                command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',*command]
            try:
                result=subprocess.run(command,input=json.dumps(dict(files=[dict(id=p,content=c) for p,c in languages['javascript'].items()],configs=configs)),capture_output=True,text=True,check=True,timeout=60)
                parsed=json.loads(result.stdout)
                diagnostics.extend(dict(language='javascript',**d) for d in parsed['diagnostics'] if d['kind']=='syntax')
                javascript=dict(status='checked',runtime=runtime,grammar='bundled TypeScript parser')
            except (OSError,ValueError,subprocess.SubprocessError) as exc:
                javascript['reason']=str(exc)
    return dict(python=python,javascript=javascript,diagnostics=diagnostics,
                purpose='Independent syntax evidence only; does not measure Joern semantic correctness.')

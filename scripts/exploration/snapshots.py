"""Immutable scan inputs, including the exact analyzer implementation."""
import hashlib
from pathlib import Path
import sys

from scan import scan_project
from .store import encoded

SCRIPTS = Path(__file__).resolve().parents[1]


def fingerprint(data):
    digest = hashlib.sha256(encoded(dict(project=data['project']['root'],
        analysis=data['snapshot']['analysisInputHash'], mapping=data['snapshot'].get('mappingHash'),
        python=sys.version, contract=2)).encode())
    for name in ('scan.py', 'inventory.py', 'parse-js.cjs', 'analyze-code.cjs',
                 'code_analysis/model.py', 'code_analysis/service.py', 'code_analysis/python_engine.py', 'code_analysis/worker.py'):
        artifact = SCRIPTS / name
        digest.update(name.encode() + b'\0' + artifact.read_bytes())
    return digest.hexdigest()


def capture(project, mapping=None, node=None, scc=None, work_dir=None):
    context = {}
    data = scan_project(project, mapping, node, scc, work_dir, snapshot_context=context)
    identifier = fingerprint(data)
    data['snapshot']['id'] = identifier
    context['snapshotId'] = identifier
    return identifier, data, context

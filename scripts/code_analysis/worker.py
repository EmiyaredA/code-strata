"""Isolated Python language worker, JSON stdin/stdout only."""
import json
import sys
try:
    import resource
except ImportError:
    resource = None
from .python_engine import analyze, logic


def main():
    request = json.load(sys.stdin)
    result = logic(request['files'][0], request['function']) if request.get('mode') == 'logic' else analyze(request['files'])
    result['resources'] = dict(peakRssBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024) if resource else None)
    result['engine'] = dict(name='python-ast-symtable', version=sys.version.split()[0])
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == '__main__':
    main()

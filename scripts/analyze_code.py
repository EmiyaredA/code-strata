"""Export optional source-only semantic indexes independently of the scan JSON."""
import argparse
import json
from pathlib import Path
from scan import scan_project
from code_analysis.service import CodeSession

if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--project', required=True)
    cli.add_argument('--node')
    cli.add_argument('--scc')
    cli.add_argument('--mapping')
    cli.add_argument('--work-dir')
    cli.add_argument('--output', required=True)
    cli.add_argument('--view', choices=['files','functions','logic','references','search','symbols'], help='只导出一个有界视图；省略时导出完整索引')
    cli.add_argument('--focus', help='文件路径或搜索结果中的对象 ID')
    cli.add_argument('--query', help='search 视图的关键词')
    cli.add_argument('--offset', type=int, default=0)
    args = cli.parse_args()
    context = {}
    data = scan_project(args.project, args.mapping, args.node, args.scc, args.work_dir, snapshot_context=context)
    session = CodeSession(data, context)
    model = session.export()
    if args.view:
        request = dict(view=args.view, offset=args.offset)
        if args.focus: request['focusId'] = args.focus
        if args.query: request['text'] = args.query
        model = session.query(request)
    Path(args.output).write_text(json.dumps(model, ensure_ascii=False), encoding='utf8')
    print(json.dumps(dict(output=args.output, status=model['status'], nodes=len(model['nodes']), relations=len(model['relations']), engines=model.get('engines',session.metrics)), ensure_ascii=False))
    raise SystemExit(1 if model['status'] == 'failed' else 0)

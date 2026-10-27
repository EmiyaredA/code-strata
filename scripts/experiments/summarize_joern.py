"""Package measured runs and source reviews; recommendation is explicit, not guessed."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics


def summarize(root):
    result=json.loads((root/'results.json').read_text())
    manifest=json.loads((root/'snapshot.json').read_text()) if (root/'snapshot.json').exists() else {}
    categories={x['id']:x['category'] for x in manifest.get('files',[])}
    row={k:result.get(k) for k in ('engineVersion','project','snapshot','startedAt','completedAt','changedInputs','validForCurrentProject','toolInstalledBytes','javaInstalledBytes','status')}
    row['evidence']=str(root.resolve())
    row['languages']={}
    for language,value in result.get('languages',{}).items():
        data={k:value.get(k) for k in ('status','indexing','query','export','modelBytes','exportBytes','fixture','diagnostics')}
        folder=root/language
        model_path=folder/'analysis/model.json' if (folder/'analysis/model.json').exists() else folder/'model.json'
        if model_path.exists():
            model=json.loads(model_path.read_text())
            coverage=model['coverage']
            data['coverage']={k:v for k,v in coverage.items() if k!='missingFiles'}
            data['coverage']['missingByCategory']=dict(Counter(categories.get(p,'unknown') for p in coverage['missingFiles']))
            data['exportScope']={k:v for k,v in model.get('exportScope',{}).items() if k!='detailRoots'}
            data['model']=str(model_path.resolve())
        samples=value.get('joernQueries',{}).get('samples',[])
        if samples:
            values=sorted(x['milliseconds'] for x in samples)
            data['joernQueries']=dict(samples=len(values),p50Ms=statistics.median(values),p95Ms=values[math.ceil(.95*len(values))-1],maxMs=max(values),scope='same-session CPG query; excludes process/index/transport/layout/render time')
        review=folder/'analysis/source-review.json' if (folder/'analysis/source-review.json').exists() else folder/'source-review.json'
        if review.exists():
            source_review=json.loads(review.read_text())
            data['sourceReview']=dict(evidence=str(review.resolve()),calls=dict(Counter(x['verdict'] for x in source_review['calls'])),bindings=dict(Counter(x['verdict'] for x in source_review['variables'])),reviewedBy=source_review.get('reviewedBy'))
        semantics=folder/'semantic-checks.json'
        if semantics.exists():data['semanticChecks']=json.loads(semantics.read_text())
        row['languages'][language]=data
    return row


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--run',action='append',required=True,type=Path)
    cli.add_argument('--output',required=True,type=Path)
    cli.add_argument('--recommendation',required=True,choices=['core-engine','optional-enhancement','do-not-integrate'])
    args=cli.parse_args()
    data=dict(version=1,recommendation=args.recommendation,recommendationSource='Explicit source-grounded evaluation, not an automatic threshold',
              runs=[summarize(path) for path in args.run])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(data,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'summary':str(args.output.resolve()),'runs':len(data['runs']),'recommendation':args.recommendation}))


if __name__=='__main__':main()

import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require=createRequire(new URL('../package.json',import.meta.url));
const compiled=await build({entryPoints:[fileURLToPath(new URL('../src/UmlGraph.jsx',import.meta.url))],bundle:true,packages:'external',platform:'node',format:'cjs',write:false});
const module={exports:{}};
new Function('require','module','exports',compiled.outputFiles[0].text)(require,module,module.exports);
const {UmlNode}=module.exports;
const node={id:'save',label:'保存配置',role:'component',members:['validate()'],evidence:Array.from({length:3},(_,i)=>({id:'e'+i,path:'folder'+i+'/migration.py',startLine:31,endLine:46,symbol:{id:'fn'+i,name:'publish',kind:'function'}}))};
const render=(tagMode,role='component')=>renderToStaticMarkup(React.createElement(UmlNode,{measuring:true,data:{node:{...node,role},tagMode,choose:()=>{}}}));
test('simple nodes omit source DOM and source-only shape classes while retaining business meaning',()=>{
  const html=render('simple');assert.match(html,/保存配置/);assert.match(html,/validate\(\)/);
  assert.doesNotMatch(html,/source-tags|source-file-tag|source-function-tag|source-more|has-source|migration\.py|publish/);
  assert.doesNotMatch(render('simple','choice'),/has-source|source-tags/);
});
test('full nodes render complete nested file and function labels and the extra-evidence entry',()=>{
  const html=render('full');assert.match(html,/source-file-tag/);assert.match(html,/source-function-tag/);
  assert.match(html,/migration\.py/);assert.match(html,/publish\(\)/);assert.match(html,/查看全部 3 个文件依据/);
  assert.ok(html.indexOf('source-file-tag')<html.indexOf('source-function-tag'));
});

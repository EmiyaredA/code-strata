import test from 'node:test';
import assert from 'node:assert/strict';
import {reconcileDiagramTabs,managementRequest,diagramCheckLabel} from '../src/diagram-management.js';
import {restoreTabs,freshnessText} from '../src/uml-model.js';

test('trash closes only removed tabs and chooses their nearest surviving neighbor',()=>{
  const state={tabs:['a','b','c'],active:'b'};
  const next=reconcileDiagramTabs(state,[{id:'a'},{id:'c'}]);
  assert.deepEqual(next,{tabs:['a','c'],active:'c'});
  assert.deepEqual(reconcileDiagramTabs(next,[{id:'a'},{id:'b'},{id:'c'}]),next,'restore does not open a tab');
  assert.deepEqual(restoreTabs(state,[{id:'c'}]),{tabs:['c'],active:'c'});
  assert.deepEqual(reconcileDiagramTabs(state,[]),{tabs:[],active:null});
});
test('creation cannot accidentally inherit the active target; update pins identity and revision',()=>{
  const target={id:'a',revision:3,type:'class',title:'模型关系',purpose:'理解模型',lifecycleVersion:2};
  const created=managementRequest('create','配置迁移','activity',target);
  assert.equal(created.target,undefined);assert.equal(created.diagramType,'activity');
  const request=managementRequest('update','补充新增依赖','auto',target);
  target.revision=4;target.id='b';
  assert.deepEqual(request.target,{id:'a',revision:3,lifecycleVersion:2});assert.equal(request.diagramType,'class');
  assert.match(request.question,/补充新增依赖/);
  assert.throws(()=>managementRequest('create','  ','auto'));
});
test('legacy updates request UML conversion and preserve purpose; failed freshness is never called current',()=>{
  const request=managementRequest('update','','auto',{id:'old',revision:1,type:'legacy',title:'迁移',purpose:'先备份再发布'});
  assert.match(request.question,/旧版阅读图转换/);assert.match(request.question,/先备份再发布/);
  assert.equal(diagramCheckLabel({status:'error'}),'检查失败');
  assert.equal(diagramCheckLabel({status:'checking'}),'检查中');
  assert.equal(diagramCheckLabel({status:'current',analyzerChanged:true}),'分析器已变化');
  assert.equal(freshnessText({status:'error',files:[],message:'权限不足'}),'权限不足');
});

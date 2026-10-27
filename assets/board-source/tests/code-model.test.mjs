import {test} from 'node:test';
import assert from 'node:assert/strict';
import {containsRange,innermost,frameKey} from '../src/code-model.js';
test('UTF16 end-exclusive ranges distinguish same-line and multiline nesting',()=>{
  const outer={start:[2,0],end:[4,8]},inner={start:[3,14],end:[3,17]};
  assert.ok(containsRange(outer,inner));assert.ok(!containsRange(inner,outer));
  const nodes=[{id:'outer',range:outer},{id:'inner',range:inner}];assert.equal(innermost(nodes,inner).id,'inner');
});
test('navigation keys distinguish levels, groups, and scope; zoom is not semantic navigation',()=>{
  assert.notEqual(frameKey({view:'functions',focusId:'f'}),frameKey({view:'logic',focusId:'f'}));
  assert.notEqual(frameKey({view:'files',groupId:'a'}),frameKey({view:'files',groupId:'b'}));
  assert.equal(frameKey({view:'logic',focusId:'f',viewport:{zoom:1}}),frameKey({view:'logic',focusId:'f',viewport:{zoom:.5}}));
});

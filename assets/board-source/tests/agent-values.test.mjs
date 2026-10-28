import test from 'node:test';
import assert from 'node:assert/strict';
import { resolvedModel, catalogModel, inheritedParameter, parameterLabel, parameterSelection } from '../src/agent-values.js';

test('unset model shows the actual native ID, never the first catalog item', () => {
  const catalog = { models: [{ id: 'first', label: 'First' }, { id: 'actual', label: 'Actual' }],
    defaults: { model: { value: 'actual', source: 'Native config' } } };
  assert.equal(resolvedModel(catalog, ''), 'actual');
  assert.equal(catalogModel(catalog, '').label, 'Actual');
  assert.equal(resolvedModel(catalog, 'custom'), 'custom');
  assert.equal(resolvedModel({ models: catalog.models }, ''), '');
});

test('native configuration overrides model defaults, missing settings stay unknown', () => {
  const catalog = { models: [{ id: 'a', defaults: { reasoningEffort: { value: 'low', source: 'Model' } } }],
    defaults: { reasoningEffort: { value: 'high', source: 'CLI config' } } };
  assert.equal(inheritedParameter(catalog, 'a', 'reasoningEffort').value, 'high');
  delete catalog.defaults.reasoningEffort;
  assert.equal(inheritedParameter(catalog, 'a', 'reasoningEffort'), null);
  catalog.inheritModelDefaults = ['reasoningEffort'];
  assert.equal(inheritedParameter(catalog, 'a', 'reasoningEffort').value, 'low');
  assert.equal(inheritedParameter(catalog, 'custom', 'reasoningEffort'), null);
});

test('off, standard and absent variant are concrete values, not generic placeholders', () => {
  assert.equal(parameterLabel({ options: [{ value: 'default', label: '标准' }] }, { value: 'default' }), '标准');
  assert.equal(parameterLabel({ options: [{ value: 'false', label: '关闭' }] }, { value: 'false' }), '关闭');
  assert.equal(parameterLabel({ options: [] }, { value: '', label: '未启用变体' }), '未启用变体');
  assert.equal(parameterLabel({ options: [{ value: 'low', label: 'low' }] }, null), '未能读取，请选择');
});

test('resolved model aliases keep the full actual ID without inventing a name', () => {
  const catalog = { models: [{ id: 'opus', resolvedId: 'claude-opus-actual', label: 'Opus' }],
    defaults: { model: { value: 'claude-opus-actual' } } };
  assert.equal(catalogModel(catalog, '').label, 'Opus');
  assert.equal(resolvedModel(catalog, ''), 'claude-opus-actual');
});

test('read and saved values share one option and switching back stays explicit', () => {
  const field = { options: [{ value: 'default', label: '标准' }, { value: 'priority', label: 'Fast' }] };
  const native = { value: 'default', label: '标准', source: 'Codex 配置' };
  assert.deepEqual(parameterSelection(field, '', native), { value: 'default', options: field.options });
  assert.deepEqual(parameterSelection(field, 'default', native), { value: 'default', options: field.options });
  assert.deepEqual(parameterSelection(field, 'priority', native), { value: 'priority', options: field.options });
});

test('unknown or obsolete values remain visible without duplicating real options', () => {
  const field = { options: [{ value: 'high', label: 'high' }] };
  assert.deepEqual(parameterSelection(field, '', null).options[0], { value: '', label: '未能读取，请选择' });
  assert.deepEqual(parameterSelection(field, 'retired', null).options[0], { value: 'retired', label: 'retired（待确认）' });
  assert.deepEqual(parameterSelection(field, '', { value: '', label: '未启用变体' }).options[0], { value: '', label: '未启用变体' });
});

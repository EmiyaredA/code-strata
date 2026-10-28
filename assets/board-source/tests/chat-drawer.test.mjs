import test from 'node:test';
import assert from 'node:assert/strict';
import { chatDrawerLayout } from '../src/chat-drawer-model.js';

test('drawer uses one third of a desktop viewport and keeps at least 640px for code', () => {
  assert.equal(chatDrawerLayout(1920).width, 640);
  assert.equal(chatDrawerLayout(1440).width, 480);
  assert.equal(chatDrawerLayout(1280, 700).width, 640);
  const boundary = chatDrawerLayout(1040, 9999);
  assert.equal(boundary.width, 400);
  assert.equal(boundary.overlay, false);
  assert.equal(chatDrawerLayout(1920, 9999).width, 720);
});

test('narrow screens overlay the graph and phones use the full viewport without losing the saved desktop width', () => {
  assert.equal(chatDrawerLayout(1000, 520).overlay, true);
  assert.equal(chatDrawerLayout(502, 520).width, 502);
  assert.equal(chatDrawerLayout(502, 520).fullScreen, true);
  assert.equal(chatDrawerLayout(390, 520).width, 390);
  assert.equal(chatDrawerLayout(1920, 520).width, 520);
  assert.equal(chatDrawerLayout(1440, -12).width, 480);
  assert.equal(chatDrawerLayout(1440, 'invalid').width, 480);
});

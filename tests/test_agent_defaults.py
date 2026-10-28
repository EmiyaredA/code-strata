"""Effective settings must be native values, not guesses or leaked config."""
import json
import os
from unittest.mock import patch
from test_agents import AgentFixture
from agents.parameters import available_parameters
from agents.runtime import Process


class DefaultsTests(AgentFixture):
    def catalog(self, agent='codex', model='', force=False):
        return self.service.model_catalog.get({'agentId': agent, 'config': {**self.config, 'model': model}, 'force': force})

    def test_five_readers_return_only_concrete_whitelisted_values_without_prompts(self):
        trace = self.root / 'defaults-trace.jsonl'
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace)}):
            results = {agent: self.catalog(agent) for agent in ['codex', 'claude', 'pi', 'dsh', 'opencode']}
        self.assertEqual(results['codex']['defaults']['reasoningEffort']['value'], 'high')
        self.assertEqual(results['codex']['defaults']['serviceTier']['value'], 'default')
        self.assertEqual(results['codex']['defaults']['model']['value'], 'provider/model')
        self.assertEqual(results['claude']['defaults']['reasoningEffort']['value'], 'low')
        self.assertEqual(results['claude']['defaults']['fastMode']['value'], 'false')
        self.assertEqual(results['pi']['defaults']['thinking']['value'], 'medium')
        self.assertEqual(results['dsh']['defaults']['reasoningEffort']['value'], 'off')
        self.assertEqual(results['opencode']['defaults']['variant']['label'], '未启用变体')
        self.assertEqual(results['opencode']['defaults']['variant']['value'], '')
        self.assertNotIn('never-return-config-secret', json.dumps(results))
        self.assertNotIn('effective', json.dumps(results))
        params = available_parameters(results['codex'], '')
        speed = next(field for field in params if field['key'] == 'serviceTier')
        self.assertIn({'value': 'default', 'label': '标准'}, speed['options'])
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertFalse(any('prompt' in row or row.get('type') == 'user' for row in rows))
        self.assertNotIn('session/prompt', [row.get('method') for row in rows])
        self.assertNotIn('turn/start', [row.get('method') for row in rows])
        self.assertNotIn('apply_flag_settings', [row.get('request', {}).get('subtype') for row in rows])

    def test_unavailable_defaults_do_not_claim_a_value_or_destroy_catalog(self):
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_MODE': 'defaults_unsupported'}):
            codex = self.catalog()
            claude = self.catalog('claude')
        self.assertEqual(codex['status'], 'ready', codex)
        self.assertEqual(codex['defaults'], {})
        self.assertTrue(codex['models'])
        self.assertTrue(codex['defaultsMessage'])
        self.assertNotIn('reasoningEffort', claude['defaults'])
        self.assertEqual(claude['defaults']['fastMode']['value'], 'false')

    def test_explicit_no_tier_and_model_defaults_are_distinct(self):
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_MODE': 'defaults_model'}):
            result = self.catalog()
        self.assertNotIn('reasoningEffort', result['defaults'])
        self.assertNotIn('serviceTier', result['defaults'])
        self.assertEqual(result['inheritModelDefaults'], ['reasoningEffort', 'serviceTier'])
        model = result['models'][0]
        self.assertEqual(model['defaults']['reasoningEffort']['value'], 'low')
        self.assertEqual(model['defaults']['serviceTier']['value'], 'default')

    def test_cli_user_config_changes_invalidate_cached_values(self):
        home = self.root / 'codex-home'
        home.mkdir()
        config = home / 'config.toml'
        config.write_text('model_reasoning_effort="low"')
        with patch.dict(os.environ, {'CODEX_HOME': str(home)}):
            self.assertFalse(self.catalog()['cached'])
            self.assertTrue(self.catalog()['cached'])
            config.write_text('model_reasoning_effort="high"\n')
            self.assertFalse(self.catalog()['cached'])

    def test_claude_and_pi_queries_use_the_unsaved_model_and_model_scoped_cache(self):
        trace = self.root / 'selected-model.jsonl'
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace)}):
            for agent in ['claude', 'pi']:
                self.assertFalse(self.catalog(agent, 'provider/model')['cached'])
                self.assertTrue(self.catalog(agent, 'provider/model')['cached'])
                self.assertFalse(self.catalog(agent, 'other')['cached'])
        args = [row['args'] for row in map(json.loads, trace.read_text().splitlines()) if 'args' in row]
        for first in ['-p', '--mode']:
            selected = [item for item in args if item[0] == first]
            self.assertEqual([item[item.index('--model') + 1] for item in selected], ['provider/model', 'other'])

    def test_slow_optional_defaults_keep_catalog_and_cleanup_process(self):
        # Limit only the optional config reader, so cold process startup for
        # the model directory cannot turn this into an unrelated timeout.
        def start(launch, args, cwd, cancel, timeout, **kwargs):
            return Process(launch, args, cwd, cancel, .15 if args == ['app-server'] else timeout, **kwargs)
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_MODE': 'defaults_hang'}), \
                patch('agents.model_catalog.Process', side_effect=start):
            result = self.catalog()
        self.assertEqual(result['status'], 'ready', result)
        self.assertEqual(result['defaults'], {})
        self.assertTrue(result['models'])

    def test_explicit_standard_tier_is_sent_as_a_real_override(self):
        trace = self.root / 'standard-trace.jsonl'
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace)}):
            job = self.service.start_test({'agentId': 'codex', 'config': {
                **self.config, 'model': 'provider/model', 'parameters': {'serviceTier': 'default'}}})
            self.assertEqual(self.wait(job)['status'], 'success')
        args = next(row['args'] for row in map(json.loads, trace.read_text().splitlines())
                    if row.get('args', [None])[0] == 'exec')
        self.assertIn('service_tier="default"', args)

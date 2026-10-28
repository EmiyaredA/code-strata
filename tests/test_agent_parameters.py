"""Capability metadata, persistence, and actual argv/ACP propagation; no real models."""
import copy
import json
import os
import threading
import time
from unittest.mock import patch

from test_agents import AgentFixture
from agents.adapters import BY_ID
from agents.config import defaults, validate_settings
from agents.models import codex_models, opencode_models
from agents.parameters import available_parameters, check_parameters, claude_parameters
from agents.runtime import AgentError


class ParameterTests(AgentFixture):
    def test_old_settings_and_optional_parameters_roundtrip(self):
        old = defaults()
        self.assertEqual(validate_settings(old), old)
        changed = copy.deepcopy(old)
        changed['agents']['codex']['parameters'] = {'reasoningEffort': 'high', 'serviceTier': 'priority'}
        changed['agents']['claude']['parameters'] = {'fastMode': 'false'}
        self.service.store.save(changed)
        self.assertEqual(self.service.store.read()['settings'], changed)
        for agent, params in [('pi', {'serviceTier': 'priority'}), ('codex', {'args': '--evil'}),
                              ('claude', {'fastMode': True}), ('codex', {'reasoningEffort': 'a\nb'})]:
            invalid = copy.deepcopy(old)
            invalid['agents'][agent]['parameters'] = params
            with self.assertRaises(ValueError):
                validate_settings(invalid)
        changed['agents']['codex']['parameters'] = {'reasoningEffort': ''}
        self.assertNotIn('parameters', validate_settings(changed)['agents']['codex'])

    def test_model_capabilities_are_exact_not_guessed(self):
        rows = codex_models(json.dumps({'models': [
            {'slug': 'a', 'supported_reasoning_levels': [{'effort': 'low'}, {'effort': 'max'}, {'effort': 'low'}],
             'additional_speed_tiers': ['fast'], 'base_instructions': 'private'}, {'slug': 'b'}]}))
        self.assertEqual([item['value'] for item in rows[0]['parameters'][0]['options']], ['low', 'max'])
        self.assertEqual(rows[0]['parameters'][1]['options'], [{'value': 'priority', 'label': 'Fast'}])
        self.assertNotIn('parameters', rows[1])
        self.assertNotIn('private', json.dumps(rows))
        oc = opencode_models('p/m\n{"variants":{"custom-high":{},"turbo":{}}}')
        self.assertEqual([item['value'] for item in oc[0]['parameters'][0]['options']], ['custom-high', 'turbo'])
        self.assertEqual(claude_parameters({'supportsEffort': False, 'supportsFastMode': False}), [])
        catalog = {'agentId': 'codex', 'status': 'ready', 'models': rows}
        with self.assertRaises(AgentError):
            check_parameters(catalog, {'model': 'b', 'parameters': {'reasoningEffort': 'max'}})
        with self.assertRaises(AgentError):
            check_parameters(catalog, {'model': '', 'parameters': {'reasoningEffort': 'max'}})

    def test_all_native_parameters_reach_invocations(self):
        trace = self.root / 'parameters.jsonl'
        configs = {'codex': {'reasoningEffort': 'high', 'serviceTier': 'priority'},
                   'opencode': {'variant': 'high'}, 'claude': {'reasoningEffort': 'low', 'fastMode': 'true'},
                   'pi': {'thinking': 'max'}, 'dsh': {'reasoningEffort': 'high'}}
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace)}):
            for agent, params in configs.items():
                config = {**self.config, 'model': 'provider/model', 'parameters': params}
                result = self.wait(self.service.start_test({'agentId': agent, 'config': config}))
                self.assertEqual(result['status'], 'success', result)
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        commands = [row['args'] for row in records if 'args' in row]
        codex = next(args for args in commands if args[0] == 'exec')
        self.assertIn('model_reasoning_effort="high"', codex)
        self.assertIn('service_tier="priority"', codex)
        self.assertEqual(codex[-1], '-')
        oc = next(args for args in commands if args[0] == 'run')
        self.assertEqual(oc[oc.index('--variant') + 1], 'high')
        claude = next(args for args in commands if args[0] == '-p' and '--input-format' not in args)
        self.assertEqual(claude[claude.index('--effort') + 1], 'low')
        self.assertEqual(json.loads(claude[claude.index('--settings') + 1]), {'fastMode': True})
        pi = next(args for args in commands if args[0] == '--print')
        self.assertEqual(pi[pi.index('--thinking') + 1], 'max')
        config_calls = [row['params'] for row in records if row.get('method') == 'session/set_config_option']
        self.assertEqual([(item['configId'], item['value']) for item in config_calls],
                         [('model', 'provider/model'), ('reasoning_effort', 'high')])
        false_args = BY_ID['claude'].test_args('', {'fastMode': 'false'})
        self.assertEqual(json.loads(false_args[false_args.index('--settings') + 1]), {'fastMode': False})
        for agent in BY_ID.values():
            args = agent.test_args('')
            self.assertFalse(set(args) & {'--effort', '--thinking', '--variant', '--settings', '-c'})

    def test_unsupported_pair_fails_before_generation(self):
        trace = self.root / 'invalid.jsonl'
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace)}):
            for agent, params in [('codex', {'reasoningEffort': 'ultra'}), ('opencode', {'variant': 'invented'}),
                                  ('claude', {'fastMode': 'true'}), ('dsh', {'reasoningEffort': 'max'})]:
                result = self.wait(self.service.start_test({'agentId': agent,
                    'config': {**self.config, 'model': 'no-name' if agent == 'claude' else 'provider/model', 'parameters': params}}))
                self.assertEqual(result['kind'], 'parameters', result)
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertFalse(any('prompt' in row or row.get('method') == 'session/prompt' for row in records))
        self.assertTrue(any(row.get('method') == 'session/close' for row in records))

    def test_dsh_capabilities_are_model_scoped_and_queries_never_prompt(self):
        trace = self.root / 'acp-query.jsonl'
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace)}):
            default = self.service.model_catalog.get({'agentId': 'dsh', 'config': self.config})
            selected = self.service.model_catalog.get({'agentId': 'dsh', 'config': {**self.config, 'model': 'provider/model'}})
        self.assertEqual(default['parameters'][0]['options'][0]['value'], 'off')
        self.assertEqual(selected['parameters'][0]['options'][0]['value'], 'low')
        self.assertFalse(selected['cached'])
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertNotIn('session/prompt', [row.get('method') for row in rows])
        self.assertEqual(sum(row.get('method') == 'session/close' for row in rows), 2)
        unknown = self.service.model_catalog.get({'agentId': 'dsh', 'config': {**self.config, 'model': 'retired-model'}})
        self.assertEqual(unknown['status'], 'ready')
        self.assertTrue(unknown['models'])
        self.assertEqual(unknown['parameters'], [])
        self.assertTrue(unknown['parameterMessage'])

    def test_parameter_validation_query_can_cancel_and_timeout(self):
        trace = self.root / 'cancel-query.jsonl'
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_TRACE': str(trace), 'CODE_STRATA_FAKE_MODE': 'models_hang'}):
            config = {**self.config, 'model': 'provider/model', 'parameters': {'reasoningEffort': 'high'}}
            job = self.service.start_test({'agentId': 'codex', 'config': config})
            time.sleep(.08)
            self.service.cancel(job['id'])
            self.assertEqual(self.wait(job)['status'], 'cancelled')
            self.service.test_timeout = .15
            job = self.service.start_test({'agentId': 'codex', 'config': config})
            self.assertEqual(self.wait(job)['kind'], 'timeout')
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertFalse(any('prompt' in row for row in rows))

    def test_optional_help_failure_preserves_pi_model_catalog(self):
        self.service.model_catalog.timeout = .2
        with patch.dict(os.environ, {'CODE_STRATA_FAKE_MODE': 'help_hang'}):
            result = self.service.model_catalog.get({'agentId': 'pi', 'config': self.config})
        self.assertEqual(result['status'], 'ready', result)
        self.assertTrue(result['models'])
        self.assertEqual(result['parameters'], [])
        self.assertTrue(result['parameterMessage'])

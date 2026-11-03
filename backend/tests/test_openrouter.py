import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('openrouter', Path(__file__).parents[2] / 'runner/openrouter.py')
openrouter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(openrouter)


def model(name='org/model:free', price='0', parameters=None):
    return {'id': name, 'pricing': {'prompt': price, 'completion': '0', 'request': '0'},
            'architecture': {'input_modalities': ['text']},
            'supported_parameters': parameters if parameters is not None else ['structured_outputs']}


def test_discovery_excludes_paid_and_unsupported():
    entries = [model(), model('org/paid:free', '0.1'), model('org/paid'), model('org/no-schema:free', parameters=[])]
    assert openrouter.free_models({'data': entries}) == ['org/model:free']
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.free_models({'data': None})


def test_missing_key_never_sends_request(monkeypatch):
    monkeypatch.delenv('GA_OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr(openrouter, '_request', lambda *a: pytest.fail('unexpected request'))
    with pytest.raises(openrouter.OpenRouterError, match='not configured'):
        openrouter.run('prompt', {})


def test_free_selection_zero_ceiling_and_model_record(monkeypatch):
    monkeypatch.setenv('GA_OPENROUTER_API_KEY', 'test-secret')
    calls = []
    def request(path, key, payload=None):
        calls.append((path, payload))
        if path == '/models':
            return {'data': [model()]}
        return {'model': 'org/model:free', 'choices': [{'message': {'content': '{"ok":true}'}}]}
    monkeypatch.setattr(openrouter, '_request', request)
    result = openrouter.run('prompt', {'type': 'object'})
    assert result['model'] == 'org/model:free'
    assert calls[1][1]['provider']['max_price'] == {'prompt': 0, 'completion': 0}
    assert calls[1][1]['model'].endswith(':free')


def test_rate_limited_models_never_fall_back_to_paid(monkeypatch):
    monkeypatch.setenv('GA_OPENROUTER_API_KEY', 'test-secret')
    calls = []
    def request(path, key, payload=None):
        calls.append(payload)
        if path == '/models':
            return {'data': [model(), model('org/paid')]}
        raise openrouter.OpenRouterError('rate limited')
    monkeypatch.setattr(openrouter, '_request', request)
    with pytest.raises(openrouter.OpenRouterError, match='rate limited'):
        openrouter.run('prompt', {})
    assert len(calls) == 2 and calls[-1]['model'] == 'org/model:free'


def test_runner_result_contract_accepts_discovered_id_and_rejects_paid():
    from pydantic import ValidationError
    from gold_advisor.api import RunnerResultIn
    assert RunnerResultIn(model='org/model:free').model == 'org/model:free'
    with pytest.raises(ValidationError):
        RunnerResultIn(model='org/paid')


def test_unexpected_provider_model_is_rejected(monkeypatch):
    monkeypatch.setenv('GA_OPENROUTER_API_KEY', 'test-secret')
    def request(path, key, payload=None):
        if path == '/models':
            return {'data': [model()]}
        return {'model': 'org/paid', 'choices': [{'message': {'content': '{}'}}]}
    monkeypatch.setattr(openrouter, '_request', request)
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.run('prompt', {})


def test_runner_selects_openrouter_without_exposing_key(monkeypatch):
    import importlib.util
    import sys

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / 'runner'))
    runner_spec = importlib.util.spec_from_file_location('gold_ai_runner_test', Path(__file__).parents[2] / 'runner/gold_ai_runner.py')
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    monkeypatch.setenv('GA_OPENROUTER_API_KEY', 'test-secret')
    monkeypatch.setattr(runner.openrouter, 'run', lambda prompt, schema: {'raw_output': '{}', 'model': 'org/model:free'})
    result = runner.run_job({'provider': 'openrouter', 'prompt': 'facts', 'schema': {}})
    assert result == {'raw_output': '{}', 'model': 'org/model:free', 'cli_version': 'OpenRouter API'}
    assert 'test-secret' not in str(result)

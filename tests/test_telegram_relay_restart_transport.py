import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('relay', Path(__file__).resolve().parents[1] / 'local_agent/telegram_relay_server.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)

@pytest.mark.parametrize('params', [
    {'limit': 100, 'timeout': 0},
    {'offset': 25, 'limit': 20, 'timeout': 0, 'allowed_updates': ['message']},
    {'offset': 0, 'limit': 20, 'timeout': 0},
])
def test_valid_polling_is_forwarded(monkeypatch, params):
    calls = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n): return b'{"ok":true,"result":[]}'
    class Opener:
        def open(self, request, timeout):
            calls.append(json.loads(request.data))
            return Response()
    monkeypatch.setattr(relay, 'build_opener', lambda *args: Opener())
    monkeypatch.setattr(relay, '_limit', lambda: True)
    result = relay.forward({'token': '123456:' + 'x' * 30, 'method': 'getUpdates', 'params': params})
    assert result[0] == 200
    assert calls == [params]

@pytest.mark.parametrize('extra', [
    {'offset': -1}, {'offset': True}, {'offset': 2**63},
    {'allowed_updates': ['callback_query']}, {'url': 'https://example.com'},
    {'timeout': 1}, {'limit': False},
])
def test_invalid_polling_does_not_reach_network(monkeypatch, extra):
    def unexpected(*args): raise AssertionError('network should not be called')
    monkeypatch.setattr(relay, 'build_opener', unexpected)
    params = {'limit': 20, 'timeout': 0, **extra}
    assert relay.forward({'token': '123456:' + 'x' * 30, 'method': 'getUpdates', 'params': params})[0] == 400

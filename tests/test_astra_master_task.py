from __future__ import annotations
import base64
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from local_agent import poller
from local_agent.control_protocol import ProtocolError


def envelope(operation="astra_season_response", arguments=None, approval=True):
    now=datetime.now(timezone.utc)
    return json.dumps({"protocol_version":1,"task_id":"astra-response-test",
        "operation":operation,"created_at":now.isoformat(),
        "expires_at":(now+timedelta(hours=1)).isoformat(),
        "requires_local_approval":approval,"arguments":arguments or {}})


def test_astra_operation_uses_strict_envelope_and_no_arguments():
    task=poller._parse_task_with_restart(envelope())
    assert task.operation=="astra_season_response"
    with pytest.raises(ProtocolError):
        poller._parse_task_with_restart(envelope(arguments={"prompt":"arbitrary"}))
    with pytest.raises(ProtocolError):
        poller._parse_task_with_restart(envelope(approval=False))


def test_astra_response_reads_private_brief_uses_astra_and_checkpoints(tmp_path, monkeypatch):
    import local_agent.octava_credentials as credentials
    master="# MASTER WORK TASK\nFIRST MANDATORY END-TO-END TEST\n"+("details "*300)
    encoded=base64.b64encode(master.encode()).decode()
    class GithubResponse:
        def json(self):
            return {"type":"file","encoding":"base64","content":encoded}
    class Client:
        def _request(self, method, path, **kwargs):
            assert method=="GET"
            assert path=="contents/private_tasks/octava_season30_master_20261013.txt"
            assert kwargs["params"]=={"ref":"main"}
            return GithubResponse()
    class ProviderResponse:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self,limit):
            assert limit==180001
            return json.dumps({"choices":[{"message":{"content":"Ответ Астры"}}]}).encode()
    captured={}
    def fake_urlopen(request, timeout):
        captured["request"]=request
        captured["timeout"]=timeout
        return ProviderResponse()
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":True})
    monkeypatch.setattr(credentials,"read_key",lambda:("local-test-key","windows_vault"))
    monkeypatch.setattr(poller,"urlopen",fake_urlopen,raising=False)
    monkeypatch.setattr(poller,"_ensure_agent_dir",lambda:tmp_path)
    result=poller._run_astra_season_response(Client(),"astra-response-test")
    body=json.loads(captured["request"].data)
    assert body["model"]=="gpt-6-astra"
    assert "MASTER WORK TASK" in body["messages"][1]["content"]
    assert captured["timeout"]==180
    assert result["status"]=="completed"
    assert result["answer"]=="Ответ Астры"
    assert (tmp_path/"reports/astra-response-test_astra_response.txt").read_text()=="Ответ Астры"
    assert result["executed_commands"] is False


def test_astra_operation_stops_when_local_provider_consent_is_off(monkeypatch):
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":False})
    class NoNetwork:
        def _request(self,*args,**kwargs):
            raise AssertionError("must stop before network")
    result=poller._run_astra_season_response(NoNetwork(),"astra-response-test")
    assert result=={"status":"blocked","reason":"local_octava_permission_disabled"}

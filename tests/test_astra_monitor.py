import json
from local_agent.studio_server import astra_monitor_snapshot

def test_empty_reports_are_not_claimed_running(tmp_path):
    result=astra_monitor_snapshot(tmp_path)
    assert result['tasks']==[]
    assert 'running' not in result

def test_transcript_is_bounded_and_secrets_redacted(tmp_path):
    folder=tmp_path/'astra-audit-1';folder.mkdir()
    (folder/'progress.json').write_text(json.dumps({'chunks_sent':3,'source_chunks':6,'api_key':'secret'}))
    (folder/'request_part_1.txt').write_text('api_key="abcdefghijklmno"\n'+'x'*11000)
    (folder/'part_1.txt').write_text('Observed source defect')
    result=astra_monitor_snapshot(tmp_path);task=result['tasks'][0]
    assert task['progress']=={'source_chunks':6,'chunks_sent':3}
    assert len(task['events'])==2
    request=next(e for e in task['events'] if e['kind']=='request')
    assert request['truncated']
    assert 'abcdefghijklmno' not in request['text']
    assert not task['final_report_saved']

def test_unrelated_files_and_symlinks_never_exposed(tmp_path):
    folder=tmp_path/'astra-audit-1';folder.mkdir()
    private=tmp_path/'passwords.txt';private.write_text('private')
    (folder/'part_1.txt').symlink_to(private)
    (folder/'arbitrary.txt').write_text('private')
    result=astra_monitor_snapshot(tmp_path)
    assert result['tasks'][0]['events']==[]

def test_saved_final_report_is_factually_distinguished(tmp_path):
    folder=tmp_path/'astra-audit-1';folder.mkdir();(folder/'AUDIT_REPORT.md').write_text('partial audit')
    assert astra_monitor_snapshot(tmp_path)['tasks'][0]['final_report_saved']

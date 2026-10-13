from local_agent.studio_jobs import SeasonFeedbackCoordinator,StudioJobError,verify_episode_artifact
import pytest,json,subprocess
from types import SimpleNamespace

def test_executes_and_returns_actual_feedback_to_next_astra_call(tmp_path):
    c=SeasonFeedbackCoordinator(tmp_path);requests=[];executions=[]
    def ask(question):
        requests.append(question);return {'action_id':'a'+str(len(requests)),'operation':'inspect','arguments':{}}
    def execute(args):executions.append(args);return {'status':'completed','observed_files':3}
    c.cycle_once(ask,{'inspect':execute},lambda *_:False)
    c.cycle_once(ask,{'inspect':execute},lambda *_:False)
    assert len(executions)==2
    assert requests[1]['feedback']['result']['observed_files']==3
    assert c.snapshot()['status']!='completed'
    assert len((tmp_path/'season_control/history.jsonl').read_text().splitlines())>=6

def test_identical_action_is_not_executed_twice_after_restart(tmp_path):
    action={'action_id':'same','operation':'inspect','arguments':{}};executions=[]
    c=SeasonFeedbackCoordinator(tmp_path)
    c.cycle_once(lambda _:action,{'inspect':lambda _:executions.append(1) or {'status':'completed'}},lambda *_:False)
    c=SeasonFeedbackCoordinator(tmp_path)
    state=c.cycle_once(lambda _:action,{'inspect':lambda _:executions.append(1)},lambda *_:False)
    assert executions==[1] and state['last_feedback']['status']=='already_executed_no_replay'

def test_textual_episode_completion_claim_never_counts(tmp_path):
    c=SeasonFeedbackCoordinator(tmp_path)
    state=c.cycle_once(lambda _:{'action_id':'a','operation':'render','arguments':{'episode_id':'S01E01'}},
        {'render':lambda _:{'status':'completed','all_episodes_done':True}},lambda *_:False)
    assert state['episodes']['S01E01']=='pending' and state['status']!='completed'

def test_unsupported_command_is_factual_blocker(tmp_path):
    state=SeasonFeedbackCoordinator(tmp_path).cycle_once(lambda _:{'action_id':'a','operation':'unavailable','arguments':{}},{},lambda *_:False)
    assert state['last_feedback']['executed'] is False
    assert state['last_feedback']['result']['status']=='blocked'

def test_mismatched_action_id_is_rejected(tmp_path):
    c=SeasonFeedbackCoordinator(tmp_path)
    c.cycle_once(lambda _:{'action_id':'a','operation':'inspect','arguments':{}},{},lambda *_:False)
    with pytest.raises(StudioJobError):c.cycle_once(lambda _:{'action_id':'a','operation':'changed','arguments':{}},{},lambda *_:False)

def test_interrupted_action_requires_reconciliation_without_blind_replay(tmp_path):
    c=SeasonFeedbackCoordinator(tmp_path);state=c.start();state['pending_action']={'action_id':'uncertain'}
    c._persist(state,{'event':'crash_test'})
    restored=SeasonFeedbackCoordinator(tmp_path).cycle_once(lambda _:pytest.fail('must not call model'),{},lambda *_:False)
    assert restored['status']=='needs_reconciliation'

def test_all_thirty_need_independent_verification_and_revalidation(tmp_path):
    c=SeasonFeedbackCoordinator(tmp_path)
    for i in range(1,31):
        state=c.cycle_once(lambda _,i=i:{'action_id':'a'+str(i),'operation':'render','arguments':{'episode_id':f'S01E{i:02d}'}},
            {'render':lambda _:{'status':'completed'}},lambda *_:True)
        assert (state['status']=='completed')==(i==30)

def test_episode_media_gate_checks_exact_mp4_contract_without_claiming_visual_quality(tmp_path,monkeypatch):
    target=tmp_path/'episodes'/'S01E01'/'final.mp4';target.parent.mkdir(parents=True);target.write_bytes(b'x'*1_000_001)
    metadata={'format':{'format_name':'mov,mp4,m4a','duration':'300'},'streams':[{
        'codec_type':'video','codec_name':'h264','width':720,'height':1280,
        'pix_fmt':'yuv420p','avg_frame_rate':'24/1','nb_read_frames':'7200'}]}
    monkeypatch.setattr('shutil.which',lambda _: '/usr/bin/ffprobe')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps(metadata).encode()))
    result=verify_episode_artifact(tmp_path,'S01E01')
    assert result['status']=='technical_checks_passed'
    assert len(result['sha256'])==64 and result['visual_review_required'] is True
    assert result['season_completion_eligible'] is False

def test_episode_media_gate_rejects_audio_and_short_episode(tmp_path,monkeypatch):
    target=tmp_path/'episodes'/'S01E01'/'final.mp4';target.parent.mkdir(parents=True);target.write_bytes(b'x'*1_000_001)
    monkeypatch.setattr('shutil.which',lambda _: '/usr/bin/ffprobe')
    video={'codec_type':'video','codec_name':'h264','width':720,'height':1280,
        'pix_fmt':'yuv420p','avg_frame_rate':'24/1','nb_read_frames':'2880'}
    metadata={'format':{'format_name':'mp4','duration':'120'},'streams':[video, {'codec_type':'audio'}]}
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps(metadata).encode()))
    assert verify_episode_artifact(tmp_path,'S01E01')['reason']=='unexpected_media_streams'
    metadata['streams']=metadata['streams'][:1]
    assert verify_episode_artifact(tmp_path,'S01E01')['reason']=='episode_duration_out_of_range'

def test_episode_media_gate_rejects_wrong_id_and_linked_output(tmp_path):
    assert verify_episode_artifact(tmp_path,'../S01E01')['reason']=='invalid_episode_id'
    episodes=tmp_path/'episodes';episodes.mkdir();(episodes/'S01E01').symlink_to(tmp_path)
    assert verify_episode_artifact(tmp_path,'S01E01')['reason']=='episode_path_is_link'

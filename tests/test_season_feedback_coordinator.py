from local_agent.studio_jobs import SeasonFeedbackCoordinator,StudioJobError
import pytest,json

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

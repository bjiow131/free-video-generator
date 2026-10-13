from local_agent.studio_jobs import AssetQualityStore,StudioJobError
import pytest

def candidate(tmp_path,asset_id='prop.scooter'):
    for name in ('source.png','candidate.blend','front.png'):(tmp_path/name).write_bytes(name.encode())
    store=AssetQualityStore(tmp_path)
    state=store.register(asset_id,'source.png','candidate.blend',['front.png'])
    return store,state

def approve(store,state):
    return store.record_astra_review(state['asset_id'],source_sha256=state['source_sha256'],candidate_sha256=state['candidate_sha256'],view_hashes=state['views'],vision_confirmed=True,criteria={'identity':True,'shape':True},unresolved=[])

def test_non_mia_is_auto_approved_and_survives_restart(tmp_path):
    store,state=candidate(tmp_path);assert not store.ready('prop.scooter');approve(store,state)
    assert AssetQualityStore(tmp_path).ready('prop.scooter')

def test_any_edit_invalidates_previous_approval(tmp_path):
    store,state=candidate(tmp_path);approve(store,state);(tmp_path/'candidate.blend').write_bytes(b'new-version')
    assert not store.ready('prop.scooter')
    assert store.snapshot('prop.scooter')['status']=='version_changed_requires_review'

def test_unresolved_issue_or_missing_vision_blocks_release(tmp_path):
    store,state=candidate(tmp_path)
    result=store.record_astra_review('prop.scooter',source_sha256=state['source_sha256'],candidate_sha256=state['candidate_sha256'],view_hashes=state['views'],vision_confirmed=False,criteria={'identity':True},unresolved=[])
    assert result['status']=='needs_revision' and not store.ready('prop.scooter')

def test_review_for_other_candidate_rejected(tmp_path):
    store,state=candidate(tmp_path)
    with pytest.raises(StudioJobError):store.record_astra_review('prop.scooter',source_sha256=state['source_sha256'],candidate_sha256='0'*64,view_hashes=state['views'],vision_confirmed=True,criteria={'shape':True},unresolved=[])

def test_mia_always_requires_owner_after_astra_review(tmp_path,monkeypatch):
    store,state=candidate(tmp_path)
    monkeypatch.setattr(AssetQualityStore,'MIA_REFERENCE_SHA',state['source_sha256'])
    state=store.register('char.mia.master','source.png','candidate.blend',['front.png'])
    approve(store,state)
    assert not store.ready('char.mia.master')
    store.owner_approve_mia('char.mia.master',state['candidate_sha256'])
    assert store.ready('char.mia.master')

def test_asset_path_traversal_is_rejected(tmp_path):
    store=AssetQualityStore(tmp_path)
    with pytest.raises(StudioJobError):store.register('prop.x','../outside','candidate.blend',['view.png'])

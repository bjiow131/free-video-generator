"""Numeric fitting evidence independent of Blender/CUDA availability."""
import ast
from pathlib import Path
import pytest
np = pytest.importorskip("numpy")


@pytest.fixture(scope='module')
def fitting():
    workflow=ast.parse(Path('local_agent/blender_workflow.py').read_text())
    fn=next(n for n in workflow.body if isinstance(n,ast.FunctionDef) and n.name=='_mia_reference_model_script')
    script=ast.literal_eval(fn.body[1].value)
    tree=ast.parse(script)
    # Extract the exact shipped pure helpers, rather than a test-only copy.
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name.startswith('fit_') and n.name!='fit_model_to_reference']
    selected += [n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FIT_BOUNDS' for t in n.targets)]
    module=ast.Module(body=selected,type_ignores=[]);ns={}
    exec(compile(module,'shipped_fit_helpers','exec'),ns)
    return ns


def toy_mesh():
    z=np.linspace(.035,3.80,220);ang=np.linspace(0,2*np.pi,140)
    zz,aa=np.meshgrid(z,ang)
    width=.20+.25*np.exp(-((zz-3.2)/.45)**2)+.16*np.exp(-((zz-2.0)/.55)**2)
    depth=.18+.24*np.exp(-((zz-3.2)/.45)**2)
    return np.stack((width*np.cos(aa),depth*np.sin(aa),zz),axis=-1).reshape(-1,3)


def targets_for(ns,v):
    return {name:ns['fit_profile'](v[:,axis]*sign,v[:,2])
            for name,axis,sign in [('front',0,1),('side',1,-1),('back',0,-1)]}


def test_fit_recovers_known_deformation_and_all_views_improve(fitting):
    v=toy_mesh();target=fitting['fit_deform'](v,{'head_width':1.12,'head_depth':.88,'torso_width':.94})
    fitted,report=fitting['fit_optimize'](v,targets_for(fitting,target))
    assert report['status']=='improved'
    assert report['relative_error_reduction']>.50
    assert all(report['after_errors'][k]<report['before_errors'][k] for k in report['before_errors'])
    assert np.max(np.abs(v-fitted))>.01
    assert not report['identity_verified']


def test_already_matching_mesh_is_preserved(fitting):
    v=toy_mesh();result,report=fitting['fit_optimize'](v,targets_for(fitting,v))
    np.testing.assert_array_equal(v,result)
    assert not report['geometry_changed']


def test_deformation_bounded_finite_and_monotonic(fitting):
    v=toy_mesh()
    for parameters in ({'head_width':100},{'head_width':float('nan')},{'head_width':True},{'command':1}):
        with pytest.raises(ValueError):fitting['fit_deform'](v,parameters)
    z=np.linspace(0,4,1000);xyz=np.stack((z*0,z*0,z),axis=1)
    p={k:b[0] for k,b in fitting['FIT_BOUNDS'].items()}
    assert np.all(np.diff(fitting['fit_deform'](xyz,p)[:,2])>0)
    with pytest.raises(ValueError):fitting['fit_optimize'](v,targets_for(fitting,v),max_evaluations=10000)


def test_segmentation_excludes_letterbox_and_rejects_bad_reference(fitting):
    image=np.ones((1536,710,3))*.5;image[:530]=0;image[1005:]=0
    for start in (80,315,550):image[550:960,start:start+80]=[.12,.4,.55]
    profiles,masks,boxes=fitting['fit_reference_profiles'](image)
    assert set(profiles)=={'front','side','back'}
    assert all(box[1]==550 and box[3]==959 for box in boxes.values())
    for mask in masks.values():assert not mask[:530].any()
    with pytest.raises(ValueError):fitting['fit_reference_profiles'](np.zeros_like(image))


def test_shipped_reference_segments_consistent_views(fitting):
    from PIL import Image
    path=Path('/workspace/scratch/828cfefd34c1/reference.jpeg')
    if not path.exists():pytest.skip('Private reference remains local')
    rgb=np.asarray(Image.open(path).convert('RGB'),dtype=float)/255
    profiles,_,boxes=fitting['fit_reference_profiles'](rgb)
    assert all(np.isfinite(p).all() for p in profiles.values())
    assert len(boxes)==3
    assert all(380<=box[3]-box[1]<=430 for box in boxes.values())
    assert all(box[2]-box[0]<220 for box in boxes.values())


def test_reference_review_isolated_from_legacy_source_reset_guard():
    workflow = ast.parse(Path('local_agent/blender_workflow.py').read_text())
    fn = next(n for n in workflow.body if isinstance(n, ast.FunctionDef) and n.name == 'create_reference_mia_model')
    calls = [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert '_legacy_source_reset_guard' not in calls
    assert any(isinstance(n, ast.Constant) and isinstance(n.value, str) and 'MIA_REFERENCE_REVIEW' in n.value for n in ast.walk(fn))

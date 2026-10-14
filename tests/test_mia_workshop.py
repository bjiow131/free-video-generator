import json
import hashlib
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
m=types.ModuleType('embedded_workshop')
m.Any=object
source=Path('local_agent/blender_rigging.py').read_text()
source=source[source.index('"""Bounded visual corrections of a saved Mia mesh; provider output is data only."""'):]
exec(compile(source,'embedded_workshop','exec'),m.__dict__)

class WorkshopTests(unittest.TestCase):
    def exercise(self, reviews):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        ws=Path(tmp.name)
        source=ws/'SOURCE_ADAPTATIONS/input/mia_spring_source_adapted.blend';source.parent.mkdir(parents=True);source.write_bytes(b'original-source')
        ref=ws/'episode1/assets/references/mia_turnaround_approved_20261012.jpeg';ref.parent.mkdir(parents=True);ref.write_bytes(b'test-reference')
        locator=types.ModuleType('local_agent.blender_locator');locator.find_blender_executable=lambda:'blender'
        names=types.ModuleType('local_agent.path_names');names.path_identifier_pattern=lambda limit:__import__('re').compile(r'[a-z]+');names.is_link_or_junction=lambda p:False
        policy=types.ModuleType('local_agent.mailbox_policy');policy.load_policy=lambda:{'enabled':True,'allow_blender':True,'allow_octava':True}
        calls=[]
        def execute(command,**kw):
            cfg=json.loads(Path(command[-1]).read_text());folder=Path(cfg['out']);calls.append(cfg)
            (folder/'mia_spring_source_adapted.blend').write_bytes(b'candidate-'+folder.name.encode())
            for view in m.MIA_ADAPTIVE_VIEWS:(folder/(view+'.png')).write_bytes(folder.name.encode())
            (folder/'geometry_report.json').write_text(json.dumps({'inventory':[{'name':'Head'}],'changes':cfg['edits']}))
            return types.SimpleNamespace(returncode=0,stdout='actual fake runner')
        with patch.object(m,'MIA_ADAPTIVE_REFERENCE_SHA',hashlib.sha256(b'test-reference').hexdigest()),patch.dict(os.environ,{'LOCAL_AGENT_WORKSPACE':str(ws)}),patch.dict('sys.modules',{'local_agent.blender_locator':locator,'local_agent.path_names':names,'local_agent.mailbox_policy':policy}),patch.object(m,'workshop_study',return_value=[]),patch.object(m,'acquire_mia_study_sources',return_value=[]),patch.object(m,'inspect_study_sources',return_value=[]),patch.object(m,'mia_adaptive_ask',side_effect=reviews),patch.object(m,'mia_visual_change_gate',return_value={'passed':True}),patch('subprocess.run',side_effect=execute),patch('shutil.which',return_value=None):
            result=m.run_workshop('input','output')
        self.assertEqual(source.read_bytes(),b'original-source')
        self.assertFalse(result['identity_verified'])
        self.assertFalse(result['production_ready'])
        return result,calls
    def test_no_edits_is_executor_blocker_not_success(self):
        r,calls=self.exercise([{'verdict':'NEEDS_REVISION','edits':[],'differences':['Topology required'],'evaluation':'baseline','learning_notes':'Need topology executor'}])
        self.assertEqual(r['goal_status'],'executor_extension_required')
        self.assertEqual(len(calls),1)
        self.assertEqual(r['astra_reviews'],1)
    def test_regression_keeps_previous_checkpoint(self):
        edit={'object':'Head','kind':'translate','offset':[.001,0,0],'reason':'Observed landmark correction'}
        r,calls=self.exercise([{'verdict':'NEEDS_REVISION','edits':[edit],'differences':['Head'],'evaluation':'baseline','learning_notes':'Study'}, {'verdict':'NEEDS_REVISION','edits':[],'differences':['Worse'],'evaluation':'regressed','learning_notes':'Revert'}])
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1]['edits'],[edit])
        self.assertTrue(r['review_dir'].endswith('pass_0'))
        self.assertFalse(r['guide']['history'][1]['accepted'])

if __name__=='__main__':unittest.main()

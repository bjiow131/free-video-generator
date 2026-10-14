import copy
import math
import unittest
from local_agent import blender_rigging as rigging
from local_agent.blender_rigging import validate_mia_adaptive_plan as validate_plan, MIA_ADAPTIVE_BLENDER_SCRIPT as BLENDER_SCRIPT, mia_visual_change_gate as visual_change_gate
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class AdaptivePlanTests(unittest.TestCase):
    def setUp(self):
        self.inventory=[{'name':'MiaHead'}]
        self.plan={'verdict':'NEEDS_REVISION','differences':['Лицо отличается'], 'edits':[{'object':'MiaHead','kind':'brush','reason':'Уточнить подбородок','center':[.5,.2,.1],'radius':[.2,.2,.2],'offset':[0,-.002,0]}]}
    def test_bounded_brush_allowed(self):
        self.assertEqual(validate_plan(self.plan,self.inventory),self.plan)
    def test_external_code_rejected(self):
        self.plan['edits'][0]['code']='import os'
        with self.assertRaises(ValueError):validate_plan(self.plan,self.inventory)
    def test_unseen_object_rejected(self):
        self.plan['edits'][0]['object']='InventedEye'
        with self.assertRaises(ValueError):validate_plan(self.plan,self.inventory)
    def test_nonfinite_bool_and_large_values_rejected(self):
        for value in (math.nan,math.inf,True,.5):
            p=copy.deepcopy(self.plan);p['edits'][0]['offset'][0]=value
            with self.assertRaises(ValueError):validate_plan(p,self.inventory)
    def test_compounded_object_edits_rejected(self):
        self.plan['edits']*=2
        with self.assertRaises(ValueError):validate_plan(self.plan,self.inventory)
    def test_ready_cannot_apply_edits(self):
        self.plan['verdict']='READY_FOR_USER_REVIEW'
        with self.assertRaises(ValueError):validate_plan(self.plan,self.inventory)

    def test_next_codex_pass_only_applies_bounded_face_refinement(self):
        plan={'verdict':'NEEDS_REVISION','differences':['Уточнить выражение и детализацию лица'], 'edits':[]}
        self.assertEqual(validate_plan(plan,self.inventory),plan)
        self.assertEqual(rigging.MIA_CODEX_CORRECTION_EDITS,[])
        self.assertFalse(rigging.MIA_CODEX_HAIR_REBUILD)
        self.assertTrue(rigging.MIA_CODEX_FACE_REFINE)
        self.assertFalse(rigging.MIA_CODEX_PROPORTION_FIT)
    def test_fixed_script_compiles(self):
        compile(BLENDER_SCRIPT,'adaptive_blender.py','exec')
    def test_identical_renders_cannot_pass_visible_change(self):
        raw=bytes([128])*(240*320*3)
        with patch('shutil.which',return_value='ffmpeg'),patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=raw)):
            self.assertFalse(visual_change_gate(Path('before'),Path('after'))['passed'])
    def test_face_and_body_both_require_visible_change(self):
        raw=bytes([128])*(240*320*3);changed=bytes([200])*(240*320*3)
        def output(v):return SimpleNamespace(returncode=0,stdout=v)
        with patch('shutil.which',return_value='ffmpeg'),patch('subprocess.run',side_effect=[output(raw),output(changed),output(raw),output(raw)]):
            self.assertFalse(visual_change_gate(Path('before'),Path('after'))['passed'])

if __name__=='__main__':unittest.main()

import copy
import math
import unittest
from local_agent.blender_rigging import validate_mia_adaptive_plan as validate_plan, MIA_ADAPTIVE_BLENDER_SCRIPT as BLENDER_SCRIPT

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
    def test_fixed_script_compiles(self):
        compile(BLENDER_SCRIPT,'adaptive_blender.py','exec')

if __name__=='__main__':unittest.main()

"""Offline regression tests for the new bounded text -> Blender job pipeline."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from local_agent.prompt_interpreter import PromptError, interpret_scene
from local_agent.studio_jobs import StudioJobError, StudioJobs


def state():
    return {
        'settings': {'fps': 12, 'duration': 3, 'resolution': '360x640'},
        'characters': [{'id': 'mia', 'name': 'Мия'}, {'id': 'stepa', 'name': 'Стёпа'}],
        'scenes': [{'id': 'scene_001', 'prompt': 'Тестовый персонаж идёт, поворачивается и говорит. Камера следует', 'duration': 3}],
    }


class InterpreterTests(unittest.TestCase):
    def test_order_and_camera(self):
        plan = interpret_scene(state()['scenes'][0]['prompt'], state(), 'scene_001')
        self.assertEqual(plan['actions'], ['walk', 'turn', 'speak'])
        self.assertEqual(plan['camera'], 'follow')
        self.assertEqual(plan['readiness'], 'ready_fixture')
        self.assertEqual(plan['total_frames'] if 'total_frames' in plan else plan['fps']*plan['duration'],36)
    def test_turn_wave_speak(self):
        p = interpret_scene('Тестовый персонаж поворачивается, машет и говорит. Камера статичная', state(), 'scene_001')
        self.assertEqual(p['actions'], ['turn','wave','speak'])
        self.assertEqual(p['camera'], 'hold')
    def test_real_mia_requires_model(self):
        p = interpret_scene('Мия идёт по дорожке. Камера следует', state(), 'scene_001')
        self.assertEqual(p['readiness'],'missing_requirements')
        self.assertIn('assets/mia.blend', ' '.join(p['missing_requirements']))
    def test_no_fake_riding(self):
        p=interpret_scene('Тестовый персонаж едет на велосипеде',state(),'scene_001')
        self.assertEqual(p['readiness'],'missing_requirements')
        self.assertTrue(any('транспорта' in x for x in p['missing_requirements']))
    def test_reject_multiple_real_characters(self):
        with self.assertRaises(PromptError):
            interpret_scene('Мия и Стёпа идут',state(),'scene_001')
    def test_reject_injection_unknown(self):
        with self.assertRaises(PromptError):
            interpret_scene('__import__("os").system("calc")',state(),'scene_001')
    def test_reject_real_fixture_mix(self):
        with self.assertRaises(PromptError):
            interpret_scene('Мия и тестовый персонаж идут',state(),'scene_001')
    def test_bounded_length(self):
        with self.assertRaises(PromptError):
            interpret_scene('x'*3001,state(),'scene_001')
    def test_malformed_scene_id(self):
        with self.assertRaises(PromptError):
            interpret_scene('Тестовый персонаж идёт',state(),'../../foo')
    def test_no_recognized_action(self):
        with self.assertRaises(PromptError):
            interpret_scene('Тестовый персонаж прекрасен',state(),'scene_001')


class JobTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store=type('FakeStore',(),{'root':Path(self.dir.name)})()
        self.jobs=StudioJobs(self.store)
    def test_reject_bad_id(self):
        with self.assertRaises(StudioJobError): self.jobs.status('../secret')
    def test_no_blender_jobs_are_not_faked(self):
        with patch('local_agent.blender_locator.find_blender_executable',return_value=None):
            with self.assertRaisesRegex(StudioJobError,'Blender'):
                self.jobs.start(state(),'scene_001')
        self.assertIsNone(self.jobs.latest())
    def test_unresolved_actor_prevents_start(self):
        s=state();s['scenes'][0]['prompt']='Мия идёт в лесу'
        with self.assertRaisesRegex(StudioJobError,'assets/mia.blend'):
            self.jobs.start(s,'scene_001')
    def test_stale_job_recovered_as_interrupted(self):
        d=self.jobs._path('f'*32)
        d.mkdir()
        data={'job_id':'f'*32,'state':'running','message':'', 'total_frames':10,'progress_percent':0}
        self.jobs._write(d,data)
        self.assertEqual(self.jobs.status('f'*32)['state'],'interrupted')
        self.assertEqual(self.jobs.status('f'*32)['state'],'interrupted')
    def test_video_only_after_success(self):
        d=self.jobs._path('e'*32)
        d.mkdir()
        self.jobs._write(d,{'job_id':'e'*32, 'state':'failed'})
        with self.assertRaises(StudioJobError): self.jobs.video('e'*32)

if __name__=='__main__':unittest.main()


def test_reject_action_count_before_job_creation():
    s = state()
    prompt = "Тестовый персонаж " + ", затем ".join(["идёт", "говорит"] * 11)
    with unittest.TestCase().assertRaisesRegex(PromptError, "максимум 20"):
        interpret_scene(prompt, s, "scene_001")


def test_reject_zero_length_action_windows():
    s = state()
    s["settings"].update(duration=1, fps=2)
    with unittest.TestCase().assertRaisesRegex(PromptError, "Недостаточно кадров"):
        interpret_scene("Тестовый персонаж идёт, затем говорит", s, "scene_001")

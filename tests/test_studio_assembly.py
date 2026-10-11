"""Real FFmpeg-only stitching test, deliberately independent from Blender."""
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from local_agent.studio_jobs import StudioJobError, StudioJobs


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local ffmpeg/ffprobe required')
class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=type('Store', (), {'root': Path(self.tmp.name)})()
        self.jobs=StudioJobs(self.store)

    def make_scene(self, label, color):
        job_id=(label*32)[:32]
        d=self.jobs._path(job_id)
        d.mkdir()
        plan={'fps':4, 'duration':1, 'resolution':'640x360'}
        (d/'manifest.json').write_text(json.dumps(plan))
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
             f'color=c={color}:s=640x360:r=4:d=1','-c:v','libx264','-pix_fmt','yuv420p','-y',str(d/'scene.mp4')]
        subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.jobs._write(d,{'job_id':job_id,'scene_id':f'scene_{label}','kind':'scene',
                            'state':'completed','created_at':ord(label),'video_url':f'/api/studio-video/{job_id}'})

    def test_two_scenes_assembled_in_order(self):
        self.make_scene('a','red')
        self.make_scene('b','green')
        state={'scenes':[{'id':'scene_a'},{'id':'scene_b'}]}
        job=self.jobs.compose(state)
        for _ in range(100):
            status=self.jobs.status(job['job_id'])
            if status['state'] not in ('running','queued'):
                break
            time.sleep(.1)
        self.assertEqual(status['state'],'completed',status['message'])
        video=self.jobs.video(job['job_id'])
        probe=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1',str(video)],text=True)
        self.assertIn('duration=',probe)
        self.assertGreater(float(probe.split('=')[1]),1.5)
        self.assertLess(float(probe.split('=')[1]),2.5)
        def frame_rgb(second):
            return subprocess.check_output(['ffmpeg','-v','error','-ss',str(second),'-i',str(video),
                                            '-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'])
        before=frame_rgb(0.3)
        after=frame_rgb(1.3)
        self.assertGreater(before[0], before[1]) # red before green
        self.assertGreater(after[1], after[0])

    def test_missing_scene_rejected(self):
        with self.assertRaisesRegex(StudioJobError,'Сцена'):
            self.jobs.compose({'scenes':[{'id':'scene_a'},{'id':'scene_b'}]})

if __name__=='__main__': unittest.main()

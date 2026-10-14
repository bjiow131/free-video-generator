import ast
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

source = Path('local_agent/poller.py').read_text()
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_run_mia_astra_review')
ns = {'Path': Path, 'os': os, 'json': json, 'Any': object}
exec(compile(ast.Module(body=[node], type_ignores=[]), 'review', 'exec'), ns)
review = ns['_run_mia_astra_review']

class HandoffTests(unittest.TestCase):
    def test_rejects_remote_parameters(self):
        self.assertEqual(review({'prompt': 'override'})['status'], 'rejected')

    def test_latest_checkpoint_request_and_truthful_result(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            ref = base/'episode1/assets/references/mia_turnaround_approved_20261012.jpeg'
            ref.parent.mkdir(parents=True)
            ref.write_bytes(Path('mia_reference.jpeg').read_bytes())
            folder = base/'SOURCE_ADAPTATIONS/mia-codex-scalp-body-v4-20261014'
            views = folder/'pass_1'
            views.mkdir(parents=True)
            (folder/'mia_spring_source_adapted.blend').write_bytes(b'x'*1200)
            (folder/'adaptive_history.json').write_text('{"test_inventory": true}')
            for name in ('front','quarter','side','back','face'):
                (views/(name+'.png')).write_bytes(b'\x89PNG\r\n\x1a\n'+b'x'*1200)
            credentials = types.ModuleType('local_agent.octava_credentials')
            credentials.read_key = lambda: ('test-secret', 'mock')
            policy = types.ModuleType('local_agent.mailbox_policy')
            policy.load_policy = lambda: {'enabled':True,'allow_octava':True,'allow_blender':True}
            calls = []
            class Response:
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def read(self,limit): return json.dumps({'model':'other-model','choices':[{'message':{'content':'NEEDS_REVISION: actual follow-up required'}}]}).encode()
            def transport(request,timeout):
                calls.append((json.loads(request.data), timeout))
                return Response()
            with patch.dict(os.environ, {'LOCAL_AGENT_WORKSPACE':root}), patch.dict('sys.modules', {'local_agent.octava_credentials':credentials,'local_agent.mailbox_policy':policy}), patch('urllib.request.urlopen',transport):
                result = review({})
            self.assertEqual(result['status'],'completed')
            self.assertFalse(result['geometry_changed'])
            self.assertFalse(result['model_verified_by_response'])
            self.assertFalse(result['training_performed'])
            payload, timeout = calls[0]
            self.assertEqual(len(calls),1)
            self.assertEqual(payload['model'],'gpt-6-astra')
            self.assertEqual(timeout,240)
            blocks = payload['messages'][1]['content']
            self.assertEqual(sum(x['type']=='image_url' for x in blocks),6)
            self.assertTrue(blocks[-1]['image_url']['url'].startswith('data:image/png;'))
            self.assertIn('CURRENT_QUARTER', [x.get('text') for x in blocks])
            self.assertTrue((folder/'astra_mia_master_review_20261014.txt').is_file())

if __name__ == '__main__': unittest.main()

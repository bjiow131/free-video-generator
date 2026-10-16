import base64
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from local_agent.studio_state import StudioStore, StudioError, StudioConflict, to_story_plan
from local_agent.studio_server import StudioHTTPServer

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=StudioStore(self.tmp.name)
    def test_default(self):
        s=self.store.load();self.assertEqual(s['revision'],0);self.assertEqual(s['characters'][0]['name'],'Мия')
    def test_round_trip(self):
        s=self.store.load();s['task']='Мия едет на велосипеде';saved=self.store.save(s,0)
        self.assertEqual(saved['revision'],1);self.assertEqual(self.store.load()['task'],s['task'])
    def test_conflict(self):
        s=self.store.load();self.store.save(s,0)
        with self.assertRaises(StudioConflict): self.store.save(s,0)
    def test_path_traversal_project(self):
        with self.assertRaises(StudioError): StudioStore(self.tmp.name,'../outside')
    def test_invalid_id(self):
        s=self.store.load();s['characters'][0]['id']='../../../etc'
        with self.assertRaises(StudioError): self.store.save(s,0)
    def test_duplicate_ids(self):
        s=self.store.load();s['characters'].append(s['characters'][0].copy())
        with self.assertRaises(StudioError): self.store.save(s,0)
    def test_reject_bad_image(self):
        s=self.store.load();s['characters'][0]['reference']='../../hack.png'
        with self.assertRaises(StudioError): self.store.save(s,0)
    def test_reject_unknown_scene_character(self):
        s=self.scene()
        s['scenes'][0]['characters']=['not_a_person']
        with self.assertRaises(StudioError): self.store.save(s,0)
    def test_reject_bool_duration(self):
        s=self.scene();s['scenes'][0]['duration']=True
        with self.assertRaises(StudioError): self.store.save(s,0)
    def test_reject_long_text(self):
        s=self.store.load();s['task']='a'*4001
        with self.assertRaises(StudioError): self.store.save(s,0)
    def test_reject_symlink(self):
        outside=Path(self.tmp.name)/'outside';outside.mkdir()
        (Path(self.tmp.name)/'redirect').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(StudioError): StudioStore(self.tmp.name,'redirect')
    def test_plan(self):
        p=to_story_plan(self.scene());self.assertEqual(p['scenes'][0]['scene_id'],'scene_001');self.assertEqual(p['scenes'][0]['assets'],['Улитка'])
    def test_import_existing_story_without_modification(self):
        plan={"schema_version":1,"project_name":"mia_story","title":"Исходный сценарий",
              "logline":"Мия находит улитку","target_duration_seconds":8,
              "character_bible":{"Мия":{"роль":"Главная героиня","характер":"Любит улиток"},"Стёпа":{"роль":"Друг"}},
              "scenes":[{"scene_id":"scene_001","title":"В лесу","duration_seconds":8,
                         "location":"Лес","action":"Мия идёт и замечает улитку", "camera":"Следящая", "assets":["Улитка"]}]}
        path=self.store.root/'story_plan.json'
        original=json.dumps(plan,ensure_ascii=False)
        path.write_text(original,encoding='utf-8')
        imported=self.store.load()
        self.assertEqual(imported['title'],'Исходный сценарий')
        self.assertEqual(imported['scenes'][0]['title'],'В лесу')
        self.assertTrue(any(c['name']=='Стёпа' for c in imported['characters']))
        self.assertEqual(path.read_text(encoding='utf-8'),original)

    def test_bad_import_preserves_safe_default(self):
        (self.store.root/'story_plan.json').write_text('{bad json}',encoding='utf-8')
        self.assertEqual(self.store.load()['scenes'],[])

    def test_no_scene_plan(self):
        with self.assertRaises(StudioError): to_story_plan(self.store.load())
    def scene(self):
        s=self.store.load();s['task']='Мия находит улитку в лесу'
        s['scenes']=[dict(id='scene_001',title='Встреча',prompt='Мия замечает улитку',location='Лес',camera='Следящая',style='3D',animation='Идёт',status='черновик',preview='',duration=8,characters=['mia'],props=['snail'])]
        s['active_scene']='scene_001'
        return s

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.server=StudioHTTPServer(('127.0.0.1',0),StudioStore(cls.tmp.name),Path(cls.tmp.name)/'approval-state')
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
    def req(self,path,body=None,headers=None):
        data=None if body is None else json.dumps(body).encode()
        h={'Content-Type':'application/json'} if data is not None else {}
        h.update(headers or {})
        req=Request(self.url+path,data=data,headers=h)
        try:
            r=urlopen(req,timeout=5)
        except HTTPError as exc:
            return exc.code,json.loads(exc.read())
        data=r.read()
        return r.status,json.loads(data) if r.headers.get_content_type()=='application/json' else data
    def test_health(self):
        self.assertEqual(self.req('/api/health')[1]['status'],'ok')
    def test_studio_local_approval_round_trip(self):
        now=datetime.now(timezone.utc)
        task=SimpleNamespace(task_id='studio-approval-001',operation='blender_inspect_mia_project',
                             arguments={'project_name':'mia_story'},created_at=now.isoformat(),
                             expires_at=(now+timedelta(minutes=2)).isoformat())
        self.server.approvals.create_request(task)
        code,pending=self.req('/api/agent/approval')
        self.assertEqual(code,200)
        self.assertEqual(pending['pending']['task_id'],task.task_id)
        self.assertEqual(pending['pending']['arguments'],task.arguments)
        code,decision=self.req('/api/agent/approval/decision',
                               {'task_id':task.task_id,'decision':'approve'})
        self.assertEqual(code,200)
        self.assertEqual(decision['decision'],'approve')
        code,duplicate=self.req('/api/agent/approval/decision',
                                {'task_id':task.task_id,'decision':'approve'})
        self.assertEqual(code,409)
        self.assertEqual(self.server.approvals.wait_for_decision(task.task_id,task.expires_at,1),'approve')
        self.server.approvals.clear_request(task.task_id)
        self.assertIsNone(self.req('/api/agent/approval')[1]['pending'])

    def test_studio_approval_rejects_unknown_fields(self):
        code,_=self.req('/api/agent/approval/decision',
                        {'task_id':'studio-approval-002','decision':'approve','command':'unsafe'})
        self.assertEqual(code,400)
    def test_static(self):
        for path in ['/','/style.css','/app.js']:
            code,data=self.req(path);self.assertEqual(code,200);self.assertGreater(len(data),1000)
    def test_host_rejected(self):
        code,_=self.req('/api/state',headers={'Host':'evil.test'});self.assertEqual(code,403)
    def test_origin_rejected(self):
        code,_=self.req('/api/state',{'revision':0,'state':{}},headers={'Origin':'https://evil.test'});self.assertEqual(code,403)
    def test_reject_upload_svg(self):
        code,_=self.req('/api/image',{'extension':'svg','data':base64.b64encode(b'<svg/>').decode()});self.assertEqual(code,400)
    def test_upload_png(self):
        data=base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'garbage').decode()
        code,resp=self.req('/api/image',{'extension':'png','data':data});self.assertEqual(code,201)
        status,raw=self.req(resp['url']);self.assertEqual(status,200);self.assertTrue(raw.startswith(b'\x89PNG'))
    def test_bad_media_name(self):
        code,_=self.req('/media/../../studio_state.json');self.assertEqual(code,404)
    def test_save_and_prepare(self):
        _,s=self.req('/api/state');s['task']='Мия гуляет по лесу';s['scenes']=[dict(id='scene_001',title='Лес',prompt=s['task'],location='Лес',camera='Следящая',style='3D',animation='Ходьба',status='черновик',preview='',duration=8,characters=['mia'],props=[])];s['active_scene']='scene_001'
        code,saved=self.req('/api/state',{'revision':0,'state':s});self.assertEqual(code,200)
        code,prepared=self.req('/api/prepare',{'revision':saved['revision']});self.assertEqual(code,200);self.assertEqual(prepared['readiness'],'planning_only')
        code,_=self.req('/api/prepare',{'revision':saved['revision']});self.assertEqual(code,400) # original plan not overwritten

if __name__=='__main__': unittest.main()

// Regression tests for distinct Studio screens and non-destructive Mia previews.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source=fs.readFileSync(new URL('../local_agent/studio_static/app.js',import.meta.url),'utf8');
const boot=source.indexOf("(async()=>{try{state=await api('/api/state')");
assert.ok(boot>0,'Bootstrap anchor');
const elements=new Map();
function element(key){
  if(!elements.has(key))elements.set(key,{
    innerHTML:'', textContent:'',value:'',style:{},classList:{add(){},remove(){}},
    addEventListener(){},replaceChildren(){},focus(){},
  });
  return elements.get(key);
}
const sandbox={
  document:{querySelector:element,addEventListener(){},createTextNode(s){return s}},
  window:{addEventListener(){}}, crypto:{randomUUID:()=> '12345678-1111-2222-3333-444444444444'},
  clearTimeout(){},setTimeout(){},fetch(){throw new Error('No network in tests')},
};
vm.createContext(sandbox);
vm.runInContext(source.slice(0,boot),sandbox);
const project={
  schema_version:1,revision:0,project:'mia_story',title:'Мия и её приключения',task:'Мия увидела улитку.',
  active_scene:'scene_001',
  characters:[
    {id:'mia',name:'Мия',role:'Главная героиня',age:'4 года',traits:'',appearance:'',outfit:'',voice:'',reference:''},
    {id:'new_1',name:'Новый персонаж',role:'Второстепенный',age:'',traits:'',appearance:'',outfit:'',voice:'',reference:''}
  ],
  props:[],
  scenes:[{id:'scene_001',title:'Первый эпизод',prompt:'Мия гуляет.',location:'Лес',camera:'Статичная',style:'3D-анимация',animation:'Естественное движение',status:'черновик',preview:'',duration:5,characters:['mia'],props:[]}],
  settings:{duration:5,aspect:'9:16',style:'3D-анимация',camera:'Статичная',animation:'Естественное движение',resolution:'360x640',fps:12,sound:'Отдельное аудио'}
};
vm.runInContext('state='+JSON.stringify(project)+';selectedCharacter="mia";approvedMia={status:"ready",character_id:"mia",readiness:[{label:"Утверждённый разворот Мии",status:"ready"}]};',sandbox);
function render(page){vm.runInContext('page='+JSON.stringify(page)+';draw();',sandbox);return element('#main').innerHTML;}

test('Home and Script are distinct functional screens',()=>{
  const home=render('Главная'), script=render('Сценарий');
  assert.match(home,/Настройки сцены/);
  assert.match(script,/Текст сценария \/ задача агенту/);
  assert.match(script,/Структура сцен/);
  assert.match(script,/data-bind="task"/);
  assert.match(script,/data-scene="scene_001"/);
  assert.doesNotMatch(script,/Настройки сцены/);
  assert.notEqual(home,script);
});

test('Character gallery and Passport are distinct, retain current Mia',()=>{
 const roster=render('Персонажи'),passport=render('Паспорта');
 assert.match(roster,/roster-grid/);
 assert.match(roster,/Открыть паспорт/);
 assert.doesNotMatch(roster,/data-character-field="appearance"/);
 assert.match(passport,/data-character-field="appearance"/);
 assert.match(passport,/Утверждённые референсы Мии/);
 assert.match(passport,/Открыть оригинал без изменений/);
 assert.notEqual(roster,passport);
});

test('Mia thumbnail can be separate from intact reference URL',()=>{
 vm.runInContext('miaThumbnailUrl="data:image/jpeg;base64,TEST_THUMB";',sandbox);
 const roster=render('Персонажи'),passport=render('Паспорта');
 assert.match(roster,/data:image\/jpeg;base64,TEST_THUMB/);
 assert.match(passport,/href="\/api\/approved-reference-image\/mia"/);
 assert.match(passport,/data:image\/jpeg;base64,TEST_THUMB/);
});

test('CSS renders actor boards in contain mode, not cover',()=>{
 const css=fs.readFileSync(new URL('../local_agent/studio_static/style.css',import.meta.url),'utf8');
 assert.match(css,/\.person-cover img,\.asset-image img,\.avatar-preview img,\.scene-thumb img\s*\{\s*object-fit:contain/);
 assert.match(css,/\.roster-image img\s*\{[^}]*object-fit:contain/);
});

test('Protected input roles cannot be mistaken for navigation',()=>{
const roster=render('Персонажи'),passport=render('Паспорта');
assert.doesNotMatch(roster,/data-action="link-mia-reference"/);
assert.match(passport,/data-action="link-mia-reference"/);
});

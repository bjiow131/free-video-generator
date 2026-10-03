"""Public-facing account, credit and model API."""
import os, tempfile
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from core.public_store import init_db, create_user, authenticate, create_session, get_user_by_session, revoke_session, ledger, change_credits
from core.api.gemini_image import GeminiImageProvider

router=APIRouter(prefix="/api/public",tags=["public"])
init_db()
class AuthBody(BaseModel):
    email:str
    password:str=Field(min_length=8,max_length=200)

def token(request):
    return request.cookies.get("ai_session") or request.headers.get("Authorization","").removeprefix("Bearer ").strip()
def user(request):
    u=get_user_by_session(token(request))
    if not u: raise HTTPException(401,"Требуется вход")
    return u

@router.post("/register")
def register(body:AuthBody):
    try: uid,email=create_user(body.email,body.password)
    except ValueError as e: raise HTTPException(422,str(e))
    return {"ok":True,"token":create_session(uid),"email":email,"credits":50}

@router.post("/login")
def login(body:AuthBody):
    found=authenticate(body.email,body.password)
    if not found: raise HTTPException(401,"Неверный email или пароль")
    uid,email=found
    return {"ok":True,"token":create_session(uid),"email":email}

@router.post("/logout")
def logout(request:Request):
    revoke_session(token(request)); return {"ok":True}

@router.get("/me")
def me(request:Request): return user(request)

@router.get("/ledger")
def get_ledger(request:Request): return {"items":ledger(user(request)["id"])}

@router.get("/models")
def models():
    return {"models":[
      {"id":"nano-banana-2","name":"Nano Banana 2","provider":"Google","type":"image","credits":10,"status":"ready","description":"Универсальная генерация и редактирование изображений"},
      {"id":"nano-banana-pro","name":"Nano Banana Pro","provider":"Google","type":"image","credits":25,"status":"ready","description":"Профессиональные изображения до 4K"},
      {"id":"veo-3.1","name":"Veo 3.1","provider":"Google","type":"video","credits":150,"status":"coming_soon","description":"Кинематографическое видео с нативным аудио"},
      {"id":"veo-3.1-lite","name":"Veo 3.1 Lite","provider":"Google","type":"video","credits":80,"status":"coming_soon","description":"Более экономичная генерация видео"},
    ]}

@router.post("/generate/image")
async def generate_image(request:Request,prompt:str=Form(...),model:str=Form("nano-banana-2"),reference:UploadFile=File(None)):
    u=user(request)
    costs={"nano-banana-2":10,"nano-banana-pro":25}
    if model not in costs: raise HTTPException(400,"Эта модель пока недоступна")
    cost=costs[model]
    if u["credits"]<cost: raise HTTPException(402,"Недостаточно кредитов")
    if not prompt.strip(): raise HTTPException(422,"Промпт не может быть пустым")
    ref=[]
    if reference and reference.filename:
        suffix=os.path.splitext(reference.filename)[1] or ".png"
        fd,path=tempfile.mkstemp(suffix=suffix,prefix="ai_ref_"); os.close(fd)
        with open(path,"wb") as f: f.write(await reference.read())
        ref=[path]
    try:
        provider=GeminiImageProvider(model="gemini-3.1-flash-image" if model=="nano-banana-2" else "gemini-3-pro-image")
        output=await provider.generate(prompt.strip(),ref)
        balance=change_credits(u["id"],-cost,"generation",model)
        return FileResponse(output,media_type="image/png",headers={"X-Credits-Remaining":str(balance["credits"])})
    except Exception as e:
        raise HTTPException(502,f"Генерация не выполнена: {e}")

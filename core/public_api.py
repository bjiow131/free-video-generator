"""Public-facing account, credit and model API."""
import os, tempfile, asyncio
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from core.public_store import init_db, create_user, authenticate, create_session, get_user_by_session, revoke_session, ledger, change_credits, add_generation, generations, update_generation
from core.api.google_video import GoogleVideoProvider
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

@router.get("/history")
def get_history(request:Request): return {"items":generations(user(request)["id"])}

@router.get("/models")
def models():
    return {"models":[
      {"id":"nano-banana-2","name":"Nano Banana 2","provider":"Google","type":"image","credits":10,"status":"ready","description":"Универсальная генерация и редактирование изображений"},
      {"id":"nano-banana-pro","name":"Nano Banana Pro","provider":"Google","type":"image","credits":25,"status":"ready","description":"Профессиональные изображения до 4K"},
      {"id":"veo-3.1","name":"Veo 3.1","provider":"Google","type":"video","credits":400,"status":"ready","description":"Кинематографическое видео с нативным аудио"},
      {"id":"veo-3.1-lite","name":"Veo 3.1 Lite","provider":"Google","type":"video","credits":100,"status":"ready","description":"Более экономичная генерация видео"},
    ]}

@router.post("/generate/image")
async def generate_image(request:Request,prompt:str=Form(...),model:str=Form("nano-banana-2"),reference:UploadFile=File(None)):
    u=user(request)
    costs={"nano-banana-2":10,"nano-banana-pro":25}
    if model not in costs: raise HTTPException(400,"Эта модель пока недоступна")
    cost=costs[model]
    if not prompt.strip(): raise HTTPException(422,"Промпт не может быть пустым")
    if u["credits"]<cost: raise HTTPException(402,"Недостаточно кредитов")

    ref=[]
    try:
        if reference and reference.filename:
            suffix=os.path.splitext(reference.filename)[1].lower() or ".png"
            if suffix not in {".png",".jpg",".jpeg",".webp"}:
                raise HTTPException(415,"Поддерживаются PNG, JPG и WebP")
            data=await reference.read()
            if len(data)>10*1024*1024:
                raise HTTPException(413,"Изображение слишком большое (максимум 10 МБ)")
            fd,path=tempfile.mkstemp(suffix=suffix,prefix="ai_ref_"); os.close(fd)
            with open(path,"wb") as f: f.write(data)
            ref=[path]

        # Reserve credits before generation; refund automatically if the provider fails.
        balance=change_credits(u["id"],-cost,"generation",model)
        provider=GeminiImageProvider(model="gemini-3.1-flash-image" if model=="nano-banana-2" else "gemini-3-pro-image")
        output=await provider.generate(prompt.strip(),ref)
        generation_id=add_generation(u["id"],model,"image",prompt.strip(),"completed",output,cost)
        return FileResponse(output,media_type="image/png",headers={"X-Credits-Remaining":str(balance["credits"]),"X-Generation-Id":generation_id})
    except HTTPException:
        raise
    except Exception:
        try:
            # Refund a reserved charge if generation did not complete.
            if 'balance' in locals():
                change_credits(u["id"],cost,"refund",model)
                add_generation(u["id"],model,"image",prompt.strip(),"failed",None,0)
        except Exception:
            pass
        raise HTTPException(502,"Генерация не выполнена")
    finally:
        for path in ref:
            try: os.remove(path)
            except OSError: pass

async def _run_video_generation(user_id,generation_id,prompt,model,cost,reference_path=None,aspect_ratio="16:9",resolution="720p"):
    try:
        provider=GoogleVideoProvider(
            model="veo-3.1-generate-preview" if model=="veo-3.1" else "veo-3.1-lite-generate-preview"
        )
        output=await provider.generate(prompt,reference_path,aspect_ratio,resolution)
        update_generation(generation_id,"completed",output)
    except Exception:
        try:
            change_credits(user_id,cost,"refund",model)
            update_generation(generation_id,"failed",None)
        except Exception:
            pass
    finally:
        if reference_path:
            try: os.remove(reference_path)
            except OSError: pass

@router.post("/generate/video")
async def generate_video(request:Request,prompt:str=Form(...),model:str=Form("veo-3.1"),aspect_ratio:str=Form("16:9"),resolution:str=Form("720p"),reference:UploadFile=File(None)):
    u=user(request)
    costs={"veo-3.1":400,"veo-3.1-lite":100}
    if model not in costs: raise HTTPException(400,"Эта модель пока недоступна")
    if not prompt.strip(): raise HTTPException(422,"Промпт не может быть пустым")
    if aspect_ratio not in {"16:9","9:16"}: raise HTTPException(422,"Неподдерживаемое соотношение сторон")
    if resolution not in {"720p","1080p","4k"}: raise HTTPException(422,"Неподдерживаемое разрешение")
    if model=="veo-3.1-lite" and resolution=="4k": raise HTTPException(422,"Veo 3.1 Lite не поддерживает 4K")
    cost=costs[model]
    if u["credits"]<cost: raise HTTPException(402,"Недостаточно кредитов")

    ref_path=None
    try:
        if reference and reference.filename:
            suffix=os.path.splitext(reference.filename)[1].lower() or ".png"
            if suffix not in {".png",".jpg",".jpeg",".webp"}:
                raise HTTPException(415,"Поддерживаются PNG, JPG и WebP")
            data=await reference.read()
            if len(data)>10*1024*1024: raise HTTPException(413,"Изображение слишком большое (максимум 10 МБ)")
            fd,ref_path=tempfile.mkstemp(suffix=suffix,prefix="ai_ref_"); os.close(fd)
            with open(ref_path,"wb") as f: f.write(data)

        change_credits(u["id"],-cost,"generation",model)
        generation_id=add_generation(u["id"],model,"video",prompt.strip(),"processing",None,cost)
        asyncio.create_task(_run_video_generation(
            u["id"],generation_id,prompt.strip(),model,cost,ref_path,aspect_ratio,resolution
        ))
        ref_path=None
        return {"ok":True,"generation_id":generation_id,"status":"processing","credits":u["credits"]-cost}
    except HTTPException:
        raise
    except Exception:
        if ref_path:
            try: os.remove(ref_path)
            except OSError: pass
        raise HTTPException(502,"Не удалось запустить генерацию видео")

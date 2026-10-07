"""Google Gemini native image provider (Nano Banana 2 / Pro)."""
import asyncio,base64,os,tempfile
class GeminiImageProvider:
 def __init__(self,api_key=None,model=None):
  self.api_key=api_key or os.environ.get("GEMINI_API_KEY","")
  self.model=model or os.environ.get("GEMINI_IMAGE_MODEL","gemini-3.1-flash-image")
 async def generate(self,prompt,reference_paths=None):
  if not self.api_key: raise RuntimeError("Google Gemini API key не настроен")
  return await asyncio.to_thread(self._sync,prompt,reference_paths or [])
 def _sync(self,prompt,reference_paths):
  from google import genai
  client=genai.Client(api_key=self.api_key)
  items=[{"type":"text","text":prompt}]
  for path in reference_paths:
   with open(path,"rb") as f: data=base64.b64encode(f.read()).decode()
   mime="image/jpeg" if path.lower().endswith((".jpg",".jpeg")) else "image/png"
   items.append({"type":"image","data":data,"mime_type":mime})
  interaction=client.interactions.create(model=self.model,input=items)
  output=getattr(interaction,"output_image",None)
  if output is None: raise RuntimeError("Google Gemini не вернул изображение")
  data=getattr(output,"data",None)
  if not data: raise RuntimeError("Google Gemini вернул пустое изображение")
  path=os.path.join(tempfile.gettempdir(), "ai_studio_gemini_%s.png"%os.urandom(8).hex())
  with open(path,"wb") as f:f.write(base64.b64decode(data))
  return path

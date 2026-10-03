"""Google Gemini / Nano Banana image provider."""
import asyncio,os
class GeminiImageProvider:
 def __init__(self,api_key=None,model=None): self.api_key=api_key or os.environ.get("GEMINI_API_KEY",""); self.model=model or os.environ.get("GEMINI_IMAGE_MODEL","gemini-3.1-flash-image")
 async def generate(self,prompt,reference_paths=None,aspect_ratio="1:1",resolution="1K"):
  if not self.api_key: raise RuntimeError("Google Gemini API пока не настроен на сервере")
  return await asyncio.to_thread(self._generate_sync,prompt,reference_paths or [],aspect_ratio,resolution)
 def _generate_sync(self,prompt,reference_paths,aspect_ratio,resolution):
  from google import genai
  from google.genai import types
  client=genai.Client(api_key=self.api_key); contents=[]
  for path in reference_paths:
   with open(path,"rb") as f:data=f.read()
   mime="image/jpeg" if path.lower().endswith((".jpg",".jpeg")) else "image/png"
   contents.append(types.Part.from_bytes(data=data,mime_type=mime))
  contents.append(prompt)
  response=client.models.generate_content(model=self.model,contents=contents,config=types.GenerateContentConfig(response_modalities=["IMAGE"],response_format={"image":{"aspect_ratio":aspect_ratio,"image_size":resolution}}))
  for part in response.parts:
   if getattr(part,"thought",False): continue
   if getattr(part,"inline_data",None) is not None:
    image=part.as_image(); tmp="/tmp/ai_studio_gemini_%s.png"%os.urandom(8).hex(); image.save(tmp); return tmp
  raise RuntimeError("Google Gemini не вернул изображение")

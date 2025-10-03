from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os

# --- 環境変数から取得 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Viteフロント
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/list")
def list_files(prefix: str = ""):
    try:
        files = supabase.storage.from_(SUPABASE_BUCKET).list(path=prefix)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    try:
        content = await file.read()
        stored_name = f"{staff}/{file.filename}"  # staff フォルダ内に保存
        supabase.storage.from_(SUPABASE_BUCKET).upload(stored_name, content)
        return {"message": "アップロード成功", "filename": stored_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signed-url/{staff}/{filename}")
def get_signed_url(staff: str, filename: str):
    try:
        stored_name = f"{staff}/{filename}"
        expires_in = 60 * 60 * 24 * 365  # 1年
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(stored_name, expires_in)
        return {"url": signed_url["signedURL"] if isinstance(signed_url, dict) else signed_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete/{filename}")
def delete_file(filename: str):
    """
    Supabase Storage から指定ファイルを削除
    """
    try:
        res = supabase.storage.from_(SUPABASE_BUCKET).remove([filename])
        return {"message": f"{filename} を削除しました", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

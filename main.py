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
def list_files():
    """
    Supabase バケット内のファイル一覧を返す
    """
    try:
        files = supabase.storage.from_(SUPABASE_BUCKET).list()
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    動画を Supabase Storage にアップロード
    """
    try:
        content = await file.read()
        supabase.storage.from_(SUPABASE_BUCKET).upload(file.filename, content)

        return {"message": "アップロード成功", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signed-url/{filename}")
def get_signed_url(filename: str):
    """
    Supabase から署名付きURLを発行して返す
    有効期限: 1年
    """
    try:
        expires_in = 60 * 60 * 24 * 365  # 1年
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(filename, expires_in)

        if isinstance(signed_url, dict) and "signedURL" in signed_url:
            return {"url": signed_url["signedURL"]}
        else:
            return {"url": signed_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os
from datetime import datetime

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
def list_all_files():
    """全動画ファイル一覧"""
    try:
        files = supabase.storage.from_(SUPABASE_BUCKET).list()
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list/{staff_name}")
def list_staff_files(staff_name: str):
    """特定スタッフのフォルダ内だけ一覧"""
    try:
        files = supabase.storage.from_(SUPABASE_BUCKET).list(path=staff_name)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload/{staff_name}")
async def upload_file(staff_name: str, file: UploadFile = File(...)):
    """
    スタッフごとにフォルダ分けしてアップロード
    例: videos/staffA/20251003-xxxx.mp4
    """
    try:
        content = await file.read()

        # ファイル名にタイムスタンプを付与
        import time
        unique_name = f"{int(time.time())}_{file.filename}"

        # パスを staff_name のフォルダに振り分け
        file_path = f"{staff_name}/{unique_name}"

        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, content)

        return {"message": "アップロード成功", "filename": file_path}
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


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


@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    """
    指定スタッフのフォルダに動画をアップロード
    ファイル名は `YYYYMMDD-HHMMSS_元ファイル名`
    """
    try:
        # ユニークなファイル名を作成
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"

        # staff フォルダ付きのパス
        path = f"{staff}/{unique_filename}"

        # ファイル内容を読み込んでアップロード
        content = await file.read()
        supabase.storage.from_(SUPABASE_BUCKET).upload(path, content)

        return {
            "message": "アップロード成功",
            "filename": unique_filename,
            "path": path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

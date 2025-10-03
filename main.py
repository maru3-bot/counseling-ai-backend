from fastapi import FastAPI, File, UploadFile, HTTPException
from supabase import create_client
import os
from datetime import datetime, timezone  # ← 修正ポイント
from typing import Optional

from dotenv import load_dotenv

app = FastAPI()

# .env ファイルを読み込み、必要な環境変数が読み込まれるようにする
load_dotenv()

# Supabase クライアント設定
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

# Supabase クライアント生成時に発生したエラーを保持しておく
supabase: Optional = None
supabase_initialization_error: Optional[str] = None

try:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase credentials are not configured")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as exc:  # noqa: BLE001 - 外部ライブラリの例外をまとめて補足
    supabase_initialization_error = str(exc)

@app.get("/")
def read_root():
    return {"message": "Hello from Counseling AI Backend!"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if supabase_initialization_error:
        raise HTTPException(status_code=500, detail=supabase_initialization_error)
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client is not available")

    try:
        contents = await file.read()

        # 日付方式でファイル名を作成
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        file_path = f"{timestamp}_{file.filename}"

        # Supabase にアップロード
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=file_path,
            file=contents
        )

        # 結果を安全に返却
        return {
            "message": "Upload successful",
            "filename": file.filename,
            "stored_as": file_path,
            "upload_result": str(res)  # ← ここで文字列にする
        }
    except Exception as e:
        return {"error": str(e)}

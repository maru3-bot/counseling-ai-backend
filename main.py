from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os
from datetime import datetime, timezone  # ← 修正ポイント

app = FastAPI()

# Supabase クライアント設定
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.get("/")
def read_root():
    return {"message": "Hello from Counseling AI Backend!"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
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

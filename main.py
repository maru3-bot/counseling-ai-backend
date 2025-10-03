from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os
import datetime

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
        # ファイル読み込み
        contents = await file.read()
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        file_path = f"{timestamp}_{file.filename}"

        # Supabase にアップロード
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=file_path,
            file=contents
        )

        # レスポンスを dict に変換
        return {
            "message": "Upload successful",
            "filename": file.filename,
            "saved_as": file_path,
            "result": str(res)   # ← ここを str() に変える
        }
    except Exception as e:
        return {"error": str(e)}

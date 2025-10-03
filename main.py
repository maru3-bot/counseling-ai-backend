from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os
from datetime import datetime, timezone

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
        # 日付つきファイル名を生成（例: 20251003-120500_test.mp4）
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        stored_name = f"{timestamp}_{file.filename}"

        # バイナリを読み込んでアップロード
        contents = await file.read()
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=stored_name,
            file=contents
        )

        # 公開URLを取得
        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(stored_name)

        return {
            "message": "Upload successful",
            "filename": file.filename,
            "stored_as": stored_name,
            "public_url": public_url  # 👈 ここで公開URLを返す
        }

    except Exception as e:
        return {"error": str(e)}


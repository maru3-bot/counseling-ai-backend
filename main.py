from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os

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
        # バイト列を取得
        contents = await file.read()

        # Supabase にアップロード（bytes をそのまま渡す）
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=file.filename,
            file=contents
        )

        return {"message": "Upload successful", "filename": file.filename, "result": res}
    except Exception as e:
        return {"error": str(e)}

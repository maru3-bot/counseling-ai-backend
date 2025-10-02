from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os
import uuid

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
        # UUID + 元のファイル名 で一意化
        unique_name = f"{uuid.uuid4()}_{file.filename}"

        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=unique_name,
            file=contents
        )

        return {
            "message": "Upload successful",
            "original_filename": file.filename,
            "saved_as": unique_name,
            "result": res
        }
    except Exception as e:
        return {"error": str(e)}


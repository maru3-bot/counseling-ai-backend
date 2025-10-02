from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os

app = FastAPI()

# Supabase クライアント設定
SUPABASE_URL = os.getenv("https://yorzedcwxbltzyvebczv.supabase.co")
SUPABASE_KEY = os.getenv("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlvcnplZGN3eGJsdHp5dmViY3p2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTkzNzAzMTgsImV4cCI6MjA3NDk0NjMxOH0.htysO4i9gQdp7NGiZ9lzgCL-IkASO6Mew1ztN071Hrs")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.get("/")
def read_root():
    return {"message": "Hello from Counseling AI Backend!"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # ファイルを一時保存
        contents = await file.read()
        file_path = f"{file.filename}"

        # Supabase にアップロード
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            file_path, contents, {"upsert": True}
        )

        return {"message": "Upload successful", "filename": file.filename, "result": res}
    except Exception as e:
        return {"error": str(e)}

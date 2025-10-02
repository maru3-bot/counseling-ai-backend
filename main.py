from fastapi import FastAPI, File, UploadFile
from supabase import create_client
import os
import tempfile

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
        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        # Supabase にアップロード（ここはファイルパスを渡す必要あり）
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=file.filename,
            file=tmp_path  # ← bytes ではなくファイルパスを渡す
        )

        return {"message": "Upload successful", "filename": file.filename, "result": res}
    except Exception as e:
        return {"error": str(e)}



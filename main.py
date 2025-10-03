from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware  # ← これを追加！
from supabase import create_client
import os
from datetime import datetime, timezone


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 全部許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        stored_name = f"{timestamp}_{file.filename}"

        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=stored_name,
            file=contents,
        )

        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(stored_name)

        return {
            "message": "Upload successful",
            "filename": file.filename,
            "stored_as": stored_name,
            "public_url": public_url,
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/list")
def list_files():
    try:
        files = supabase.storage.from_(SUPABASE_BUCKET).list()
        file_list = []

        for f in files:
            name = f["name"]
            public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(name)
            file_list.append({"filename": name, "public_url": public_url})

        return {"files": file_list}
    except Exception as e:
        return {"error": str(e)}

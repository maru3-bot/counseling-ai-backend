from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os

# --- 環境変数 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # フロントのURL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Supabase Storage に動画ファイルをアップロード
    """
    try:
        # ファイル名（ユニーク化する）
        filename = file.filename
        file_bytes = await file.read()

        # Supabase に保存
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=filename,
            file=file_bytes,
            file_options={"content-type": file.content_type},
        )

        if res.get("error"):
            raise HTTPException(status_code=400, detail=res["error"]["message"])

        return {"message": "アップロード成功", "filename": filename}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

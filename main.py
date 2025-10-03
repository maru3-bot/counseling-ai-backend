from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os

# --- 環境変数から取得 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key推奨
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # React (Vite) のポート
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# スタッフ別フォルダにアップロード
@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    try:
        content = await file.read()
        stored_name = f"{staff}/{file.filename}"  # staffA/xxx.mp4
        supabase.storage.from_(SUPABASE_BUCKET).upload(stored_name, content)
        return {"message": "アップロード成功", "filename": stored_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# スタッフ別フォルダ内の動画一覧を返す
@app.get("/list/{staff}")
def list_files(staff: str):
    try:
        files = supabase.storage.from_(SUPABASE_BUCKET).list(path=staff)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 署名付きURL発行（スタッフ別対応）
@app.get("/signed-url/{staff}/{filename}")
def get_signed_url(staff: str, filename: str):
    try:
        expires_in = 60 * 60 * 24 * 365  # 1年
        full_path = f"{staff}/{filename}"
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(full_path, expires_in)

        if isinstance(signed_url, dict) and "signedURL" in signed_url:
            return {"url": signed_url["signedURL"]}
        else:
            return {"url": signed_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

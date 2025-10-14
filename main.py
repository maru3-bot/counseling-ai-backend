import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

# ===== 環境変数 =====
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

# ===== Supabase 接続 =====
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Supabase URL または SERVICE_ROLE_KEY が設定されていません")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ===== FastAPI アプリ設定 =====
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番では必要に応じて制限
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 動作確認用エンドポイント =====
@app.get("/")
def root():
    return {"ok": True, "message": "Backend is running."}

# ===== ファイル一覧取得 =====
@app.get("/list/{staff_id}")
def list_files(staff_id: str):
    try:
        folder_path = f"{staff_id}/"
        res = supabase.storage.from_(SUPABASE_BUCKET).list(folder_path)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===== ファイルアップロード =====
@app.post("/upload/{staff_id}")
async def upload_file(staff_id: str, file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_path = f"{staff_id}/{file.filename}"
        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, contents)
        return {"ok": True, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


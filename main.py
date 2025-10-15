import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

# ===== 環境変数 =====
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

# フロントエンドのURL（クラウド環境で設定）
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://counseling-ai-frontend.onrender.com")
# デバッグモード
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# ===== Supabase 接続 =====
supabase = None
supabase_error = None

try:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("Supabase URL または SERVICE_ROLE_KEY が設定されていません")
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    print("Supabase接続成功")
except Exception as e:
    supabase_error = str(e)
    print(f"Supabase接続エラー: {e}")

# ===== FastAPI アプリ設定 =====
app = FastAPI()

# CORSの設定（クラウド環境で特定のドメインのみを許可）
allowed_origins = [FRONTEND_URL]
if DEBUG:
    allowed_origins.append("*")  # デバッグ時は全て許可
    print("デバッグモード: CORS制限なし")
else:
    print(f"本番モード: CORS許可オリジン = {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 動作確認用エンドポイント =====
@app.get("/")
def root():
    return {
        "ok": True, 
        "message": "Backend is running.",
        "env": {
            "supabase_url_set": bool(SUPABASE_URL),
            "supabase_key_set": bool(SUPABASE_SERVICE_ROLE_KEY),
            "bucket": SUPABASE_BUCKET,
            "frontend_url": FRONTEND_URL,
            "debug_mode": DEBUG,
            "allowed_origins": allowed_origins
        },
        "supabase_status": "connected" if supabase else f"error: {supabase_error}"
    }

# ===== ファイル一覧取得 =====
@app.get("/list/{staff_id}")
def list_files(staff_id: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        folder_path = f"{staff_id}/"
        print(f"フォルダパス: {folder_path} のファイル一覧取得")
        res = supabase.storage.from_(SUPABASE_BUCKET).list(folder_path)
        return res
    except Exception as e:
        error_msg = f"ファイル一覧取得エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== ファイルアップロード =====
@app.post("/upload/{staff_id}")
async def upload_file(staff_id: str, file: UploadFile = File(...)):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        contents = await file.read()
        file_path = f"{staff_id}/{file.filename}"
        print(f"アップロード: {file_path}, サイズ: {len(contents)} bytes")
        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, contents)
        return {"ok": True, "path": file_path}
    except Exception as e:
        error_msg = f"アップロードエラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== ヘルスチェック =====
@app.get("/healthz")
def healthz():
    return {"status": "healthy"}
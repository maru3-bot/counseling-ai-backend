import os
import mimetypes
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

# --- 環境変数 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # 必ず Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# CORS（ローカル開発用）。本番では許可ドメインを絞ってください。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def guess_content_type(filename: str, fallback: Optional[str] = None) -> str:
    """アップロード時の Content-Type を推定。text/plain を避ける。"""
    ct, _ = mimetypes.guess_type(filename)
    if not ct or ct.startswith("text/"):
        ext = (os.path.splitext(filename)[1] or "").lower()
        return {
            ".mp4": "video/mp4",
            ".m4v": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".aac": "audio/aac",
        }.get(ext, fallback or "application/octet-stream")
    return ct

def strip_download_param(signed_url: str) -> str:
    """Supabaseの署名URLから download= パラメータを除去して inline 再生しやすくする"""
    p = urlparse(signed_url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() != "download"]
    new_query = urlencode(q)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    """
    指定スタッフのフォルダに動画/音声をアップロード
    ファイル名は `YYYYMMDD-%H%M%S_元ファイル名`
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"
        path = f"{staff}/{unique_filename}"

        content = await file.read()
        content_type = guess_content_type(file.filename, fallback=(file.content_type or None))

        # Supabase SDK v2: file_options のキーはハイフン、値は文字列
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path,
            content,
            file_options={"content-type": content_type, "x-upsert": "true"},
        )

        return {"message": "アップロード成功", "filename": unique_filename, "path": path, "content_type": content_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list/{staff}")
def list_files(staff: str):
    try:
        items = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        return {"files": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signed-url/{staff}/{filename}")
def get_signed_url(staff: str, filename: str, expires_sec: int = 3600):
    try:
        path = f"{staff}/{filename}"
        res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires_sec)

        # SDKの戻り形がdict or オブジェクトの差異に耐性を持たせる
        url = None
        if isinstance(res, dict):
            url = res.get("signedURL") or res.get("signed_url") or (res.get("data") or {}).get("signedURL") or (res.get("data") or {}).get("signed_url")
        if not url:
            url = getattr(res, "signedURL", None) or getattr(res, "signed_url", None) or getattr(getattr(res, "data", None), "signedURL", None) or getattr(getattr(res, "data", None), "signed_url", None)
        if not url:
            raise HTTPException(404, f"Signed URL not returned for path: {path}")

        return {"url": strip_download_param(url)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"signed-url error: {e}")

@app.delete("/delete/{staff}/{filename}")
def delete_file(staff: str, filename: str):
    """
    Supabase Storage から該当ファイルを削除。
    assessments を使っている場合は、併せてレコードも削除推奨。
    """
    try:
        path = f"{staff}/{filename}"
        # Storage 削除
        supabase.storage.from_(SUPABASE_BUCKET).remove([path])

        # もし assessments を運用しているなら、下記を有効化
        # try:
        #     supabase.table("assessments").delete().eq("staff", staff).eq("filename", filename).execute()
        # except Exception:
        #     pass

        return {"message": "deleted", "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete error: {e}")
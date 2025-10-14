import os
import io
import json
import mimetypes
import shutil
import subprocess
import tempfile
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, List
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from app_prompt_loader import PromptManager

# ✅ FastAPI インスタンスを最初に1回だけ作成
app = FastAPI()

# ✅ CORS設定（本番URLとローカル開発用を許可）
origins = [
    "https://counseling-ai-frontend.onrender.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 環境変数
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")
MODEL_MODE = os.getenv("USE_MODEL", "low")  # "low" or "high"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。")

try:
    from openai import OpenAI  # openai>=1.x
except Exception:
    OpenAI = None

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
prompt_manager = PromptManager()

MAX_WHISPER_BYTES = 25 * 1024 * 1024
MAX_CHARS_PER_CHUNK = 4000
CHUNK_OVERLAP = 400

logger = logging.getLogger("app")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# --- ヘルスチェック ---
@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": MODEL_MODE}


# --- ファイル処理 ---
EXTENSION_CT_MAP = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".wav": "audio/wav", ".aac": "audio/aac",
}

def guess_content_type(filename: str, fallback: Optional[str] = None) -> str:
    ct, _ = mimetypes.guess_type(filename)
    if not ct or ct.startswith("text/"):
        ext = (os.path.splitext(filename)[1] or "").lower()
        return EXTENSION_CT_MAP.get(ext, fallback or "application/octet-stream")
    return ct

def strip_download_param(signed_url: str) -> str:
    p = urlparse(signed_url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() != "download"]
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))

@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unique_filename = f"{timestamp}_{file.filename}"
    path = f"{staff}/{unique_filename}"
    content = await file.read()
    content_type = guess_content_type(file.filename, file.content_type)
    supabase.storage.from_(SUPABASE_BUCKET).upload(path, content, file_options={
        "content-type": content_type, "x-upsert": "true"
    })
    return {"message": "アップロード成功", "filename": unique_filename, "path": path, "content_type": content_type}

@app.get("/list/{staff}")
def list_files(staff: str):
    items = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
    return {"files": items}

@app.get("/signed-url/{staff}/{filename}")
def get_signed_url(staff: str, filename: str, expires_sec: int = 3600):
    path = f"{staff}/{filename}"
    res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires_sec)
    url = res.get("signedURL") or (res.get("data") or {}).get("signedURL")
    if not url:
        raise HTTPException(404, "Signed URL not found")
    return {"url": strip_download_param(url)}

@app.delete("/delete/{staff}/{filename}")
def delete_file(staff: str, filename: str):
    path = f"{staff}/{filename}"
    supabase.storage.from_(SUPABASE_BUCKET).remove([path])
    return {"message": "deleted", "path": path}

def download_file_bytes(staff: str, filename: str) -> bytes:
    return supabase.storage.from_(SUPABASE_BUCKET).download(f"{staff}/{filename}")


# --- Whisper ---
def transcode_for_whisper(file_bytes: bytes, filename: str) -> Tuple[bytes, str]:
    if len(file_bytes) <= MAX_WHISPER_BYTES:
        return file_bytes, filename
    if shutil.which("ffmpeg") is None:
        raise HTTPException(413, "ffmpegが見つかりません")
    bitrates = ["64k", "48k", "32k"]
    base, _ = os.path.splitext(os.path.basename(filename))
    with tempfile.TemporaryDirectory() as d:
        in_path = os.path.join(d, f"{base}_in")
        out_path = os.path.join(d, f"{base}_out.m4a")
        with open(in_path, "wb") as f:
            f.write(file_bytes)
        for br in bitrates:
            cmd = ["ffmpeg", "-y", "-i", in_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", br, out_path]
            if subprocess.run(cmd).returncode == 0:
                data = open(out_path, "rb").read()
                if len(data) <= MAX_WHISPER_BYTES:
                    return data, f"{base}.m4a"
    raise HTTPException(413, "25MB以下に圧縮できませんでした")

def get_openai_client():
    return OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY and OpenAI else None

def get_openai_transcript(file_bytes: bytes, filename: str) -> str:
    client = get_openai_client()
    if not client:
        raise HTTPException(500, "OPENAI API未設定")
    send_bytes, send_name = transcode_for_whisper(file_bytes, filename)
    bio = io.BytesIO(send_bytes); bio.name = send_name
    tr = client.audio.transcriptions.create(model="whisper-1", file=bio, response_format="text")
    return getattr(tr, "text", tr) if isinstance(tr, str) or hasattr(tr, "text") else ""


# --- 分析 ---
def _chat_json(client, model, system_prompt, user_content):
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return json.loads(getattr(resp.choices[0].message, "content", "") or "{}")

def analyze_with_openai(transcript, model):
    client = get_openai_client()
    if not client:
        raise HTTPException(500, "OpenAI API未設定")
    return _chat_json(client, model, prompt_manager.get_analyze_prompt(), transcript)

def analyze(transcript):
    model = "gpt-4o-mini" if MODEL_MODE == "low" else "gpt-4o"
    return model, analyze_with_openai(transcript, model)

@app.post("/analyze/{staff}/{filename}")
def run_analysis(staff: str, filename: str, force: bool = False):
    if not force:
        existing = get_assessment(staff, filename)
        if existing:
            return existing
    file_bytes = download_file_bytes(staff, filename)
    transcript = get_openai_transcript(file_bytes, filename)
    model_name, analysis = analyze(transcript)
    return upsert_assessment(staff, filename, transcript, MODEL_MODE, model_name, analysis)

@app.get("/analysis/{staff}/{filename}")
def fetch_analysis(staff: str, filename: str):
    found = get_assessment(staff, filename)
    if not found:
        raise HTTPException(404, "分析結果がありません")
    return found

@app.get("/results/{staff}")
def list_results(staff: str):
    res = supabase.table("assessments").select("*").eq("staff", staff).order("created_at", desc=True).execute()
    return {"results": res.data if hasattr(res, "data") else []}

def upsert_assessment(staff, filename, transcript, model_mode, model_name, analysis):
    now = datetime.utcnow().isoformat()
    record = {
        "staff": staff,
        "filename": filename,
        "transcript": transcript,
        "model_mode": model_mode,
        "model_name": model_name,
        "analysis": analysis,
        "created_at": now,
    }
    try:
        supabase.table("assessments").upsert(record, on_conflict="staff,filename").execute()
    except Exception as e:
        logger.warning("assessments upsert failed: %s", e)
    return record

def get_assessment(staff, filename):
    try:
        q = supabase.table("assessments").select("*").eq("staff", staff).eq("filename", filename).limit(1).execute()
        rows = getattr(q, "data", None) or []
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("assessments select failed: %s", e)
        return None

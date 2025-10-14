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

from app_prompt_loader import PromptManager

app = FastAPI()

# CORS設定（本番では限定してOK）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app_prompt_loader import PromptManager

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
try:
    from openai import OpenAI  # openai>=1.x
except Exception:
    OpenAI = None  # type: ignore

# --- 環境変数 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # 必ず Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")
MODEL_MODE = os.getenv("USE_MODEL", "low")  # low | high

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Whisper に送る最大サイズ（約25 MiB）
MAX_WHISPER_BYTES = 25 * 1024 * 1024
# テキスト分割
MAX_CHARS_PER_CHUNK = 4000
CHUNK_OVERLAP = 400

# ログ
logger = logging.getLogger("app")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()

# CORS（ローカル開発用）。本番では許可ドメインを絞る
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_openai_client() -> Optional["OpenAI"]:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)

# --- Content-Type 判定 ---
EXTENSION_CT_MAP = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
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
    new_query = urlencode(q)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": MODEL_MODE}

# --- Storage: アップロード/一覧/署名URL/削除 ---
@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"
        path = f"{staff}/{unique_filename}"

        content = await file.read()
        content_type = guess_content_type(file.filename, fallback=(file.content_type or None))

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
    try:
        path = f"{staff}/{filename}"
        supabase.storage.from_(SUPABASE_BUCKET).remove([path])
        # assessments を運用している場合の削除は必要に応じて追加
        return {"message": "deleted", "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete error: {e}")

def download_file_bytes(staff: str, filename: str) -> bytes:
    path = f"{staff}/{filename}"
    return supabase.storage.from_(SUPABASE_BUCKET).download(path)

# --- Whisper: 25MB超は ffmpeg で音声抽出・圧縮 ---
def transcode_for_whisper(file_bytes: bytes, filename: str) -> Tuple[bytes, str]:
    if len(file_bytes) <= MAX_WHISPER_BYTES:
        return file_bytes, filename
    if shutil.which("ffmpeg") is None:
        raise HTTPException(
            413,
            "ファイルが25MBを超えています。ffmpegが見つからないため自動圧縮できません。",
        )
    bitrates = ["64k", "48k", "32k"]
    base, _ = os.path.splitext(os.path.basename(filename))
    with tempfile.TemporaryDirectory() as d:
        in_path = os.path.join(d, f"{base}_in")
        out_path = os.path.join(d, f"{base}_out.m4a")
        with open(in_path, "wb") as f:
            f.write(file_bytes)
        for br in bitrates:
            cmd = ["ffmpeg", "-y", "-i", in_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", br, out_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                continue
            try:
                data = open(out_path, "rb").read()
                if len(data) <= MAX_WHISPER_BYTES:
                    return data, f"{base}.m4a"
            except Exception:
                continue
    raise HTTPException(413, "自動圧縮でも25MB以下にできませんでした。")

def get_openai_transcript(file_bytes: bytes, filename: str) -> str:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY 未設定または openai ライブラリがありません。")
    send_bytes, send_name = transcode_for_whisper(file_bytes, filename)
    bio = io.BytesIO(send_bytes); bio.name = send_name
    try:
        tr = client.audio.transcriptions.create(model="whisper-1", file=bio, response_format="text")
        if isinstance(tr, str):
            return tr
        text = getattr(tr, "text", None)
        if text:
            return text
        raise HTTPException(500, "Whisper transcription response could not be parsed.")
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")

# --- プロンプト外部ファイル ---
prompt_manager = PromptManager()

def _chat_json(client, model: str, system_prompt: str, user_content: str) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = getattr(resp.choices[0].message, "content", "") or ""
        if not content.strip():
            finish_reason = getattr(resp.choices[0], "finish_reason", None)
            raise HTTPException(500, f"Model returned empty content (finish_reason={finish_reason}).")
        return json.loads(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"OpenAI analyze failed: {e}")

def analyze_with_openai(transcript: str, model: str) -> Dict[str, Any]:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY 未設定または openai ライブラリがありません。")
    system_prompt = prompt_manager.get_analyze_prompt()
    return _chat_json(client, model, system_prompt, transcript)

def _chunk_text(text: str, size: int = MAX_CHARS_PER_CHUNK, overlap: int = CHUNK_OVERLAP) -> List[str]:
    chunks: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(i + size, n)
        chunks.append(text[i:j])
        if j >= n:
            break
        i = max(0, j - overlap)
    return chunks

def _merge_analyses(analyses: List[Dict[str, Any]], model: str) -> Dict[str, Any]:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY 未設定または openai ライブラリがありません。")
    system_prompt = prompt_manager.get_merge_prompt()
    user_content = "以下の部分分析を統合してください。\n" + json.dumps(analyses, ensure_ascii=False)
    return _chat_json(client, model, system_prompt, user_content)

def analyze_with_chunking(transcript: str, model: str) -> Dict[str, Any]:
    chunks = _chunk_text(transcript)
    partials: List[Dict[str, Any]] = []
    for ch in chunks:
        partials.append(analyze_with_openai(ch, model=model))
    return _merge_analyses(partials, model=model)

def analyze(transcript: str) -> Tuple[str, Dict[str, Any]]:
    mode = MODEL_MODE.lower()
    if mode == "low":
        model = "gpt-4o-mini"
    elif mode == "high":
        model = "gpt-4o"
    else:
        raise HTTPException(500, "Invalid USE_MODEL (low/high のみ対応)")
    if len(transcript) > MAX_CHARS_PER_CHUNK * 2:
        analysis = analyze_with_chunking(transcript, model=model)
    else:
        analysis = analyze_with_openai(transcript, model=model)
    return model, analysis

# --- assessments 保存/取得（テーブルがなくても落ちない） ---
def upsert_assessment(staff: str, filename: str, transcript: str, model_mode: str, model_name: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
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
    return record | {"created_at": now}

def get_assessment(staff: str, filename: str) -> Optional[Dict[str, Any]]:
    try:
        q = supabase.table("assessments").select("*").eq("staff", staff).eq("filename", filename).limit(1).execute()
        rows = getattr(q, "data", None) or []
        if not rows:
            return None
        return rows[0]
    except Exception as e:
        logger.warning("assessments select failed: %s", e)
        return None

@app.get("/analysis/{staff}/{filename}")
def fetch_analysis(staff: str, filename: str):
    found = get_assessment(staff, filename)
    if not found:
        raise HTTPException(404, "No analysis found for this file.")
    return found

@app.get("/results/{staff}")
def list_results(staff: str):
    try:
        res = supabase.table("assessments").select("staff,filename,model_mode,model_name,created_at,analysis").eq("staff", staff).order("created_at", desc=True).execute()
        return {"results": getattr(res, "data", [])}
    except Exception as e:
        logger.warning("assessments list failed: %s", e)
        return {"results": []}

@app.post("/analyze/{staff}/{filename}")
def run_analysis(staff: str, filename: str, force: bool = False):
    logger.info("analyze.start staff=%s file=%s force=%s", staff, filename, force)
    if not force:
        existing = get_assessment(staff, filename)
        if existing:
            return existing
    file_bytes = download_file_bytes(staff, filename)
    transcript = get_openai_transcript(file_bytes, filename=filename)
    model_name, analysis_json = analyze(transcript)
    saved = upsert_assessment(
        staff=staff,
        filename=filename,
        transcript=transcript,
        model_mode=MODEL_MODE,
        model_name=model_name,
        analysis=analysis_json,
    )
    logger.info("analyze.done staff=%s file=%s chars=%s model=%s", staff, filename, len(transcript), model_name)
    return saved
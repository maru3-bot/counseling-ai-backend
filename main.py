import io
import json
import os
import mimetypes
import tempfile
import subprocess
import shutil
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict
from supabase import create_client
from supabase.client import Client

# OpenAI（ChatGPT API）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

try:
    from openai import OpenAI  # openai>=1.x
except Exception:
    OpenAI = None  # type: ignore

# --- 環境変数から取得 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を環境変数に設定してください。")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# モデル切替（OpenAIのみ）
MODEL_MODE = os.getenv("USE_MODEL", "low")  # low/high
MAX_WHISPER_BYTES = 25 * 1024 * 1024  # 25 MiB 目安

app = FastAPI()

# CORS設定（検証しやすいように * 許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return PlainTextResponse("", status_code=204)

class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # 「model_」警告抑制
    staff: str
    filename: str
    transcript: str
    model_mode: str
    model_name: str
    analysis: Dict[str, Any]
    created_at: str

def get_openai_client() -> Optional["OpenAI"]:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)

@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": MODEL_MODE}

# --- Content-Type 判定の補助 ---
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

def guess_content_type(filename: str, fallback: str | None = None) -> str:
    ct, _ = mimetypes.guess_type(filename)
    if not ct or ct.startswith("text/"):
        ext = os.path.splitext(filename)[1].lower()
        return EXTENSION_CT_MAP.get(ext, fallback or "application/octet-stream")
    return ct

def strip_download_param(signed_url: str) -> str:
    p = urlparse(signed_url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() != "download"]
    new_query = urlencode(q)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
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

        return {
            "message": "アップロード成功",
            "filename": unique_filename,
            "path": path,
            "content_type": content_type,
        }
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
        clean = strip_download_param(url)
        return {"url": clean}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"signed-url error: {e}")

def download_file_bytes(staff: str, filename: str) -> bytes:
    path = f"{staff}/{filename}"
    data = supabase.storage.from_(SUPABASE_BUCKET).download(path)
    return data

# --- Whisper用: 必要に応じて ffmpeg で音声抽出・圧縮 ---
def transcode_for_whisper(file_bytes: bytes, filename: str) -> Tuple[bytes, str]:
    if len(file_bytes) <= MAX_WHISPER_BYTES:
        return file_bytes, filename  # そのまま送れる

    if shutil.which("ffmpeg") is None:
        raise HTTPException(
            413,
            "ファイルが25MBを超えています。ffmpegが見つからないため自動圧縮できません。"
            "短いファイルにするか、音声だけを低ビットレートで再エンコードしてから再試行してください。"
        )

    # 64k → 48k → 32k の順で圧縮を試す
    bitrates = ["64k", "48k", "32k"]
    base, _ = os.path.splitext(os.path.basename(filename))

    with tempfile.TemporaryDirectory() as d:
        in_path = os.path.join(d, f"{base}_in")
        out_path = os.path.join(d, f"{base}_out.m4a")

        # 入力を書き出し
        with open(in_path, "wb") as f:
            f.write(file_bytes)

        for br in bitrates:
            # 音声のみ抽出（モノラル16kHz、AAC、指定ビットレート）
            cmd = [
                "ffmpeg", "-y",
                "-i", in_path,
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "aac",
                "-b:a", br,
                out_path,
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                # 次のビットレートで再トライ
                continue
            try:
                data = open(out_path, "rb").read()
                if len(data) <= MAX_WHISPER_BYTES:
                    return data, f"{base}.m4a"
            except Exception:
                continue

    # ここまでで25MB以下にできなかった
    raise HTTPException(
        413,
        "ファイルが25MBを超えており、自動圧縮でも上限を下回れませんでした。"
        "短いクリップに分割するか、より低ビットレートで再エンコードしてから再試行してください。"
    )

def transcribe_with_whisper(file_bytes: bytes, filename: str) -> str:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")

    # 25MB超なら自動で音声抽出・圧縮
    send_bytes, send_name = transcode_for_whisper(file_bytes, filename)

    bio = io.BytesIO(send_bytes)
    bio.name = send_name  # 拡張子でフォーマット推定させる

    try:
        tr = client.audio.transcriptions.create(
            model="whisper-1",
            file=bio,
            response_format="text",
        )
        if isinstance(tr, str):
            return tr
        text = getattr(tr, "text", None)
        if text:
            return text
        raise HTTPException(500, "Whisper transcription response could not be parsed.")
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")

ANALYZE_SYSTEM_PROMPT = """あなたはたくさんの顧客を抱える日本人美容師です。
（中略：プロンプトは現状のまま）
"""

def safe_json_extract(text: str) -> Dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t.replace("json", "", 1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return json.loads(t)

# 既存の analyze_with_openai と safe_json_extract を次で置き換え

def analyze_with_openai(transcript: str, model: str) -> Dict[str, Any]:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        return safe_json_extract(content)
        response_format={"type": "json_object"},  # JSONモードで厳格に
        
        # 応答本文を取得
        content = getattr(resp.choices[0].message, "content", "") or ""
        if not content.strip():
            finish_reason = getattr(resp.choices[0], "finish_reason", None)
            raise HTTPException(
                500,
                f"Model returned empty content (finish_reason={finish_reason}). "
                "入力（文字起こし）が長すぎる可能性があります。短いクリップで再試行するか、後述の分割要約をご検討ください。"
            )
        # JSONモードなのでそのままJSONパース可能
        return json.loads(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"OpenAI analyze failed: {e}")

def analyze(transcript: str) -> tuple[str, Dict[str, Any]]:
    mode = MODEL_MODE.lower()
    if mode == "low":
        return "gpt-4o-mini", analyze_with_openai(transcript, model="gpt-4o-mini")
    elif mode == "high":
        return "gpt-4o", analyze_with_openai(transcript, model="gpt-4o")
    else:
        raise HTTPException(500, "Invalid USE_MODEL (low/high のみ対応)")

def upsert_assessment(
    staff: str,
    filename: str,
    transcript: str,
    model_mode: str,
    model_name: str,
    analysis: Dict[str, Any],
) -> AnalyzeResponse:
    now = datetime.utcnow().isoformat()
    data = {
        "staff": staff,
        "filename": filename,
        "transcript": transcript,
        "model_mode": model_mode,
        "model_name": model_name,
        "analysis": analysis,
        "created_at": now,
    }
    supabase.table("assessments").upsert(
        data, on_conflict="staff,filename"
    ).execute()
    return AnalyzeResponse(
        staff=staff,
        filename=filename,
        transcript=transcript,
        model_mode=model_mode,
        model_name=model_name,
        analysis=analysis,
        created_at=now,
    )

def get_assessment(staff: str, filename: str) -> Optional[AnalyzeResponse]:
    q = (
        supabase.table("assessments")
        .select("*")
        .eq("staff", staff)
        .eq("filename", filename)
        .limit(1)
        .execute()
    )
    rows = getattr(q, "data", None) or []
    if not rows:
        return None
    row = rows[0]
    return AnalyzeResponse(
        staff=row["staff"],
        filename=row["filename"],
        transcript=row.get("transcript", ""),
        model_mode=row.get("model_mode", ""),
        model_name=row.get("model_name", ""),
        analysis=row.get("analysis", ""),
        created_at=row.get("created_at", ""),
    )

@app.get("/analysis/{staff}/{filename}", response_model=AnalyzeResponse)
def fetch_analysis(staff: str, filename: str):
    found = get_assessment(staff, filename)
    if not found:
        raise HTTPException(404, "No analysis found for this file.")
    return found

@app.get("/results/{staff}")
def list_results(staff: str):
    res = (
        supabase.table("assessments")
        .select("staff,filename,model_mode,model_name,created_at,analysis")
        .eq("staff", staff)
        .order("created_at", desc=True)
        .execute()
    )
    return {"results": getattr(res, "data", [])}

@app.post("/analyze/{staff}/{filename}", response_model=AnalyzeResponse)
def run_analysis(staff: str, filename: str, force: bool = False):
    if not force:
        existing = get_assessment(staff, filename)
        if existing:
            return existing

    file_bytes = download_file_bytes(staff, filename)
    transcript = transcribe_with_whisper(file_bytes, filename=filename)
    model_name, analysis_json = analyze(transcript)
    saved = upsert_assessment(
        staff=staff,
        filename=filename,
        transcript=transcript,
        model_mode=MODEL_MODE,
        model_name=model_name,
        analysis=analysis_json,
    )
    return saved
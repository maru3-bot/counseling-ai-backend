import io
import json
import os
import mimetypes
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from datetime import datetime
from typing import Any, Dict, Optional

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
        # text/plain などは動画/音声の可能性が高いので拡張子で補正
        ext = os.path.splitext(filename)[1].lower()
        return EXTENSION_CT_MAP.get(ext, fallback or "application/octet-stream")
    return ct

def strip_download_param(signed_url: str) -> str:
    """Supabaseの署名URLに付く ?download=xxx を除去して inline 再生を促す"""
    p = urlparse(signed_url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() != "download"]
    new_query = urlencode(q)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    """
    指定スタッフのフォルダに動画をアップロード
    ファイル名は `YYYYMMDD-HHMMSS_元ファイル名`
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"
        path = f"{staff}/{unique_filename}"

        content = await file.read()
        content_type = guess_content_type(file.filename, fallback=(file.content_type or None))

        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path,
            content,
            file_options={"contentType": content_type, "upsert": "true"},
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
    """
    動画再生用の署名付きURLを発行（downloadパラメータを除去して返す）
    """
    try:
        path = f"{staff}/{filename}"
        res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires_sec)
        url = res.get("signedURL") or res.get("signed_url")
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

# --- 既存ファイルの Content-Type を修復（同じパスに上書き） ---
@app.post("/admin/fix-content-type/{staff}/{filename}")
def fix_content_type(staff: str, filename: str, content_type: Optional[str] = None):
    """
    既存のオブジェクトを同一パスで再アップロードし、Content-Type を付与/修正します。
    content_type を省略すると拡張子から推測します。
    """
    try:
        path = f"{staff}/{filename}"
        # 存在確認（無ければ 404）
        listing = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        names = {item.get("name") for item in listing or []}
        if filename not in names:
            raise HTTPException(404, f"File not found: {path}")

        data = supabase.storage.from_(SUPABASE_BUCKET).download(path)
        if not isinstance(data, (bytes, bytearray)):
            raise HTTPException(500, f"download returned non-bytes type: {type(data)}")

        ct = content_type or guess_content_type(filename)
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path,
            data,
            file_options={"contentType": ct, "upsert": "true"},
        )
        return {"message": "fixed", "path": path, "content_type": ct}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fix-content-type error: {e}")

def transcribe_with_whisper(file_bytes: bytes, filename: str) -> str:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")

    bio = io.BytesIO(file_bytes)
    bio.name = filename
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
カウンセリング力に定評があり、顧客からの信頼も厚く、全国各地でセミナーを開催しています。
具体例を用いた分析は非常にわかりやすく、多くの受講者を抱えています。
その観点からカウンセリング中の対話の文字起こしを読み、以下の観点で日本語で評価してください。

- 要約（200〜400字程度）
- 強み（箇条書き3〜5個）
- 改善提案（箇条書き3〜5個、実践的に）
- リスク・注意点（箇条書き、該当があれば）
- スコア（1〜5、整数）:
  - empathy（共感）
  - active_listening（傾聴）
  - clarity（明確さ）
  - problem_solving（問題解決）
- 全体講評（200〜300字）

必ず次のJSONだけを返してください（前後の文章やコードブロックは不要）:
{
  "summary": "...",
  "strengths": ["...", "..."],
  "improvements": ["...", "..."],
  "risk_flags": ["..."],
  "scores": {
    "empathy": 3,
    "active_listening": 3,
    "clarity": 3,
    "problem_solving": 3
  },
  "overall_comment": "..."
}
"""

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
    except Exception as e:
        raise HTTPException(500, f"OpenAI analyze failed: {e}")

def safe_json_extract(text: str) -> Dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t.replace("json", "", 1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    try:
        return json.loads(t)
    except Exception as e:
        raise HTTPException(500, f"Failed to parse JSON from model output: {e}. Raw: {text[:500]}")

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
        model_mode=MODEL_MODE,
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
        analysis=row.get("analysis", {}),
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
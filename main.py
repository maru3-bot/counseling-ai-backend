import base64
import io
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, List
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict
from supabase import create_client
from supabase.client import Client

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
MODEL_MODE = os.getenv("USE_MODEL", "low")  # low / high

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を .env に設定してください。")

# Supabase クライアント
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Whisper に送る最大サイズ（約25MiB）
MAX_WHISPER_BYTES = 25 * 1024 * 1024
# チャンク分割用（長文のとき）
MAX_CHARS_PER_CHUNK = 4000
CHUNK_OVERLAP = 400

app = FastAPI()

# CORS（検証用に * 許可。必要に応じて絞る）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 例: ["http://localhost:5173", "https://your-frontend.example.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルート → /docs に誘導
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

# favicon 404 抑止
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return PlainTextResponse("", status_code=204)

# 健康チェック
@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": MODEL_MODE}

# Pydantic モデル（警告抑止）
class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
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
    if not ct or (ct.startswith("text/")):
        ext = os.path.splitext(filename)[1].lower()
        return EXTENSION_CT_MAP.get(ext, fallback or "application/octet-stream")
    return ct

def strip_download_param(signed_url: str) -> str:
    """Supabase 署名URLに付く ?download=... を除去して inline 再生しやすくする"""
    p = urlparse(signed_url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() != "download"]
    new_query = urlencode(q)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

# --- Storage: アップロード/一覧/署名URL ---
@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    """指定スタッフのフォルダに動画/音声をアップロード。ファイル名はタイムスタンプ付きで一意化。"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"
        path = f"{staff}/{unique_filename}"
        content = await file.read()
        content_type = guess_content_type(file.filename, fallback=(file.content_type or None))

        # Supabase Python SDK v2: file_options のキーはハイフン形式、値は文字列
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
    """スタッフ別フォルダのファイル一覧"""
    try:
        items = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        return {"files": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signed-url/{staff}/{filename}")
def get_signed_url(staff: str, filename: str, expires_sec: int = 3600):
    """動画/音声の署名付きURL（downloadパラメータ除去済み）"""
    try:
        path = f"{staff}/{filename}"
        res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires_sec)
        url = None
        if isinstance(res, dict):
            url = (
                res.get("signedURL")
                or res.get("signed_url")
                or (res.get("data") or {}).get("signedURL")
                or (res.get("data") or {}).get("signed_url")
            )
        if not url:
            url = (
                getattr(res, "signedURL", None)
                or getattr(res, "signed_url", None)
                or getattr(getattr(res, "data", None), "signedURL", None)
                or getattr(getattr(res, "data", None), "signed_url", None)
            )
        if not url:
            raise HTTPException(404, f"Signed URL not returned for path: {path}")
        return {"url": strip_download_param(url)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"signed-url error: {e}")

def download_file_bytes(staff: str, filename: str) -> bytes:
    """Storage から同名ファイルをダウンロード（bytes）"""
    path = f"{staff}/{filename}"
    data = supabase.storage.from_(SUPABASE_BUCKET).download(path)
    return data

# --- 既存ファイルの Content-Type 修復（Service Role 必須） ---
@app.post("/admin/fix-content-type/{staff}/{filename}")
def fix_content_type(staff: str, filename: str, content_type: Optional[str] = None):
    """
    既存のオブジェクトを同一パスで「上書き」して、Content-Type を付与/修正します。
    注意: RLS の影響を受けないよう、必ず Service Role Key で接続してください。
    """
    try:
        path = f"{staff}/{filename}"
        listing = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        names = {item.get("name") for item in (listing or [])}
        if filename not in names:
            raise HTTPException(404, f"File not found: {path}")

        data = supabase.storage.from_(SUPABASE_BUCKET).download(path)
        if not isinstance(data, (bytes, bytearray)):
            raise HTTPException(500, f"download returned non-bytes type: {type(data)}")
        ct = content_type or guess_content_type(filename)

        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path,
            data,
            file_options={"content-type": ct, "x-upsert": "true"},
        )
        return {"message": "fixed", "path": path, "content_type": ct}
    except HTTPException:
        raise
    except Exception as e:
        # 例: {'statusCode': 400, 'error': 'Unauthorized', 'message': 'new row violates row-level security policy'}
        raise HTTPException(status_code=500, detail=f"fix-content-type error: {e}")

# 管理用: 接続しているキーの role を確認（開発用途。必要なければ削除）
@app.get("/admin/check-role", include_in_schema=False)
def admin_check_role():
    try:
        t = SUPABASE_KEY or ""
        payload_b64 = t.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return {"role": payload.get("role"), "iss": payload.get("iss")}
    except Exception as e:
        return {"error": str(e)}

# --- Whisper 送信用の自動圧縮（25MB超のとき） ---
def transcode_for_whisper(file_bytes: bytes, filename: str) -> Tuple[bytes, str]:
    """25MB超なら ffmpeg で音声のみ抽出・圧縮してから Whisper に送る"""
    if len(file_bytes) <= MAX_WHISPER_BYTES:
        return file_bytes, filename

    if shutil.which("ffmpeg") is None:
        raise HTTPException(
            413,
            "ファイルが25MBを超えています。ffmpeg が見つからないため自動圧縮できません。"
            "短いクリップで試すか、音声のみを低ビットレートで再エンコードしてから再試行してください。",
        )

    bitrates = ["64k", "48k", "32k"]
    base, _ = os.path.splitext(os.path.basename(filename))

    with tempfile.TemporaryDirectory() as d:
        in_path = os.path.join(d, f"{base}_in")
        out_path = os.path.join(d, f"{base}_out.m4a")
        with open(in_path, "wb") as f:
            f.write(file_bytes)

        for br in bitrates:
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
                continue
            try:
                data = open(out_path, "rb").read()
                if len(data) <= MAX_WHISPER_BYTES:
                    return data, f"{base}.m4a"
            except Exception:
                continue

    raise HTTPException(
        413,
        "ファイルが25MBを超えており、自動圧縮でも上限を下回れませんでした。"
        "短いクリップに分割するか、さらに低ビットレートで再エンコードして再試行してください。",
    )

def transcribe_with_whisper(file_bytes: bytes, filename: str) -> str:
    """OpenAI Whisper API で文字起こし"""
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")

    send_bytes, send_name = transcode_for_whisper(file_bytes, filename)
    bio = io.BytesIO(send_bytes)
    bio.name = send_name  # 拡張子からフォーマット推定

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")

# --- 要約・採点（Chat Completions を JSONモードで実行） ---
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

def _chat_json(client, model: str, system_prompt: str, user_content: str) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},  # JSONモード
        )
        content = getattr(resp.choices[0].message, "content", "") or ""
        if not content.strip():
            finish_reason = getattr(resp.choices[0], "finish_reason", None)
            raise HTTPException(
                500,
                f"Model returned empty content (finish_reason={finish_reason}). "
                "入力が長すぎる可能性があります。短いクリップで再試行するか、分割要約をご利用ください。",
            )
        return json.loads(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"OpenAI analyze failed: {e}")

def analyze_with_openai(transcript: str, model: str) -> Dict[str, Any]:
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")
    return _chat_json(client, model, ANALYZE_SYSTEM_PROMPT, transcript)

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
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")

    system_prompt = (
        "あなたは複数の部分分析結果(JSON)を統合して、指定の最終フォーマットにまとめる役割です。"
        "重複は整理し、矛盾は整合的に統合してください。必ず最終の単一JSONだけを返してください。"
        "最終フォーマットは次です："
        "{"
        "\"summary\":\"...\","
        "\"strengths\":[\"...\"],"
        "\"improvements\":[\"...\"],"
        "\"risk_flags\":[\"...\"],"
        "\"scores\":{\"empathy\":1,\"active_listening\":1,\"clarity\":1,\"problem_solving\":1},"
        "\"overall_comment\":\"...\""
        "}"
    )
    user_content = "以下の部分分析を統合してください。\n" + json.dumps(analyses, ensure_ascii=False)
    return _chat_json(client, model, system_prompt, user_content)

def analyze_with_chunking(transcript: str, model: str) -> Dict[str, Any]:
    chunks = _chunk_text(transcript)
    partials: List[Dict[str, Any]] = []
    for ch in chunks:
        part = analyze_with_openai(ch, model=model)
        partials.append(part)
    return _merge_analyses(partials, model=model)

def analyze(transcript: str) -> Tuple[str, Dict[str, Any]]:
    """モデル選択と長文フォールバック（分割→統合）"""
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

# --- 結果の保存/取得 ---
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
        staff=row.get("staff", ""),
        filename=row.get("filename", ""),
        transcript=row.get("transcript", ""),
        model_mode=row.get("model_mode", ""),
        model_name=row.get("model_name", ""),
        analysis=row.get("analysis", {}) or {},
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
    """
    文字起こし→要約・採点を実行。
    既存結果があれば再利用。force=true で再実行。
    """
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
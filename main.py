import io
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict  # ← ConfigDict を追加
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

# CORS設定（検証しやすいように * 許可。必要に応じて絞ってください）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 例: ["http://localhost:5173", "https://your-frontend.example.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeResponse(BaseModel):
    # 「model_」で始まるフィールド名を許可（警告を抑制）
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


@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": MODEL_MODE}


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
        supabase.storage.from_(SUPABASE_BUCKET).upload(path, content)

        return {
            "message": "アップロード成功",
            "filename": unique_filename,
            "path": path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list/{staff}")
def list_files(staff: str):
    """
    スタッフ別のファイル一覧を取得
    """
    try:
        items = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        return {"files": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signed-url/{staff}/{filename}")
def get_signed_url(staff: str, filename: str, expires_sec: int = 3600):
    """
    動画再生用の署名付きURLを発行
    """
    try:
        path = f"{staff}/{filename}"
        res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires_sec)
        return {"url": res.get("signedURL") or res.get("signed_url")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def download_file_bytes(staff: str, filename: str) -> bytes:
    path = f"{staff}/{filename}"
    data = supabase.storage.from_(SUPABASE_BUCKET).download(path)
    return data


def transcribe_with_whisper(file_bytes: bytes, filename: str) -> str:
    """
    OpenAI Whisper APIで文字起こし
    """
    client = get_openai_client()
    if client is None:
        raise HTTPException(500, "OPENAI_API_KEY が未設定か openai ライブラリがありません。")

    bio = io.BytesIO(file_bytes)
    bio.name = filename  # 一部クライアントは拡張子に依存するため
    try:
        tr = client.audio.transcriptions.create(
            model="whisper-1",
            file=bio,
            # language="ja",  # 日本語メインの場合は明示も可（自動検出でもOK）
            response_format="text",
        )
        # response_format="text" の場合は str を返すことがある
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
    """
    LLMがコードフェンスや余分なテキストを返してもJSON部分を抽出してパース。
    """
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
    """
    モデルモードに応じて分析を実行。戻り値: (model_name, analysis_json)
    """
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
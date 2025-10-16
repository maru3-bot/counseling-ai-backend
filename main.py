import os
import json
import tempfile
import subprocess
import shutil
import math
import asyncio
import requests
import time
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from app_prompt_loader import PromptManager
from datetime import datetime
from pydantic import BaseModel

# ===== ロギング設定（方法1） =====
# ログディレクトリ作成
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("counseling-ai-backend")
logger.setLevel(logging.DEBUG)

# フォーマッタ
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

# コンソール出力
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# ローテーションするファイル出力（最大5MB×3世代）
file_handler = RotatingFileHandler(
    "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# ハンドラ重複防止
if not logger.handlers:
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

# ===== 環境変数 =====
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# フロントエンドのURL（クラウド環境で設定）
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://counseling-ai-frontend.onrender.com")
# デバッグモード
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# プロンプトパスの設定
ANALYZE_PROMPT_PATH = os.getenv("ANALYZE_PROMPT_PATH", "prompts/analyze_system_prompt.md")
MERGE_PROMPT_PATH = os.getenv("MERGE_PROMPT_PATH", "prompts/merge_system_prompt.md")
COMPANY_VALUES_PATH = os.getenv("COMPANY_VALUES_PATH", "prompts/company_values.md")
EDUCATION_PLAN_PATH = os.getenv("EDUCATION_PLAN_PATH", "prompts/education_plan.md")

# プロンプトマネージャーを初期化
prompt_manager = PromptManager(
    analyze_prompt_path=ANALYZE_PROMPT_PATH,
    merge_prompt_path=MERGE_PROMPT_PATH,
    company_values_path=COMPANY_VALUES_PATH,
    education_plan_path=EDUCATION_PLAN_PATH
)

# 処理中のタスク状態を保持
processing_tasks = {}

class TaskStatus(BaseModel):
    staff_id: str
    filename: str
    status: str
    progress: float
    message: str
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None

# ===== Supabase 接続 =====
supabase = None
supabase_error = None

try:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("Supabase URL または SERVICE_ROLE_KEY が設定されていません")
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    logger.info("Supabase接続成功")
except Exception as e:
    supabase_error = str(e)
    logger.exception(f"Supabase接続エラー: {e}")

# ===== FastAPI アプリ設定 =====
app = FastAPI()

# HTTPアクセスログ（メソッド/パス/ステータス/所要時間）
@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    start = time.time()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = (time.time() - start) * 1000
        status = response.status_code if response else 500
        logger.info(f"{request.method} {request.url.path} -> {status} ({duration_ms:.1f} ms)")

# CORSの設定
allowed_origins = [FRONTEND_URL]
if DEBUG:
    allowed_origins.append("*")  # デバッグ時は全て許可
    logger.debug("デバッグモード: CORS制限なし")
else:
    logger.info(f"本番モード: CORS許可オリジン = {allowed_origins}")

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
        logger.debug(f"フォルダパス: {folder_path} のファイル一覧取得")
        res = supabase.storage.from_(SUPABASE_BUCKET).list(folder_path)
        return res
    except Exception as e:
        logger.exception("ファイル一覧取得エラー")
        raise HTTPException(status_code=500, detail=f"ファイル一覧取得エラー: {str(e)}")

# ===== ファイルアップロード =====
@app.post("/upload/{staff_id}")
async def upload_file(staff_id: str, file: UploadFile = File(...)):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    try:
        contents = await file.read()
        filename = file.filename
        content_type = file.content_type or "application/octet-stream"
        if filename.lower().endswith(('.mp4', '.mov', '.avi', '.wmv', '.mkv')):
            if 'video/' not in content_type:
                content_type = "video/mp4" if filename.lower().endswith('.mp4') else "video/quicktime"
        file_path = f"{staff_id}/{filename}"
        logger.info(f"アップロード: {file_path}, サイズ: {len(contents)} bytes, タイプ: {content_type}")
        file_options = {
            "content-type": content_type,
            "cache-control": "3600"
        }
        try:
            supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
        except Exception:
            pass
        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, contents, file_options)
        return {"ok": True, "path": file_path, "type": content_type}
    except Exception as e:
        logger.exception("アップロードエラー")
        raise HTTPException(status_code=500, detail=f"アップロードエラー: {str(e)}")

# ===== 署名付きURLの取得 =====
@app.get("/signed-url/{staff_id}/{filename}")
def get_signed_url(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    try:
        file_path = f"{staff_id}/{filename}"
        try:
            _ = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file_path)
        except Exception as e:
            logger.error(f"ファイル情報取得エラー: {e}")
            raise HTTPException(status_code=404, detail=f"ファイル {filename} が見つかりません")
        try:
            transform = {"format": "mp4"}
            signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
                file_path, 3600, transform=transform
            )
        except Exception:
            signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
                file_path, 3600
            )
        return {"url": signed_url["signedURL"]}
    except Exception as e:
        logger.exception("署名付きURL取得エラー")
        raise HTTPException(status_code=500, detail=f"署名付きURL取得エラー: {str(e)}")

# ===== ファイル削除 =====
@app.delete("/delete/{staff_id}/{filename}")
def delete_file(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    try:
        file_path = f"{staff_id}/{filename}"
        supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
        try:
            supabase.table("assessments").delete().eq("staff", staff_id).eq("filename", filename).execute()
        except Exception:
            pass
        task_key = f"{staff_id}:{filename}"
        if task_key in processing_tasks:
            del processing_tasks[task_key]
        return {"ok": True, "message": f"{filename} を削除しました"}
    except Exception as e:
        logger.exception("削除エラー")
        raise HTTPException(status_code=500, detail=f"削除エラー: {str(e)}")

# ===== タスク状態の取得 =====
@app.get("/task-status/{staff_id}/{filename}")
def get_task_status(staff_id: str, filename: str):
    task_key = f"{staff_id}:{filename}"
    if task_key in processing_tasks:
        return processing_tasks[task_key]
    else:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")

# ===== 音声を複数のチャンクに分割する関数 =====
def split_audio(input_path: str, chunk_dir: str, max_size_mb: int = 24) -> List[str]:
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        output_path = os.path.join(chunk_dir, "chunk_0.mp3")
        shutil.copy(input_path, output_path)
        return [output_path]
    command = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{input_path}"'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"動画長さの取得に失敗しました: {result.stderr}")
    total_duration = float(result.stdout.strip())
    chunks_count = math.ceil(file_size_mb / max_size_mb)
    chunk_duration = total_duration / chunks_count
    chunk_paths = []
    for i in range(chunks_count):
        start_time = i * chunk_duration
        output_path = os.path.join(chunk_dir, f"chunk_{i}.mp3")
        command = f'ffmpeg -y -i "{input_path}" -ss {start_time} -t {chunk_duration} -c:a libmp3lame -q:a 2 "{output_path}"'
        result = subprocess.run(command, shell=True, capture_output=True)
        if result.returncode != 0:
            raise Exception(f"音声チャンク{i}の作成に失敗しました")
        chunk_paths.append(output_path)
    return chunk_paths

# ===== 複数のチャンクを文字起こし =====
async def transcribe_chunks(chunk_paths: List[str], openai_client, update_progress) -> str:
    total_chunks = len(chunk_paths)
    transcripts = []
    for i, chunk_path in enumerate(chunk_paths):
        update_progress(f"チャンク {i+1}/{total_chunks} を文字起こし中...", (i / total_chunks) * 0.5)
        with open(chunk_path, "rb") as audio_file:
            response = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja",
                response_format="text"
            )
        transcripts.append(response)
    return " ".join(transcripts)

# ===== 大きなテキストを分割 =====
def split_text(text: str, max_tokens: int = 4000) -> List[str]:
    chars_per_token = 2.5
    max_chars = int(max_tokens * chars_per_token)
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

# ===== テキストチャンクを分析 =====
async def analyze_text_chunks(text_chunks: List[str], system_prompt: str, openai_client, update_progress) -> List[Dict]:
    total_chunks = len(text_chunks)
    results = []
    for i, chunk in enumerate(text_chunks):
        update_progress(f"テキストチャンク {i+1}/{total_chunks} を分析中...", 0.5 + (i / total_chunks) * 0.4)
        completion = openai_client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chunk}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        analysis_text = completion.choices[0].message.content
        analysis = json.loads(analysis_text)
        results.append(analysis)
    return results

# ===== 複数の分析結果をマージ =====
async def merge_analyses(analyses: List[Dict], merge_prompt: str, openai_client, update_progress) -> Dict:
    if len(analyses) == 1:
        return analyses[0]
    update_progress("複数の分析結果をマージ中...", 0.9)
    analyses_json = json.dumps(analyses, ensure_ascii=False)
    completion = openai_client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": merge_prompt},
            {"role": "user", "content": analyses_json}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )
    merged_text = completion.choices[0].message.content
    merged_analysis = json.loads(merged_text)
    return merged_analysis

# ===== 非同期で動画を分析 =====
async def analyze_video_task(staff_id: str, filename: str):
    task_key = f"{staff_id}:{filename}"
    def update_progress(message, progress):
        if task_key in processing_tasks:
            processing_tasks[task_key].message = message
            processing_tasks[task_key].progress = progress
            logger.info(f"進捗更新: {message} ({progress*100:.1f}%)")
    try:
        import openai
        file_path = f"{staff_id}/{filename}"
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        update_progress("動画のダウンロードを開始します...", 0.01)
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(file_path, 3600)
        video_url = signed_url["signedURL"]
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as video_file:
            video_path = video_file.name
            response = requests.get(video_url, stream=True)
            if response.status_code != 200:
                raise Exception("動画のダウンロードに失敗しました")
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_file.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        update_progress(
                            f"動画をダウンロード中... {downloaded/(1024*1024):.1f}MB/{total_size/(1024*1024):.1f}MB",
                            0.01 + (downloaded/total_size) * 0.09
                        )
        update_progress("音声抽出を開始します...", 0.1)
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio.mp3")
            command = f'ffmpeg -i "{video_path}" -q:a 3 -map a "{audio_path}" -y'
            process = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if process.returncode != 0:
                stderr = process.stderr.decode()
                raise Exception(f"音声の抽出に失敗しました: {stderr}")
            update_progress("音声を分割しています...", 0.2)
            chunks_dir = os.path.join(temp_dir, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            audio_chunks = split_audio(audio_path, chunks_dir)
            update_progress(f"文字起こしを開始します... ({len(audio_chunks)}チャンク)", 0.3)
            transcript = await transcribe_chunks(audio_chunks, client, update_progress)
            update_progress("文字起こし完了。分析を開始します...", 0.5)
            text_chunks = split_text(transcript)
            analyze_prompt = prompt_manager.get_analyze_prompt()
            merge_prompt = prompt_manager.get_merge_prompt()
            analyses = await analyze_text_chunks(text_chunks, analyze_prompt, client, update_progress)
            final_analysis = await merge_analyses(analyses, merge_prompt, client, update_progress)
            update_progress("分析完了。結果を保存します...", 0.95)
            try:
                data = {
                    "staff": staff_id,
                    "filename": filename,
                    "transcript": transcript[:10000] + ("..." if len(transcript) > 10000 else ""),
                    "model_mode": "gpt-4-turbo",
                    "model_name": "GPT-4 Turbo",
                    "analysis": final_analysis,
                    "created_at": datetime.now().isoformat()
                }
                supabase.table("assessments").delete().eq("staff", staff_id).eq("filename", filename).execute()
                supabase.table("assessments").insert(data).execute()
            except Exception as e:
                logger.exception("分析結果保存エラー")
        try:
            os.unlink(video_path)
        except Exception as e:
            logger.warning(f"一時ファイル削除エラー: {e}")
        if task_key in processing_tasks:
            processing_tasks[task_key].status = "completed"
            processing_tasks[task_key].progress = 1.0
            processing_tasks[task_key].completed_at = datetime.now().isoformat()
            processing_tasks[task_key].message = "分析が完了しました"
    except Exception as e:
        error_msg = f"分析エラー: {str(e)}"
        logger.exception(error_msg)
        if task_key in processing_tasks:
            processing_tasks[task_key].status = "error"
            processing_tasks[task_key].error = error_msg
            processing_tasks[task_key].completed_at = datetime.now().isoformat()
            processing_tasks[task_key].message = "分析中にエラーが発生しました"

# ===== 分析実行 =====
@app.post("/analyze/{staff_id}/{filename}")
async def analyze_file(staff_id: str, filename: str, force: bool = False, background_tasks: BackgroundTasks = None):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API Keyが設定されていません")
    task_key = f"{staff_id}:{filename}"
    try:
        if task_key in processing_tasks:
            task = processing_tasks[task_key]
            if task.status == "processing":
                return {"status": "processing", "message": f"分析実行中: {task.progress*100:.1f}%", "task_id": task_key}
            elif task.status == "completed" and not force:
                try:
                    response = supabase.table("assessments").select("*").eq("staff", staff_id).eq("filename", filename).execute()
                    if response.data and len(response.data) > 0:
                        return response.data[0]["analysis"]
                except Exception as e:
                    logger.warning(f"分析結果取得エラー: {e}")
        if not force:
            try:
                response = supabase.table("assessments").select("*").eq("staff", staff_id).eq("filename", filename).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]["analysis"]
            except Exception as e:
                logger.warning(f"既存の分析結果取得エラー: {e}")
        processing_tasks[task_key] = TaskStatus(
            staff_id=staff_id,
            filename=filename,
            status="processing",
            progress=0.0,
            message="分析を開始しています...",
            started_at=datetime.now().isoformat()
        )
        background_tasks.add_task(analyze_video_task, staff_id, filename)
        return {"status": "processing", "message": "分析を開始しました。タスクステータスを確認してください。", "task_id": task_key}
    except Exception as e:
        logger.exception("分析開始エラー")
        raise HTTPException(status_code=500, detail=f"分析エラー: {str(e)}")

# ===== 分析結果取得 =====
@app.get("/analysis/{staff_id}/{filename}")
def get_analysis(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    try:
        try:
            response = supabase.table("assessments").select("*").eq("staff", staff_id).eq("filename", filename).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]["analysis"]
        except Exception as e:
            logger.warning(f"分析結果取得エラー: {e}")
        task_key = f"{staff_id}:{filename}"
        if task_key in processing_tasks and processing_tasks[task_key].status == "processing":
            raise HTTPException(
                status_code=202,
                detail={"message": "分析処理中です", "progress": processing_tasks[task_key].progress, "status": "processing"}
            )
        raise HTTPException(status_code=404, detail=f"{filename}の分析結果が見つかりません")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("分析結果取得で予期しないエラー")
        raise HTTPException(status_code=500, detail=f"分析結果取得エラー: {str(e)}")

# ===== スタッフの全分析結果取得 =====
@app.get("/results/{staff_id}")
def get_staff_results(staff_id: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    try:
        try:
            response = supabase.table("assessments").select("*").eq("staff", staff_id).execute()
            return response.data
        except Exception as e:
            logger.warning(f"結果一覧取得エラー: {e}")
            return []
    except Exception as e:
        logger.exception("結果一覧取得で予期しないエラー")
        raise HTTPException(status_code=500, detail=f"結果一覧取得エラー: {str(e)}")

# ===== MIMEタイプ修正 =====
@app.post("/fix-mime-type/{staff_id}/{filename}")
async def fix_mime_type(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    try:
        file_path = f"{staff_id}/{filename}"
        response = supabase.storage.from_(SUPABASE_BUCKET).download(file_path)
        contents = response
        supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
        file_options = {"content-type": "video/mp4", "cache-control": "3600"}
        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, contents, file_options)
        return {"ok": True, "message": f"ファイル {filename} のMIMEタイプを修正しました"}
    except Exception as e:
        logger.exception("MIMEタイプ修正エラー")
        raise HTTPException(status_code=500, detail=f"MIMEタイプ修正エラー: {str(e)}")

# ===== ヘルスチェック =====
@app.get("/healthz")
def healthz():
    return {"status": "healthy"}
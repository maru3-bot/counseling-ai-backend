import os
import json
import tempfile
import subprocess
import shutil
import math
import asyncio
import requests
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from app_prompt_loader import PromptManager
from datetime import datetime
from pydantic import BaseModel

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
        # ファイル名からMIMEタイプを確認
        filename = file.filename
        content_type = file.content_type or "application/octet-stream"
        
        # 動画ファイルの場合、MIMEタイプを明示的に設定
        if filename.lower().endswith(('.mp4', '.mov', '.avi', '.wmv', '.mkv')):
            if 'video/' not in content_type:
                content_type = "video/mp4" if filename.lower().endswith('.mp4') else "video/quicktime"
        
        file_path = f"{staff_id}/{filename}"
        print(f"アップロード: {file_path}, サイズ: {len(contents)} bytes, タイプ: {content_type}")
        
        # 修正: ハイフン形式のキーを使用
        file_options = {
            "content-type": content_type,
            "cache-control": "3600"
        }
        
        # 既存のファイルがあれば削除してからアップロード
        try:
            supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
        except Exception:
            pass  # ファイルが存在しない場合も続行
            
        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, contents, file_options)
        return {"ok": True, "path": file_path, "type": content_type}
    except Exception as e:
        error_msg = f"アップロードエラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== 署名付きURLの取得 =====
@app.get("/signed-url/{staff_id}/{filename}")
def get_signed_url(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        file_path = f"{staff_id}/{filename}"
        
        # ファイルのメタデータを取得（存在確認のため）
        try:
            file_info = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file_path)
        except Exception as e:
            print(f"ファイル情報取得エラー: {e}")
            raise HTTPException(status_code=404, detail=f"ファイル {filename} が見つかりません")
        
        # 署名付きURLを1時間有効で生成（動画再生用）
        try:
            # トランスフォームを使ってみる（APIによってサポート状況が異なる）
            transform = { "format": "mp4" }
            signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
                file_path, 
                3600,
                transform=transform
            )
        except Exception:
            # トランスフォームがサポートされていない場合は通常のURLを使用
            signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
                file_path, 
                3600
            )
        
        return {"url": signed_url["signedURL"]}
    except Exception as e:
        error_msg = f"署名付きURL取得エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== ファイル削除 =====
@app.delete("/delete/{staff_id}/{filename}")
def delete_file(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        file_path = f"{staff_id}/{filename}"
        supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
        
        # 分析結果も削除（存在する場合）
        try:
            # テーブル構造に合わせてクエリを修正
            supabase.table("assessments").delete().eq("staff", staff_id).eq("filename", filename).execute()
        except Exception:
            pass  # テーブルがなくてもエラーにしない
            
        # 処理中のタスクがあれば削除
        task_key = f"{staff_id}:{filename}"
        if task_key in processing_tasks:
            del processing_tasks[task_key]
            
        return {"ok": True, "message": f"{filename} を削除しました"}
    except Exception as e:
        error_msg = f"削除エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

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
    """
    音声ファイルを指定したサイズのチャンクに分割する
    """
    # ファイルサイズの確認
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    
    if file_size_mb <= max_size_mb:
        # ファイルサイズが十分小さい場合はそのまま返す
        output_path = os.path.join(chunk_dir, "chunk_0.mp3")
        shutil.copy(input_path, output_path)
        return [output_path]
    
    # 動画/音声の長さを取得
    command = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{input_path}"'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"動画長さの取得に失敗しました: {result.stderr}")
    
    total_duration = float(result.stdout.strip())
    
    # チャンク数の計算
    chunks_count = math.ceil(file_size_mb / max_size_mb)
    chunk_duration = total_duration / chunks_count
    
    chunk_paths = []
    
    for i in range(chunks_count):
        start_time = i * chunk_duration
        output_path = os.path.join(chunk_dir, f"chunk_{i}.mp3")
        
        # チャンクを作成
        command = f'ffmpeg -y -i "{input_path}" -ss {start_time} -t {chunk_duration} -c:a libmp3lame -q:a 2 "{output_path}"'
        result = subprocess.run(command, shell=True, capture_output=True)
        
        if result.returncode != 0:
            raise Exception(f"音声チャンク{i}の作成に失敗しました")
        
        chunk_paths.append(output_path)
    
    return chunk_paths

# ===== 複数のチャンクを文字起こし =====
async def transcribe_chunks(chunk_paths: List[str], openai_client, update_progress) -> str:
    """
    複数の音声チャンクを文字起こしして結合する
    """
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
    
    # 全てのトランスクリプトを結合
    return " ".join(transcripts)

# ===== 大きなテキストを分割 =====
def split_text(text: str, max_tokens: int = 4000) -> List[str]:
    """
    大きなテキストを指定したトークン数以下のチャンクに分割する
    簡易版: 実際には文や段落の区切りで分割すべき
    """
    # 簡易的な日本語トークン見積もり: 文字数 * 0.4
    chars_per_token = 2.5
    max_chars = int(max_tokens * chars_per_token)
    
    # テキストを分割
    chunks = []
    for i in range(0, len(text), max_chars):
        chunks.append(text[i:i+max_chars])
    
    return chunks

# ===== テキストチャンクを分析 =====
async def analyze_text_chunks(text_chunks: List[str], system_prompt: str, openai_client, update_progress) -> List[Dict]:
    """
    テキストチャンクを分析して結果を返す
    """
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
    """
    複数の分析結果を1つにマージする
    """
    if len(analyses) == 1:
        return analyses[0]
    
    update_progress("複数の分析結果をマージ中...", 0.9)
    
    # 結果をJSON文字列にして送信
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
    """
    バックグラウンドで動画を分析するタスク
    """
    task_key = f"{staff_id}:{filename}"
    
    # 進捗状況更新関数
    def update_progress(message, progress):
        if task_key in processing_tasks:
            processing_tasks[task_key].message = message
            processing_tasks[task_key].progress = progress
            print(f"進捗更新: {message} ({progress*100:.1f}%)")
    
    try:
        import openai
        import tempfile
        import os
        
        file_path = f"{staff_id}/{filename}"
        
        # OpenAI クライアント初期化
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        update_progress("動画のダウンロードを開始します...", 0.01)
        
        # 署名付きURLを取得して動画をダウンロード
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(file_path, 3600)
        video_url = signed_url["signedURL"]
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as video_file:
            video_path = video_file.name
            
            # ダウンロード
            response = requests.get(video_url, stream=True)
            if response.status_code != 200:
                raise Exception("動画のダウンロードに失敗しました")
            
            # 進捗状況の更新
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
        
        # 一時ディレクトリの作成
        with tempfile.TemporaryDirectory() as temp_dir:
            # 音声の抽出（高圧縮率でサイズを削減）
            audio_path = os.path.join(temp_dir, "audio.mp3")
            command = f'ffmpeg -i "{video_path}" -q:a 3 -map a "{audio_path}" -y'
            process = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if process.returncode != 0:
                stderr = process.stderr.decode()
                raise Exception(f"音声の抽出に失敗しました: {stderr}")
            
            update_progress("音声を分割しています...", 0.2)
            
            # チャンクディレクトリ作成
            chunks_dir = os.path.join(temp_dir, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            
            # 音声を複数のチャンクに分割（Whisper APIの25MB制限に対応）
            audio_chunks = split_audio(audio_path, chunks_dir)
            
            update_progress(f"文字起こしを開始します... ({len(audio_chunks)}チャンク)", 0.3)
            
            # 全チャンクの文字起こし
            transcript = await transcribe_chunks(audio_chunks, client, update_progress)
            
            update_progress("文字起こし完了。分析を開始します...", 0.5)
            
            # テキストを適切なサイズに分割
            text_chunks = split_text(transcript)
            
            # システムプロンプト取得
            analyze_prompt = prompt_manager.get_analyze_prompt()
            merge_prompt = prompt_manager.get_merge_prompt()
            
            # 各チャンクを分析
            analyses = await analyze_text_chunks(text_chunks, analyze_prompt, client, update_progress)
            
            # 複数の分析結果をマージ
            final_analysis = await merge_analyses(analyses, merge_prompt, client, update_progress)
            
            update_progress("分析完了。結果を保存します...", 0.95)
            
            # 分析結果をSupabaseに保存
            try:
                # 実際のテーブル構造に合わせてデータを整形
                data = {
                    "staff": staff_id,
                    "filename": filename,
                    "transcript": transcript[:10000] + ("..." if len(transcript) > 10000 else ""),  # 長すぎる場合は切り詰め
                    "model_mode": "gpt-4-turbo",
                    "model_name": "GPT-4 Turbo",
                    "analysis": final_analysis,
                    "created_at": datetime.now().isoformat()
                }
                
                # 挿入前に同じエントリがないか確認して削除
                supabase.table("assessments").delete().eq("staff", staff_id).eq("filename", filename).execute()
                
                # 新しいデータを挿入
                supabase.table("assessments").insert(data).execute()
            except Exception as e:
                print(f"分析結果保存エラー: {e}")
        
        # 一時ファイルの削除
        try:
            os.unlink(video_path)
        except Exception as e:
            print(f"一時ファイル削除エラー: {e}")
            
        # タスク完了を設定
        if task_key in processing_tasks:
            processing_tasks[task_key].status = "completed"
            processing_tasks[task_key].progress = 1.0
            processing_tasks[task_key].completed_at = datetime.now().isoformat()
            processing_tasks[task_key].message = "分析が完了しました"
            
    except Exception as e:
        error_msg = f"分析エラー: {str(e)}"
        print(error_msg)
        
        # エラーを記録
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
        # 既存のタスクがあるか確認
        if task_key in processing_tasks:
            task = processing_tasks[task_key]
            if task.status == "processing":
                return {"status": "processing", "message": f"分析実行中: {task.progress*100:.1f}%", "task_id": task_key}
            elif task.status == "completed":
                # 完了済みタスクは、強制分析でなければ結果を返す
                if not force:
                    try:
                        response = supabase.table("assessments").select("*").eq("staff", staff_id).eq("filename", filename).execute()
                        if response.data and len(response.data) > 0:
                            return response.data[0]["analysis"]
                    except Exception as e:
                        print(f"分析結果取得エラー: {e}")
        
        # 既存の分析結果をチェック（forceがFalseの場合は既存の結果を返す）
        if not force:
            try:
                response = supabase.table("assessments").select("*").eq("staff", staff_id).eq("filename", filename).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]["analysis"]
            except Exception as e:
                print(f"既存の分析結果取得エラー: {e}")
        
        # 新しい分析タスクを開始
        processing_tasks[task_key] = TaskStatus(
            staff_id=staff_id,
            filename=filename,
            status="processing",
            progress=0.0,
            message="分析を開始しています...",
            started_at=datetime.now().isoformat()
        )
        
        # バックグラウンドタスクとして分析を開始
        background_tasks.add_task(analyze_video_task, staff_id, filename)
        
        return {
            "status": "processing", 
            "message": "分析を開始しました。タスクステータスを確認してください。",
            "task_id": task_key
        }
    except Exception as e:
        error_msg = f"分析エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== 分析結果取得 =====
@app.get("/analysis/{staff_id}/{filename}")
def get_analysis(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        # テーブル構造に合わせてクエリを修正
        try:
            response = supabase.table("assessments").select("*").eq("staff", staff_id).eq("filename", filename).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]["analysis"]
        except Exception as e:
            print(f"分析結果取得エラー: {e}")
            
        # 分析中かチェック
        task_key = f"{staff_id}:{filename}"
        if task_key in processing_tasks and processing_tasks[task_key].status == "processing":
            raise HTTPException(
                status_code=202,  # Accepted
                detail={
                    "message": "分析処理中です",
                    "progress": processing_tasks[task_key].progress,
                    "status": "processing"
                }
            )
            
        # 分析結果がない場合は404
        raise HTTPException(status_code=404, detail=f"{filename}の分析結果が見つかりません")
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"分析結果取得エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== スタッフの全分析結果取得 =====
@app.get("/results/{staff_id}")
def get_staff_results(staff_id: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        # テーブル構造に合わせてクエリを修正
        try:
            response = supabase.table("assessments").select("*").eq("staff", staff_id).execute()
            return response.data
        except Exception as e:
            print(f"結果一覧取得エラー: {e}")
            return []
    except Exception as e:
        error_msg = f"結果一覧取得エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== MIMEタイプ修正 =====
@app.post("/fix-mime-type/{staff_id}/{filename}")
async def fix_mime_type(staff_id: str, filename: str):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    try:
        file_path = f"{staff_id}/{filename}"
        
        # ファイルをダウンロード
        response = supabase.storage.from_(SUPABASE_BUCKET).download(file_path)
        contents = response
        
        # 一旦削除
        supabase.storage.from_(SUPABASE_BUCKET).remove([file_path])
        
        # 正しいMIMEタイプで再アップロード
        file_options = {
            "content-type": "video/mp4",
            "cache-control": "3600"
        }
        
        supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, contents, file_options)
        return {"ok": True, "message": f"ファイル {filename} のMIMEタイプを修正しました"}
    except Exception as e:
        error_msg = f"MIMEタイプ修正エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== ヘルスチェック =====
@app.get("/healthz")
def healthz():
    return {"status": "healthy"}
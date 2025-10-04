from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from supabase import create_client
import os
from datetime import datetime
import json
import tempfile
from openai import OpenAI
from app_prompt_loader import PromptManager

# --- 環境変数から取得 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Initialize PromptManager
prompt_manager = PromptManager(
    analyze_prompt_path=os.getenv("ANALYZE_PROMPT_PATH", "prompts/analyze_system_prompt.md"),
    merge_prompt_path=os.getenv("MERGE_PROMPT_PATH", "prompts/merge_system_prompt.md"),
    company_values_path=os.getenv("COMPANY_VALUES_PATH", "prompts/company_values.md"),
    education_plan_path=os.getenv("EDUCATION_PLAN_PATH", "prompts/education_plan.md"),
)

app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Viteフロント
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for analysis results (in production, use a database)
analysis_results = {}


@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    """
    指定スタッフのフォルダに動画をアップロード
    ファイル名は `YYYYMMDD-HHMMSS_元ファイル名`
    """
    try:
        # ユニークなファイル名を作成
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"

        # staff フォルダ付きのパス
        path = f"{staff}/{unique_filename}"

        # ファイル内容を読み込んでアップロード
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
async def list_files(staff: str):
    """
    指定スタッフのフォルダ内のファイル一覧を取得
    """
    try:
        result = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        return {"files": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signed-url/{staff}/{filename}")
async def get_signed_url(staff: str, filename: str):
    """
    指定ファイルの署名付きURL取得（有効期限60秒）
    """
    try:
        path = f"{staff}/{filename}"
        url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, 60)
        return {"url": url["signedURL"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete/{staff}/{filename}")
async def delete_file(staff: str, filename: str):
    """
    指定ファイルを削除
    """
    try:
        path = f"{staff}/{filename}"
        supabase.storage.from_(SUPABASE_BUCKET).remove([path])
        return {"message": "削除成功", "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def transcribe_audio(audio_path: str) -> str:
    """
    Whisper APIで音声ファイルを文字起こし
    ファイルサイズが25MBを超える場合は自動で処理
    """
    if not openai_client:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")
    
    file_size = os.path.getsize(audio_path)
    max_size = 25 * 1024 * 1024  # 25MB
    
    with open(audio_path, "rb") as audio_file:
        if file_size > max_size:
            # Large files: would need chunking logic in production
            # For now, just try to transcribe as-is
            pass
        
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )
    
    return transcript


def analyze_transcript_chunk(transcript_chunk: str) -> dict:
    """
    トランスクリプトのチャンクをGPT-4で分析（JSON mode）
    """
    if not openai_client:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")
    
    # Get the analysis prompt from PromptManager (with hot-reload)
    system_prompt = prompt_manager.get_analyze_prompt()
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Transcript:\n\n{transcript_chunk}"}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    )
    
    result = json.loads(response.choices[0].message.content)
    return result


def merge_analyses(analyses: list) -> dict:
    """
    複数の分析結果を統合
    """
    if not openai_client:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")
    
    if len(analyses) == 1:
        return analyses[0]
    
    # Get the merge prompt from PromptManager (with hot-reload)
    system_prompt = prompt_manager.get_merge_prompt()
    
    analyses_text = json.dumps(analyses, ensure_ascii=False, indent=2)
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyses to merge:\n\n{analyses_text}"}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    )
    
    result = json.loads(response.choices[0].message.content)
    return result


def chunk_transcript(transcript: str, max_tokens: int = 3000) -> list:
    """
    トランスクリプトを複数のチャンクに分割
    簡易実装: 文字数ベースで分割（本番では token count を使用）
    """
    # Rough estimate: 1 token ≈ 4 characters for Japanese/English mix
    max_chars = max_tokens * 4
    
    if len(transcript) <= max_chars:
        return [transcript]
    
    chunks = []
    start = 0
    while start < len(transcript):
        end = start + max_chars
        # Try to break at sentence boundary
        if end < len(transcript):
            # Look for sentence end markers
            for marker in ["。", ".", "！", "!", "？", "?"]:
                last_marker = transcript.rfind(marker, start, end)
                if last_marker != -1:
                    end = last_marker + 1
                    break
        
        chunks.append(transcript[start:end])
        start = end
    
    return chunks


async def process_analysis(staff: str, filename: str, analysis_id: str):
    """
    バックグラウンドで分析処理を実行
    """
    try:
        analysis_results[analysis_id] = {"status": "processing", "progress": 0}
        
        # Download file from Supabase
        path = f"{staff}/{filename}"
        file_data = supabase.storage.from_(SUPABASE_BUCKET).download(path)
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
            tmp_file.write(file_data)
            tmp_path = tmp_file.name
        
        try:
            # Transcribe audio
            analysis_results[analysis_id]["progress"] = 30
            transcript = transcribe_audio(tmp_path)
            
            # Chunk and analyze
            analysis_results[analysis_id]["progress"] = 60
            chunks = chunk_transcript(transcript)
            chunk_analyses = []
            
            for chunk in chunks:
                chunk_analysis = analyze_transcript_chunk(chunk)
                chunk_analyses.append(chunk_analysis)
            
            # Merge results
            analysis_results[analysis_id]["progress"] = 90
            final_analysis = merge_analyses(chunk_analyses)
            
            # Store results
            analysis_results[analysis_id] = {
                "status": "completed",
                "progress": 100,
                "transcript": transcript,
                "analysis": final_analysis
            }
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    except Exception as e:
        analysis_results[analysis_id] = {
            "status": "failed",
            "error": str(e)
        }


@app.post("/analyze/{staff}/{filename}")
async def analyze_video(staff: str, filename: str, background_tasks: BackgroundTasks):
    """
    動画ファイルの分析を開始（非同期処理）
    """
    try:
        # Generate analysis ID
        analysis_id = f"{staff}_{filename}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Start background processing
        background_tasks.add_task(process_analysis, staff, filename, analysis_id)
        
        return {
            "message": "分析を開始しました",
            "analysis_id": analysis_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analysis/{analysis_id}")
async def get_analysis_status(analysis_id: str):
    """
    分析のステータスを取得
    """
    if analysis_id not in analysis_results:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    result = analysis_results[analysis_id]
    
    # Return status and progress without full results
    return {
        "status": result.get("status"),
        "progress": result.get("progress", 0),
        "error": result.get("error")
    }


@app.get("/results/{analysis_id}")
async def get_analysis_results(analysis_id: str):
    """
    分析結果を取得
    """
    if analysis_id not in analysis_results:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    result = analysis_results[analysis_id]
    
    if result.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Analysis not completed yet")
    
    return {
        "transcript": result.get("transcript"),
        "analysis": result.get("analysis")
    }


@app.get("/healthz")
async def health_check():
    """
    ヘルスチェックエンドポイント
    """
    return {"status": "ok"}

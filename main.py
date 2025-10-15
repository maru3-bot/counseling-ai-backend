import os
import json
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from app_prompt_loader import PromptManager

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
        
        # MIMEタイプを明示的に指定してアップロード
        file_options = {
            "contentType": content_type,
            "cacheControl": "3600",
            "upsert": True
        }
        
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
        # トランスフォームを使って適切なContent-Typeを強制する
        transform = {
            "format": "mp4",  # 強制的にmp4として扱う
        }
        
        try:
            signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
                file_path, 
                3600,  # 1時間有効
                transform=transform,
            )
        except Exception as e:
            # トランスフォームが使えない場合は通常のURLを使用
            signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
                file_path, 
                3600,  # 1時間有効
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
            # Supabaseにテーブルがあれば削除
            supabase.table("assessments").delete().eq("path", file_path).execute()
        except Exception:
            pass  # テーブルがなくてもエラーにしない
            
        return {"ok": True, "message": f"{filename} を削除しました"}
    except Exception as e:
        error_msg = f"削除エラー: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# ===== 分析実行 =====
@app.post("/analyze/{staff_id}/{filename}")
async def analyze_file(staff_id: str, filename: str, force: bool = False):
    if supabase_error:
        raise HTTPException(status_code=500, detail=f"Supabase接続エラー: {supabase_error}")
    
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API Keyが設定されていません")
    
    try:
        import openai
        from datetime import datetime
        
        file_path = f"{staff_id}/{filename}"
        
        # 既存の分析結果をチェック（forceがFalseの場合は既存の結果を返す）
        if not force:
            try:
                # Supabaseから既存の分析結果を取得
                response = supabase.table("assessments").select("*").eq("path", file_path).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]["analysis"]
            except Exception as e:
                print(f"既存の分析結果取得エラー: {e}")
                # テーブルがない場合は続行
        
        # 署名付きURLを取得
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(file_path, 3600)
        video_url = signed_url["signedURL"]
        
        # OpenAI APIを使用して分析（実際の実装は省略）
        # 本来はWhisperで文字起こしをしてGPTで分析するべきですが、簡易版として
        openai.api_key = OPENAI_API_KEY
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        # システムプロンプトの取得
        system_prompt = prompt_manager.get_analyze_prompt()
        
        # 分析結果のモックアップ
        # 実際の実装ではWhisper APIで文字起こしを行い、その結果をGPTに渡します
        mock_analysis = {
            "summary": f"{filename}の分析結果です。実際の実装ではWhisperで文字起こしを行い、その内容をGPTに分析させます。",
            "strengths": ["顧客の要望をよく聞いている", "適切な提案をしている", "専門用語を分かりやすく説明している"],
            "improvements": ["もう少し具体的な例を出すと良い", "選択肢を増やすと良い", "フォローアップの提案ができると良い"],
            "risk_flags": [],
            "scores": {"empathy": 4, "active_listening": 4, "clarity": 3, "problem_solving": 3},
            "overall_comment": "全体として良好なカウンセリングですが、より具体的な選択肢の提示とフォローアップの計画があるとさらに良くなります。"
        }
        
        # 実際の実装では以下のように行う
        # 1. Whisper APIで音声を文字起こし
        # 2. GPT APIで文字起こしを分析
        # 3. 結果を整形
        
        # 分析結果をSupabaseに保存
        try:
            # assessmentsテーブルがない場合は作成される
            data = {
                "path": file_path,
                "filename": filename,
                "staff_id": staff_id,
                "analysis": mock_analysis,
                "created_at": datetime.now().isoformat()
            }
            supabase.table("assessments").upsert(data).execute()
        except Exception as e:
            print(f"分析結果保存エラー: {e}")
            # 保存に失敗しても分析結果は返す
        
        return mock_analysis
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
        file_path = f"{staff_id}/{filename}"
        
        # Supabaseから分析結果を取得
        try:
            response = supabase.table("assessments").select("*").eq("path", file_path).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]["analysis"]
        except Exception as e:
            print(f"分析結果取得エラー: {e}")
            
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
        # Supabaseからスタッフの全分析結果を取得
        try:
            response = supabase.table("assessments").select("*").eq("staff_id", staff_id).execute()
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
            "contentType": "video/mp4",
            "cacheControl": "3600",
            "upsert": True
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
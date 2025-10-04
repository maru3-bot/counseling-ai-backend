from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os
from datetime import datetime
import mimetypes
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# --- 環境変数から取得 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],  # Viteフロント (localhost and 127.0.0.1)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def guess_content_type(filename: str) -> str:
    """
    ファイル名から適切なContent-Typeを推測
    """
    content_type, _ = mimetypes.guess_type(filename)
    if content_type:
        return content_type
    # デフォルトは application/octet-stream
    return "application/octet-stream"


@app.get("/healthz")
async def healthz():
    """
    ヘルスチェック用エンドポイント
    """
    return {"status": "ok"}


@app.post("/upload/{staff}")
async def upload_file(staff: str, file: UploadFile = File(...)):
    """
    指定スタッフのフォルダに動画をアップロード
    ファイル名は `YYYYMMDD-HHMMSS_元ファイル名`
    Content-Typeを正しく設定してアップロード
    """
    try:
        # ユニークなファイル名を作成
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_filename = f"{timestamp}_{file.filename}"

        # staff フォルダ付きのパス
        path = f"{staff}/{unique_filename}"

        # Content-Typeを推測
        content_type = guess_content_type(file.filename)

        # ファイル内容を読み込んでアップロード
        content = await file.read()
        
        # file_optionsでContent-Typeとupsertを指定
        file_options = {
            "content-type": content_type,
            "x-upsert": "true"
        }
        
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path, 
            content,
            file_options=file_options
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
async def list_files(staff: str):
    """
    指定スタッフのフォルダ内のファイル一覧を取得
    """
    try:
        # staffフォルダのファイル一覧を取得
        res = supabase.storage.from_(SUPABASE_BUCKET).list(staff)
        
        # ファイル名のリストを返す
        files = [{"name": item["name"]} for item in res]
        
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signed-url/{staff}/{filename}")
async def get_signed_url(staff: str, filename: str):
    """
    指定ファイルの署名付きURLを取得（インライン再生用にdownloadパラメータを除去）
    """
    try:
        # ファイルパスを構築
        path = f"{staff}/{filename}"
        
        # 署名付きURLを作成（60分有効）
        res = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
            path, 
            3600  # 60分 = 3600秒
        )
        
        # URLを取得
        signed_url = res.get("signedURL")
        
        if not signed_url:
            raise HTTPException(status_code=404, detail="ファイルが見つかりません")
        
        # downloadパラメータを除去してインライン再生を可能にする
        parsed = urlparse(signed_url)
        query_params = parse_qs(parsed.query)
        
        # downloadパラメータを削除
        if "download" in query_params:
            del query_params["download"]
        
        # クエリ文字列を再構築
        new_query = urlencode(query_params, doseq=True)
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        
        return {"url": new_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

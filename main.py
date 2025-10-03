from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os

# --- 環境変数から取得 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key推奨
SUPABASE_BUCKET = "videos"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# CORS設定（Reactから叩けるように）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite
        "http://localhost:3000",  # create-react-app 互換
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/signed-url/{filename}")
def get_signed_url(filename: str):
    """
    Supabase から署名付きURLを発行して返す
    有効期限: 1年間 (31,536,000秒)
    """
    try:
        expires_in = 60 * 60 * 24 * 365  # 1年
        result = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(filename, expires_in)

        # 新しい supabase-py は str を返す
        if isinstance(result, str):
            return {"url": result}

        # 古い supabase-py は dict を返す
        if isinstance(result, dict) and "signedURL" in result:
            return {"url": result["signedURL"]}

        raise HTTPException(status_code=400, detail="署名付きURLの生成に失敗しました")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key 推奨
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # 本番ではフロントのURLを追加
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ ファイル一覧を返すエンドポイント
@app.get("/list")
def list_files():
    try:
        res = supabase.storage.from_(SUPABASE_BUCKET).list()
        files = [{"filename": f["name"]} for f in res]
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ 署名付きURLを返すエンドポイント
@app.get("/signed-url/{filename}")
def get_signed_url(filename: str):
    try:
        expires_in = 60 * 60 * 24 * 365  # 1年
        signed_url = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(filename, expires_in)

        if not signed_url:
            raise HTTPException(status_code=400, detail="署名付きURLの生成に失敗しました")

        if isinstance(signed_url, dict) and "signedURL" in signed_url:
            return {"url": signed_url["signedURL"]}
        else:
            return {"url": signed_url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

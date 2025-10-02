from fastapi import FastAPI, UploadFile, File

app = FastAPI()

@app.get("/")
async def read_root():
    return {"message": "Hello from Counseling AI Backend!"}

# アップロードエンドポイント
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # ここではファイルを保存せず、ファイル名だけ返す
    return {"filename": file.filename}

# counseling-ai-backend
社内カウンセリング教育アプリケーション

## セットアップ

### バックエンド (FastAPI)

1. 環境変数を設定:
```bash
export SUPABASE_URL="your-supabase-url"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
export SUPABASE_BUCKET="videos"  # オプション、デフォルトは "videos"
```

2. 依存関係をインストール:
```bash
pip install -r requirements.txt
```

3. サーバーを起動:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### フロントエンド (React + Vite)

1. フロントエンドディレクトリに移動:
```bash
cd counseling-ai-frontend
```

2. 依存関係をインストール:
```bash
npm install
```

3. 環境変数を設定（ローカル開発用）:
```bash
cp .env.example .env.local
# .env.localを編集してAPI_BASEを設定
# VITE_API_BASE=http://localhost:8000
```

4. 開発サーバーを起動:
```bash
npm run dev
```

## API エンドポイント

- `GET /healthz` - ヘルスチェック
- `POST /upload/{staff}` - 動画アップロード（スタッフ別フォルダ）
- `GET /list/{staff}` - スタッフ別動画一覧取得
- `GET /signed-url/{staff}/{filename}` - 動画再生用署名付きURL取得

## 機能

- スタッフ別の動画アップロードと管理
- Supabase Storageを使用した動画保存
- 署名付きURLによる安全な動画再生
- ダークモード対応UI


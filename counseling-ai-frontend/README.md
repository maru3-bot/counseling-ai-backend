# counseling-ai-backend
社内カウンセリング教育アプリケーション

## 概要
- FastAPI + Supabase(Storage/DB)
- Whisper(OpenAI)で文字起こし
- GPT-4o/4o-mini で要約・採点（OpenAIのみ）
- 環境変数 `USE_MODEL` で切替（`low`/`high`）

## 環境変数
```
# Supabase
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_BUCKET=videos

# OpenAI
OPENAI_API_KEY=sk-...

# モデル切替
USE_MODEL=low   # low=gpt-4o-mini, high=gpt-4o
```

## 依存関係
`requirements.txt` を参照（openai を追加）

## DB（Postgres）スキーマ
SupabaseのSQLエディタで以下を実行してください。

```sql
create table if not exists public.assessments (
  id uuid primary key default gen_random_uuid(),
  staff text not null,
  filename text not null,
  transcript text,
  model_mode text,
  model_name text,
  analysis jsonb,
  created_at timestamptz default now(),
  unique (staff, filename)
);

create index if not exists idx_assessments_staff_created_at
on public.assessments (staff, created_at desc);
```

## API
- POST `/upload/{staff}`: 動画アップロード（Storage）
- GET `/list/{staff}`: 動画一覧（Storage）
- GET `/signed-url/{staff}/{filename}`: 再生用の署名付きURL
- POST `/analyze/{staff}/{filename}`: 文字起こし→要約・採点を実行（DBに保存、同一ファイルは上書き）
  - クエリ `force=true` で再分析
- GET `/analysis/{staff}/{filename}`: 既存の分析結果取得（未実行なら404）
- GET `/results/{staff}`: スタッフの分析結果一覧

## 動作モード（モデル）
- `USE_MODEL=low` → OpenAI: `gpt-4o-mini`（コスト安・検証向け）
- `USE_MODEL=high` → OpenAI: `gpt-4o`（精度重視・本番向け）

文字起こしは `whisper-1` 固定。
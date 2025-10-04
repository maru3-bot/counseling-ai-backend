# counseling-ai-backend
社内カウンセリング教育アプリケーション

## 機能概要
- 動画/音声のアップロード・一覧・再生（Supabase Storage）
- 文字起こし（OpenAI Whisper、自動音声抽出・圧縮で25MB制限を回避）
- 要約/強み/改善/スコア/講評の自動分析（JSONモード、長文は分割→統合）
- 分析結果の保存/取得（assessmentsテーブル、未作成でも動作）
- プロンプトはMarkdown外部ファイルでホットリロード（サーバ再起動不要）

## 必要環境変数 (.env)
```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_BUCKET=videos

OPENAI_API_KEY=
USE_MODEL=low  # low|high

# プロンプトのパス（未設定なら既定を使用）
ANALYZE_PROMPT_PATH=prompts/analyze_system_prompt.md
MERGE_PROMPT_PATH=prompts/merge_system_prompt.md
COMPANY_VALUES_PATH=prompts/company_values.md
EDUCATION_PLAN_PATH=prompts/education_plan.md
```

## 起動
```
# 仮想環境を有効化後
uvicorn main:app --reload --port 8000 --host 127.0.0.1 --env-file .env
```
- ヘルスチェック: http://127.0.0.1:8000/healthz

## API（主要）
- POST /upload/{staff}
- GET  /list/{staff}
- GET  /signed-url/{staff}/{filename}
- DELETE /delete/{staff}/{filename}
- POST /analyze/{staff}/{filename}?force=true|false
- GET  /analysis/{staff}/{filename}
- GET  /results/{staff}

## プロンプト外部化
- prompts/analyze_system_prompt.md（分析の指示）
- prompts/merge_system_prompt.md（分割結果の統合指示）
- 差し込み: prompts/company_values.md, prompts/education_plan.md
- これらを保存すると、次回の「分析する」から自動反映されます（再起動不要）。
# counseling-ai-backend
社内カウンセリング教育アプリケーション

## 概要

このバックエンドは、カウンセリングセッションの動画をアップロード、分析し、フィードバックを生成するためのAPIを提供します。

## 新機能: 外部プロンプト管理

### 特徴

- **編集可能なプロンプト**: プロンプトは外部のMarkdownファイルとして管理され、コードを変更せずに編集可能
- **ホットリロード**: ファイルを編集すると、サーバーを再起動せずに変更が反映される
- **プレースホルダー置換**: `{{company_values}}` と `{{education_plan}}` プレースホルダーを使用して、会社の価値観や教育計画を動的に挿入
- **環境変数サポート**: プロンプトファイルのパスは環境変数でカスタマイズ可能

### プロンプトファイル

- `prompts/analyze_system_prompt.md` - 分析用システムプロンプト
- `prompts/merge_system_prompt.md` - 複数チャンクの統合用プロンプト
- `prompts/company_values.md` - 会社の価値観（オプション）
- `prompts/education_plan.md` - 教育計画（オプション）

### 使用方法

1. プロンプトファイルを直接編集
2. 保存後、次のリクエストで自動的に反映される（再起動不要）
3. プレースホルダーを使用して、長い会社の方針や教育フレームワークを含める

### 設定

`.env`ファイルで以下の環境変数を設定できます（`.env.example`を参照）:

```env
# プロンプトファイルパス（オプション、デフォルト値）
ANALYZE_PROMPT_PATH=prompts/analyze_system_prompt.md
MERGE_PROMPT_PATH=prompts/merge_system_prompt.md
COMPANY_VALUES_PATH=prompts/company_values.md
EDUCATION_PLAN_PATH=prompts/education_plan.md
```

## API エンドポイント

- `POST /upload/{staff}` - 動画ファイルをアップロード
- `GET /list/{staff}` - スタッフの動画一覧を取得
- `GET /signed-url/{staff}/{filename}` - 署名付きURL取得
- `DELETE /delete/{staff}/{filename}` - 動画ファイルを削除
- `POST /analyze/{staff}/{filename}` - 動画の分析を開始
- `GET /analysis/{analysis_id}` - 分析のステータスを確認
- `GET /results/{analysis_id}` - 分析結果を取得
- `GET /healthz` - ヘルスチェック

## セットアップ

1. 依存関係のインストール:
```bash
pip install -r requirements.txt
```

2. 環境変数の設定（`.env.example`を`.env`にコピーして編集）

3. サーバーの起動:
```bash
uvicorn main:app --reload
```

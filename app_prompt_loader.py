import os
from typing import Optional, Dict

class PromptManager:
    """
    - Markdown のプロンプトファイルを読み込む
    - mtime を見て変更があれば自動リロード
    - {{company_values}} / {{education_plan}} を別ファイルから差し込み
    """
    def __init__(self) -> None:
        self.analyze_path = os.getenv("ANALYZE_PROMPT_PATH", "prompts/analyze_system_prompt.md")
        self.merge_path = os.getenv("MERGE_PROMPT_PATH", "prompts/merge_system_prompt.md")
        self.company_values_path = os.getenv("COMPANY_VALUES_PATH", "")
        self.education_plan_path = os.getenv("EDUCATION_PLAN_PATH", "")

        self._cache: Dict[str, str] = {}
        self._mtimes: Dict[str, float] = {}

        # デフォルト（ファイルが見つからない場合の安全装置）
        self._default_analyze = """あなたはたくさんの顧客を抱える日本人美容師です。
{{company_values}}

{{education_plan}}

以下の観点で会話の文字起こしを日本語で評価してください。
- 要約（200〜400字程度）
- 強み（箇条書き3〜5個）
- 改善提案（箇条書き3〜5個、実践的に）
- リスク・注意点（該当があれば）
- スコア（1〜5、整数）: empathy, active_listening, clarity, problem_solving
- 全体講評（200〜300字）

必ず次のJSONだけを返してください:
{
  "summary": "...",
  "strengths": ["...", "..."],
  "improvements": ["...", "..."],
  "risk_flags": ["..."],
  "scores": { "empathy": 3, "active_listening": 3, "clarity": 3, "problem_solving": 3 },
  "overall_comment": "..."
}
"""
        self._default_merge = """あなたは複数の部分分析結果(JSON)を統合して、最終の単一JSONにまとめます。
重複は整理し、矛盾は整合的に統合してください。
最終フォーマット:
{
  "summary": "...",
  "strengths": ["..."],
  "improvements": ["..."],
  "risk_flags": ["..."],
  "scores": { "empathy": 1, "active_listening": 1, "clarity": 1, "problem_solving": 1 },
  "overall_comment": "..."
}
"""

    def _read_file(self, path: str) -> Optional[str]:
        if not path:
            return None
        if not os.path.isfile(path):
            return None
        mtime = os.path.getmtime(path)
        if path in self._mtimes and self._mtimes[path] == mtime:
            return self._cache.get(path)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        self._mtimes[path] = mtime
        self._cache[path] = text
        return text

    def _substitute(self, text: str) -> str:
        values = self._read_file(self.company_values_path) or ""
        plan = self._read_file(self.education_plan_path) or ""
        return (
            text.replace("{{company_values}}", values)
                .replace("{{education_plan}}", plan)
        )

    def get_analyze_prompt(self) -> str:
        text = self._read_file(self.analyze_path) or self._default_analyze
        return self._substitute(text)

    def get_merge_prompt(self) -> str:
        text = self._read_file(self.merge_path) or self._default_merge
        return self._substitute(text)
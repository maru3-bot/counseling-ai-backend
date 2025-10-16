"""
PromptManager: Loads and hot-reloads external prompts from disk.
"""

import os
from pathlib import Path
from typing import Optional

class PromptManager:
    """
    Manages external prompt files with hot-reload capability.
    """

    def __init__(
        self,
        analyze_prompt_path: str = "prompts/analyze_system_prompt.md",
        merge_prompt_path: str = "prompts/merge_system_prompt.md",
        company_values_path: Optional[str] = "prompts/company_values.md",
        education_plan_path: Optional[str] = "prompts/education_plan.md",
    ):
        # 実行環境差異（/opt/render/project/src など）に強いルート候補を用意
        this_file = Path(__file__).resolve()
        candidates = [
            this_file.parent,          # 例: /opt/render/project/src
            this_file.parent.parent,   # 例: /opt/render/project
            Path.cwd(),                # カレント
        ]

        def resolve_path(rel: Optional[str]) -> Optional[Path]:
            if not rel:
                return None
            for base in candidates:
                p = (base / rel).resolve()
                if p.exists():
                    return p
            # 見つからない場合は最初の候補に結合して返す（存在はしないが、後段でバックアップにフォールバック）
            return (candidates[0] / rel).resolve()

        # 絶対パスに解決
        self.analyze_prompt_path = resolve_path(analyze_prompt_path)
        self.merge_prompt_path = resolve_path(merge_prompt_path)
        self.company_values_path = resolve_path(company_values_path) if company_values_path else None
        self.education_plan_path = resolve_path(education_plan_path) if education_plan_path else None

        print(f"プロンプトパス: analyze={self.analyze_prompt_path} merge={self.merge_prompt_path}")

        # Cache for prompt contents and modification times
        self._cache = {}
        self._mtimes = {}

        # プロンプトファイルが見つからない場合のバックアップ内容
        self._backup_prompts = {
            "analyze_prompt": "あなたは美容師です。会話を評価してください。",
            "merge_prompt": "複数の分析結果を統合してください。",
            "company_values": "・お客様の安心と納得を最優先\n・根拠ある提案\n・再現性の高いスタイルづくり",
            "education_plan": "・対話は「確認→提案→合意」の順に進める\n・提案には「理由・手入れ時間・持続期間」を必ず含める"
        }

    def _read_file(self, path: Optional[Path]) -> str:
        """
        Read a file and return its contents.
        Returns backup content if file doesn't exist.
        """
        if not path or not path.exists():
            basename = path.name if isinstance(path, Path) else ""
            key = basename.replace(".md", "")
            if path and "analyze" in str(path):
                key = "analyze_prompt"
            elif path and "merge" in str(path):
                key = "merge_prompt"
            elif path and "company" in str(path):
                key = "company_values"
            elif path and "education" in str(path):
                key = "education_plan"

            print(f"警告: ファイル {path} が見つからないためバックアップを使用します")
            return self._backup_prompts.get(key, "")

        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"警告: ファイル読み込みエラー {path}: {e}")
            basename = path.name if isinstance(path, Path) else ""
            key = basename.replace(".md", "")
            return self._backup_prompts.get(key, "")

    def _get_file_mtime(self, path: Optional[Path]) -> float:
        if not path or not path.exists():
            return 0.0
        try:
            return path.stat().st_mtime
        except Exception:
            return 0.0

    def _load_prompt(self, path: Optional[Path], cache_key: str) -> str:
        current_mtime = self._get_file_mtime(path)
        cached_mtime = self._mtimes.get(cache_key, 0.0)

        if cache_key not in self._cache or current_mtime != cached_mtime:
            content = self._read_file(path)
            self._cache[cache_key] = content
            self._mtimes[cache_key] = current_mtime

        return self._cache[cache_key]

    def _substitute_placeholders(self, prompt: str) -> str:
        if "{{company_values}}" in prompt:
            company_values = self._load_prompt(self.company_values_path, "company_values")
            prompt = prompt.replace("{{company_values}}", company_values)

        if "{{education_plan}}" in prompt:
            education_plan = self._load_prompt(self.education_plan_path, "education_plan")
            prompt = prompt.replace("{{education_plan}}", education_plan)

        return prompt

    def get_analyze_prompt(self) -> str:
        prompt = self._load_prompt(self.analyze_prompt_path, "analyze_prompt")
        return self._substitute_placeholders(prompt)

    def get_merge_prompt(self) -> str:
        prompt = self._load_prompt(self.merge_prompt_path, "merge_prompt")
        return self._substitute_placeholders(prompt)
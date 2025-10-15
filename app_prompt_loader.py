"""
PromptManager: Loads and hot-reloads external prompts from disk.
"""

import os
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
        # 絶対パスに変換して確実に見つけられるようにする
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        self.analyze_prompt_path = os.path.join(self.base_dir, analyze_prompt_path)
        self.merge_prompt_path = os.path.join(self.base_dir, merge_prompt_path)
        self.company_values_path = os.path.join(self.base_dir, company_values_path) if company_values_path else None
        self.education_plan_path = os.path.join(self.base_dir, education_plan_path) if education_plan_path else None
        
        print(f"プロンプトパス: {self.analyze_prompt_path}")
        
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
    
    def _read_file(self, path: str) -> str:
        """
        Read a file and return its contents.
        Returns backup content if file doesn't exist.
        """
        if not path or not os.path.exists(path):
            key = os.path.basename(path).replace(".md", "")
            if "analyze" in path:
                key = "analyze_prompt"
            elif "merge" in path:
                key = "merge_prompt"
            elif "company" in path:
                key = "company_values"
            elif "education" in path:
                key = "education_plan"
                
            print(f"警告: ファイル {path} が見つからないためバックアップを使用します")
            return self._backup_prompts.get(key, "")
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"警告: ファイル読み込みエラー {path}: {e}")
            key = os.path.basename(path).replace(".md", "")
            return self._backup_prompts.get(key, "")
    
    # 残りのメソッドは変更なし
    def _get_file_mtime(self, path: str) -> float:
        if not path or not os.path.exists(path):
            return 0.0
        try:
            return os.path.getmtime(path)
        except Exception:
            return 0.0
    
    def _load_prompt(self, path: str, cache_key: str) -> str:
        current_mtime = self._get_file_mtime(path)
        cached_mtime = self._mtimes.get(cache_key, 0.0)
        
        if cache_key not in self._cache or current_mtime != cached_mtime:
            content = self._read_file(path)
            self._cache[cache_key] = content
            self._mtimes[cache_key] = current_mtime
        
        return self._cache[cache_key]
    
    def _substitute_placeholders(self, prompt: str) -> str:
        if "{{company_values}}" in prompt:
            company_values = self._load_prompt(
                self.company_values_path, "company_values"
            )
            prompt = prompt.replace("{{company_values}}", company_values)
        
        if "{{education_plan}}" in prompt:
            education_plan = self._load_prompt(
                self.education_plan_path, "education_plan"
            )
            prompt = prompt.replace("{{education_plan}}", education_plan)
        
        return prompt
    
    def get_analyze_prompt(self) -> str:
        prompt = self._load_prompt(self.analyze_prompt_path, "analyze_prompt")
        return self._substitute_placeholders(prompt)
    
    def get_merge_prompt(self) -> str:
        prompt = self._load_prompt(self.merge_prompt_path, "merge_prompt")
        return self._substitute_placeholders(prompt)
"""
PromptManager: Loads and hot-reloads external prompts from disk.

Features:
- Lazy-loads prompt files on first access
- Caches content and checks mtime for hot-reload
- Supports {{company_values}} and {{education_plan}} placeholder substitution
- No server restart needed when editing prompt files
"""

import os
from typing import Optional


class PromptManager:
    """
    Manages external prompt files with hot-reload capability.
    
    Loads prompts from Markdown files and supports placeholder substitution
    for {{company_values}} and {{education_plan}}.
    """
    
    def __init__(
        self,
        analyze_prompt_path: str = "prompts/analyze_system_prompt.md",
        merge_prompt_path: str = "prompts/merge_system_prompt.md",
        company_values_path: Optional[str] = "prompts/company_values.md",
        education_plan_path: Optional[str] = "prompts/education_plan.md",
    ):
        """
        Initialize PromptManager with paths to prompt files.
        
        Args:
            analyze_prompt_path: Path to the analysis system prompt
            merge_prompt_path: Path to the merge system prompt
            company_values_path: Optional path to company values content
            education_plan_path: Optional path to education plan content
        """
        self.analyze_prompt_path = analyze_prompt_path
        self.merge_prompt_path = merge_prompt_path
        self.company_values_path = company_values_path
        self.education_plan_path = education_plan_path
        
        # Cache for prompt contents and modification times
        self._cache = {}
        self._mtimes = {}
    
    def _read_file(self, path: str) -> str:
        """
        Read a file and return its contents.
        Returns empty string if file doesn't exist.
        """
        if not path or not os.path.exists(path):
            return ""
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Failed to read {path}: {e}")
            return ""
    
    def _get_file_mtime(self, path: str) -> float:
        """Get file modification time, returns 0 if file doesn't exist."""
        if not path or not os.path.exists(path):
            return 0.0
        try:
            return os.path.getmtime(path)
        except Exception:
            return 0.0
    
    def _load_prompt(self, path: str, cache_key: str) -> str:
        """
        Load a prompt file with caching and hot-reload support.
        
        Args:
            path: File path to load
            cache_key: Key for caching this prompt
            
        Returns:
            The prompt content as a string
        """
        current_mtime = self._get_file_mtime(path)
        cached_mtime = self._mtimes.get(cache_key, 0.0)
        
        # Check if we need to reload (file changed or not cached)
        if cache_key not in self._cache or current_mtime != cached_mtime:
            content = self._read_file(path)
            self._cache[cache_key] = content
            self._mtimes[cache_key] = current_mtime
        
        return self._cache[cache_key]
    
    def _substitute_placeholders(self, prompt: str) -> str:
        """
        Replace {{company_values}} and {{education_plan}} placeholders
        with content from respective files.
        """
        # Load company values if placeholder exists
        if "{{company_values}}" in prompt:
            company_values = self._load_prompt(
                self.company_values_path, "company_values"
            )
            prompt = prompt.replace("{{company_values}}", company_values)
        
        # Load education plan if placeholder exists
        if "{{education_plan}}" in prompt:
            education_plan = self._load_prompt(
                self.education_plan_path, "education_plan"
            )
            prompt = prompt.replace("{{education_plan}}", education_plan)
        
        return prompt
    
    def get_analyze_prompt(self) -> str:
        """
        Get the analysis system prompt with placeholders substituted.
        
        Returns:
            The complete analysis prompt ready to use
        """
        prompt = self._load_prompt(self.analyze_prompt_path, "analyze_prompt")
        return self._substitute_placeholders(prompt)
    
    def get_merge_prompt(self) -> str:
        """
        Get the merge system prompt with placeholders substituted.
        
        Returns:
            The complete merge prompt ready to use
        """
        prompt = self._load_prompt(self.merge_prompt_path, "merge_prompt")
        return self._substitute_placeholders(prompt)

あなたは複数の部分分析結果(JSON)を統合して、最終の単一JSONにまとめます。
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
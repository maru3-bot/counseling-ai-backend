import { useEffect, useState } from "react";
import axios from "axios";

// ローカル検証時は "http://localhost:8000" に変更してください
const API_BASE = "https://counseling-ai-backend.onrender.com";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});
  const [staff, setStaff] = useState("staffA");
  const [analysisMap, setAnalysisMap] = useState({});
  const [loadingMap, setLoadingMap] = useState({});

  // 動画一覧取得（スタッフごと）
  const fetchVideos = async (selectedStaff) => {
    try {
      const res = await axios.get(`${API_BASE}/list/${selectedStaff}`);
      setVideos(res.data.files || []);
    } catch (err) {
      console.error(err);
    }
  };

  // スタッフ選択変更時に再取得
  useEffect(() => {
    fetchVideos(staff);
  }, [staff]);

  // ファイルアップロード
  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      await axios.post(`${API_BASE}/upload/${staff}`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      alert("アップロード成功！");
      fetchVideos(staff);
    } catch (err) {
      console.error("アップロード失敗:", err);
      alert("アップロード失敗");
    }
  };

  // 署名付きURLを取得して再生
  const handlePlay = async (filename) => {
    try {
      const res = await axios.get(`${API_BASE}/signed-url/${staff}/${filename}`);
      setVideoUrls((prev) => ({
        ...prev,
        [filename]: res.data.url,
      }));
    } catch (err) {
      console.error("署名付きURLの取得エラー:", err);
    }
  };

  // 分析（サーバーで文字起こし→要約・採点）
  const handleAnalyze = async (filename, force = false) => {
    try {
      setLoadingMap((m) => ({ ...m, [filename]: true }));
      const res = await axios.post(
        `${API_BASE}/analyze/${staff}/${filename}?force=${force ? "true" : "false"}`
      );
      setAnalysisMap((prev) => ({
        ...prev,
        [filename]: res.data,
      }));
    } catch (err) {
      console.error("分析エラー:", err);
      alert("分析に失敗しました。しばらくしてから再度お試しください。");
    } finally {
      setLoadingMap((m) => ({ ...m, [filename]: false }));
    }
  };

  // 既存の分析結果を取得
  const handleFetchAnalysis = async (filename) => {
    try {
      const res = await axios.get(`${API_BASE}/analysis/${staff}/${filename}`);
      setAnalysisMap((prev) => ({ ...prev, [filename]: res.data }));
    } catch (err) {
      // まだ未分析なら404。何もしない。
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>スタッフ別アップロード＆閲覧 + AI分析</h1>

      {/* スタッフ選択 */}
      <label>
        スタッフを選択:{" "}
        <select value={staff} onChange={(e) => setStaff(e.target.value)}>
          <option value="staffA">staffA</option>
          <option value="staffB">staffB</option>
        </select>
      </label>

      <br />
      <br />
      <input type="file" onChange={handleFileChange} />

      <h2>{staff} の動画一覧</h2>
      {videos.map((v) => {
        const filename = v.name;
        const a = analysisMap[filename];
        const loading = loadingMap[filename];

        return (
          <div key={filename} style={{ marginBottom: "28px", textAlign: "left" }}>
            <p style={{ marginBottom: 8 }}>
              <strong>{filename}</strong>
            </p>
            <video
              width="360"
              height="240"
              controls
              src={videoUrls[filename] || null}
              style={{ display: "block", marginBottom: 8 }}
            />
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <button onClick={() => handlePlay(filename)}>▶ 再生する</button>
              <button onClick={() => handleFetchAnalysis(filename)}>📥 既存の分析を取得</button>
              <button onClick={() => handleAnalyze(filename)} disabled={loading}>
                {loading ? "分析中..." : "🔎 分析する"}
              </button>
              <button onClick={() => handleAnalyze(filename, true)} disabled={loading}>
                {loading ? "再分析中..." : "♻ 再分析（強制）"}
              </button>
            </div>

            {a && (
              <div
                style={{
                  border: "1px solid #ccc",
                  borderRadius: 8,
                  padding: 12,
                  background: "#f9f9f9",
                }}
              >
                <p style={{ margin: "4px 0" }}>
                  <strong>モデル:</strong> {a.model_name} ({a.model_mode})
                </p>
                <p style={{ margin: "4px 0" }}>
                  <strong>作成時刻:</strong> {new Date(a.created_at).toLocaleString()}
                </p>
                <p style={{ whiteSpace: "pre-wrap" }}>
                  <strong>要約:</strong> {a.analysis?.summary}
                </p>
                <div style={{ display: "flex", gap: 24, marginTop: 8 }}>
                  <div>
                    <strong>強み</strong>
                    <ul>
                      {(a.analysis?.strengths || []).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <strong>改善提案</strong>
                    <ul>
                      {(a.analysis?.improvements || []).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                {Array.isArray(a.analysis?.risk_flags) && a.analysis.risk_flags.length > 0 && (
                  <div>
                    <strong>リスク・注意点</strong>
                    <ul>
                      {a.analysis.risk_flags.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div style={{ marginTop: 8 }}>
                  <strong>スコア</strong>
                  <ul>
                    <li>共感: {a.analysis?.scores?.empathy}</li>
                    <li>傾聴: {a.analysis?.scores?.active_listening}</li>
                    <li>明確さ: {a.analysis?.scores?.clarity}</li>
                    <li>問題解決: {a.analysis?.scores?.problem_solving}</li>
                  </ul>
                </div>
                <p>
                  <strong>全体講評:</strong> {a.analysis?.overall_comment}
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default App;
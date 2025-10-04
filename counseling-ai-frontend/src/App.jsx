import { useEffect, useState } from "react";
import axios from "axios";
import "./App.css";

// APIの接続先（.env.local で VITE_API_BASE を設定。未設定ならローカルAPI）
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});
  const [staff, setStaff] = useState("staffA");

  // 分析結果: filename -> AnalyzeResponse
  const [analyses, setAnalyses] = useState({});
  // 状態表示
  const [loading, setLoading] = useState({}); // filename -> "playing" | "fetching" | "analyzing" | "reanalyzing" | "deleting"
  const [errors, setErrors] = useState({});   // filename -> message

  const setLoad = (name, state) => setLoading((prev) => ({ ...prev, [name]: state }));
  const clearLoad = (name) =>
    setLoading((prev) => {
      const cp = { ...prev };
      delete cp[name];
      return cp;
    });
  const setErr = (name, message) => setErrors((prev) => ({ ...prev, [name]: message }));
  const clearErr = (name) =>
    setErrors((prev) => {
      const cp = { ...prev };
      delete cp[name];
      return cp;
    });

  // スタッフの動画一覧
  const fetchVideos = async (selectedStaff) => {
    try {
      const res = await axios.get(`${API_BASE}/list/${selectedStaff}`);
      setVideos(res.data.files || []);
    } catch (err) {
      console.error("一覧取得エラー:", err);
      setVideos([]);
    }
  };

  // スタッフ変更時に一覧再取得＆状態クリア
  useEffect(() => {
    fetchVideos(staff);
    setVideoUrls({});
    setAnalyses({});
    setErrors({});
    setLoading({});
  }, [staff]);

  // アップロード
  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
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
      alert("アップロードに失敗しました。コンソールを確認してください。");
    }
  };

  // 再生URL取得
  const handlePlay = async (filename) => {
    clearErr(filename);
    setLoad(filename, "playing");
    try {
      const res = await axios.get(`${API_BASE}/signed-url/${staff}/${filename}`);
      setVideoUrls((prev) => ({ ...prev, [filename]: res.data.url }));
    } catch (err) {
      console.error("署名付きURLの取得エラー:", err);
      setErr(filename, "再生用URLの取得に失敗しました。");
    } finally {
      clearLoad(filename);
    }
  };

  // 既存の分析取得
  const handleFetchAnalysis = async (filename) => {
    clearErr(filename);
    setLoad(filename, "fetching");
    try {
      const res = await axios.get(`${API_BASE}/analysis/${staff}/${filename}`);
      setAnalyses((prev) => ({ ...prev, [filename]: res.data }));
    } catch (err) {
      console.error("既存分析の取得エラー:", err);
      setErr(filename, "既存の分析は見つかりませんでした。先に「分析する」を実行してください。");
    } finally {
      clearLoad(filename);
    }
  };

  // 分析（force=false/true）
  const handleAnalyze = async (filename, force = false) => {
    clearErr(filename);
    setLoad(filename, force ? "reanalyzing" : "analyzing");
    try {
      const url = `${API_BASE}/analyze/${staff}/${filename}${force ? "?force=true" : ""}`;
      const res = await axios.post(url);
      setAnalyses((prev) => ({ ...prev, [filename]: res.data }));
      // 再生URLが未取得なら合わせて取得
      if (!videoUrls[filename]) {
        const sres = await axios.get(`${API_BASE}/signed-url/${staff}/${filename}`);
        setVideoUrls((prev) => ({ ...prev, [filename]: sres.data.url }));
      }
    } catch (err) {
      console.error("分析エラー:", err);
      setErr(filename, "分析に失敗しました。サーバログ/OPENAI_API_KEY/ffmpegを確認してください。");
    } finally {
      clearLoad(filename);
    }
  };

  // 削除
  const handleDelete = async (filename) => {
    const yes = confirm(`${filename} を削除します。よろしいですか？`);
    if (!yes) return;
    clearErr(filename);
    setLoad(filename, "deleting");
    try {
      await axios.delete(`${API_BASE}/delete/${staff}/${filename}`);
      // 状態から除去
      setVideos((prev) => prev.filter((v) => v.name !== filename));
      setVideoUrls((prev) => {
        const cp = { ...prev };
        delete cp[filename];
        return cp;
      });
      setAnalyses((prev) => {
        const cp = { ...prev };
        delete cp[filename];
        return cp;
      });
    } catch (err) {
      console.error("削除エラー:", err);
      setErr(filename, "削除に失敗しました。権限やファイル名を確認してください。");
    } finally {
      clearLoad(filename);
    }
  };

  const renderAnalysis = (data) => {
    if (!data) return null;
    const { model_mode, model_name, analysis, created_at } = data;
    const a = analysis || {};
    const scores = a.scores || {};
    return (
      <div className="analysis-card" style={{ marginTop: 12 }}>
        <div style={{ marginBottom: 8 }}>
          <strong>モデル:</strong> {model_name} ({model_mode})　<strong>作成時刻:</strong> {created_at}
        </div>
        {a.summary && (
          <>
            <h4>要約</h4>
            <p>{a.summary}</p>
          </>
        )}
        {!!(a.strengths || []).length && (
          <>
            <h4>強み</h4>
            <ul>{a.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
          </>
        )}
        {!!(a.improvements || []).length && (
          <>
            <h4>改善提案</h4>
            <ul>{a.improvements.map((s, i) => <li key={i}>{s}</li>)}</ul>
          </>
        )}
        {!!(a.risk_flags || []).length && (
          <>
            <h4>リスク・注意点</h4>
            <ul>{a.risk_flags.map((s, i) => <li key={i}>{s}</li>)}</ul>
          </>
        )}
        {Object.keys(scores).length > 0 && (
          <>
            <h4>スコア</h4>
            <ul>
              {"empathy" in scores && <li>共感: {scores.empathy}</li>}
              {"active_listening" in scores && <li>傾聴: {scores.active_listening}</li>}
              {"clarity" in scores && <li>明確さ: {scores.clarity}</li>}
              {"problem_solving" in scores && <li>問題解決: {scores.problem_solving}</li>}
            </ul>
          </>
        )}
        {a.overall_comment && (
          <>
            <h4>全体講評</h4>
            <p>{a.overall_comment}</p>
          </>
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>スタッフ別アップロード＆閲覧</h1>

      {/* スタッフ選択 */}
      <label>
        スタッフを選択:{" "}
        <select value={staff} onChange={(e) => setStaff(e.target.value)}>
          <option value="staffA">staffA</option>
          <option value="staffB">staffB</option>
        </select>
      </label>

      <br /><br />
      <input type="file" onChange={handleFileChange} />

      <h2 style={{ marginTop: 24 }}>{staff} の動画一覧</h2>
      {videos.map((v) => {
        const name = v.name;
        const isLoading = loading[name];
        const err = errors[name];
        return (
          <div key={name} style={{ marginBottom: "24px" }}>
            <p style={{ marginBottom: 8 }}>{name}</p>
            <video
              width="320"
              height="240"
              controls
              src={videoUrls[name] || ""}
              style={{ background: "#000" }}
            />
            <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button onClick={() => handlePlay(name)} disabled={!!isLoading}>
                ▶ 再生する
              </button>
              <button onClick={() => handleFetchAnalysis(name)} disabled={!!isLoading}>
                既存の分析を取得
              </button>
              <button onClick={() => handleAnalyze(name, false)} disabled={!!isLoading}>
                分析する
              </button>
              <button onClick={() => handleAnalyze(name, true)} disabled={!!isLoading}>
                再分析（強制）
              </button>
              <button
                onClick={() => handleDelete(name)}
                disabled={!!isLoading}
                style={{ backgroundColor: "#b91c1c", color: "#fff" }}
              >
                削除
              </button>
            </div>
            {isLoading && <div style={{ marginTop: 6, color: "#666" }}>処理中: {isLoading}</div>}
            {err && <div style={{ marginTop: 6, color: "#b91c1c" }}>{err}</div>}
            {renderAnalysis(analyses[name])}
          </div>
        );
      })}
    </div>
  );
}

export default App;
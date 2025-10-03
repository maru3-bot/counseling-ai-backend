import { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});
  const [uploadProgress, setUploadProgress] = useState(0); // 追加
  const [message, setMessage] = useState(""); // 成功/失敗メッセージ

  useEffect(() => {
    fetchVideos();
  }, []);

  const fetchVideos = () => {
    axios.get("https://counseling-ai-backend.onrender.com/list")
      .then(res => setVideos(res.data.files))
      .catch(err => console.error(err));
  };

  const handleFileChange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  try {
    await axios.post(
      `https://counseling-ai-backend.onrender.com/upload/staffA`, // ← staff名を指定
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    );

    fetchVideos();
  } catch (err) {
    console.error("アップロード失敗:", err);
  }
};


  const handlePlay = async (filename) => {
    try {
      const res = await axios.get(
        `https://counseling-ai-backend.onrender.com/signed-url/${filename}`
      );
      setVideoUrls(prev => ({
        ...prev,
        [filename]: res.data.url,
      }));
    } catch (err) {
      console.error("署名付きURLの取得エラー:", err);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>アップロード動画一覧</h1>

      {/* ファイル選択 */}
      <input type="file" accept="video/*" onChange={handleFileChange} />

      {/* プログレスバー */}
      {uploadProgress > 0 && uploadProgress < 100 && (
        <div style={{ marginTop: "10px" }}>
          アップロード中... {uploadProgress}%
          <progress value={uploadProgress} max="100" />
        </div>
      )}

      {/* 成功/失敗メッセージ */}
      {message && <p>{message}</p>}

      {/* 動画一覧 */}
      {videos.map((v, i) => (
        <div key={i} style={{ marginBottom: "20px" }}>
          <p>{v.name} （{Math.round(v.metadata.size / 1024)} KB, {v.created_at}）</p>
          <video
            width="320"
            height="240"
            controls
            src={videoUrls[v.name] || ""}
          />
          <br />
          <button onClick={() => handlePlay(v.name)}>▶ 再生する</button>
        </div>
      ))}
    </div>
  );
}

export default App;

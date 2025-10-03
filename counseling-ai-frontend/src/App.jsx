import { useEffect, useState } from "react";
import axios from "axios";

const API_BASE = "https://counseling-ai-backend.onrender.com";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});

  // アップロード済みファイル一覧を取得
  useEffect(() => {
    fetchVideos();
  }, []);

  const fetchVideos = async () => {
    try {
      const res = await axios.get(`${API_BASE}/list`);
      // 新しい順にソート
      const sorted = res.data.files.sort(
        (a, b) => new Date(b.updated_at) - new Date(a.updated_at)
      );
      setVideos(sorted);
    } catch (err) {
      console.error(err);
    }
  };

  // 再生ボタンを押したときに署名付きURLを取得
  const handlePlay = async (filename) => {
    try {
      const res = await axios.get(`${API_BASE}/signed-url/${filename}`);
      setVideoUrls((prev) => ({
        ...prev,
        [filename]: res.data.url,
      }));
    } catch (err) {
      console.error("署名付きURLの取得エラー:", err);
    }
  };

  // 削除ボタンを押したとき
  const handleDelete = async (filename) => {
    if (!window.confirm(`${filename} を削除してもよろしいですか？`)) return;

    try {
      await axios.delete(`${API_BASE}/delete/${filename}`);
      setVideos((prev) => prev.filter((v) => v.name !== filename));
    } catch (err) {
      console.error("削除エラー:", err);
      alert("削除に失敗しました");
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>アップロード動画一覧</h1>
      {videos.map((v) => (
        <div key={v.id || v.name} style={{ marginBottom: "20px" }}>
          <p>{v.name}</p>

          <video
            width="320"
            height="240"
            controls
            src={videoUrls[v.name] || null}
          />

          <br />
          <button onClick={() => handlePlay(v.name)}>▶ 再生する</button>
          <button
            onClick={() => handleDelete(v.name)}
            style={{ marginLeft: "10px", color: "red" }}
          >
            🗑 削除
          </button>
        </div>
      ))}
    </div>
  );
}

export default App;

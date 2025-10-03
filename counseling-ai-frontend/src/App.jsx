import { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [staff, setStaff] = useState("staffA"); // デフォルトスタッフ

  // 📌 一覧取得（スタッフごと）
  const fetchVideos = async () => {
    try {
      const res = await axios.get(
        `https://counseling-ai-backend.onrender.com/list?prefix=${staff}/`
      );
      const files = res.data.files || [];
      // 新しい順に並べ替え
      const sorted = files.sort(
        (a, b) => new Date(b.updated_at) - new Date(a.updated_at)
      );
      setVideos(sorted);
    } catch (err) {
      console.error("一覧取得エラー:", err);
    }
  };

  useEffect(() => {
    fetchVideos();
  }, [staff]);

  // 📌 アップロード
  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    setUploading(true);
    try {
      await axios.post(
        `https://counseling-ai-backend.onrender.com/upload/${staff}`, // ← staff を渡す
        formData,
        {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (p) => {
            setProgress(Math.round((p.loaded * 100) / p.total));
          },
        }
      );

      setProgress(0);
      setUploading(false);
      fetchVideos();
    } catch (err) {
      console.error("アップロード失敗:", err);
      setUploading(false);
    }
  };

  // 📌 再生ボタンを押したときに署名付きURLを取得
  const handlePlay = async (filename) => {
    try {
      const res = await axios.get(
        `https://counseling-ai-backend.onrender.com/signed-url/${staff}/${filename}`
      );
      setVideoUrls((prev) => ({
        ...prev,
        [filename]: res.data.url,
      }));
    } catch (err) {
      console.error("署名付きURL取得エラー:", err);
    }
  };

  // 📌 削除（任意）
  const handleDelete = async (filename) => {
    if (!window.confirm(`${filename} を削除しますか？`)) return;
    try {
      await axios.delete(
        `https://counseling-ai-backend.onrender.com/delete/${staff}/${filename}`
      );
      fetchVideos();
    } catch (err) {
      console.error("削除失敗:", err);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>スタッフ別アップロード動画一覧</h1>

      {/* スタッフ切り替え */}
      <div style={{ marginBottom: "20px" }}>
        <label>スタッフ選択: </label>
        <select value={staff} onChange={(e) => setStaff(e.target.value)}>
          <option value="staffA">staffA</option>
          <option value="staffB">staffB</option>
          <option value="staffC">staffC</option>
        </select>
      </div>

      {/* アップロード */}
      <input type="file" accept="video/*" onChange={handleFileChange} />
      {uploading && <p>アップロード中... {progress}%</p>}

      {/* 一覧表示 */}
      <div style={{ marginTop: "20px" }}>
        {videos.map((v) => (
          <div key={v.name} style={{ marginBottom: "20px" }}>
            <p>{v.name}</p>

            <video
              width="240"
              height="160"
              controls
              src={videoUrls[v.name] || ""}
              poster="/zazalogo.png"
              style={{ borderRadius: "8px", background: "#fff" }}
            />

            <br />
            <button onClick={() => handlePlay(v.name)}>▶ 再生する</button>
            <button onClick={() => handleDelete(v.name)}>🗑 削除</button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;

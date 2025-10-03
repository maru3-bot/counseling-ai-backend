import { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});
  const [selectedFile, setSelectedFile] = useState(null);

  // 一覧取得
  const fetchVideos = () => {
    axios.get("https://counseling-ai-backend.onrender.com/list")
      .then(res => setVideos(res.data.files))
      .catch(err => console.error(err));
  };

  useEffect(() => {
    fetchVideos();
  }, []);

  // アップロード処理
  const handleUpload = async () => {
    if (!selectedFile) return alert("ファイルを選択してください");

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      await axios.post("https://counseling-ai-backend.onrender.com/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      alert("アップロード成功！");
      fetchVideos(); // 一覧を更新
    } catch (err) {
      console.error(err);
      alert("アップロード失敗");
    }
  };

  // 再生ボタンを押したとき署名付きURL取得
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

      {/* アップロードフォーム */}
      <input
        type="file"
        accept="video/mp4"
        onChange={(e) => setSelectedFile(e.target.files[0])}
      />
      <button onClick={handleUpload}>アップロード</button>

      <hr />

  {videos.map((v) => (
    <div key={v.id || v.name} style={{ marginBottom: "20px" }}>
      <p>{v.name}</p>

      <video
        width="320"
        height="240"
        controls
        src={videoUrls[v.name] || null}   // 空文字 "" ではなく null
      />

      <br />
        <button onClick={() => handlePlay(v.name)}>
        ▶ 再生する
        </button>
    </div>
))}

    </div>
  );
}

export default App;

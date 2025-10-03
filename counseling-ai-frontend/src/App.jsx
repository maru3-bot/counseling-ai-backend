import { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({}); // ファイルごとの署名付きURLを保存

  // アップロード済みファイル一覧を取得
  useEffect(() => {
    axios
      .get("https://counseling-ai-backend.onrender.com/list")
      .then((res) => {
        // .emptyFolderPlaceholder を除外
        const validFiles = res.data.files.filter(
          (f) => !f.filename.includes("emptyFolderPlaceholder")
        );
        setVideos(validFiles);
      })
      .catch((err) => console.error(err));
  }, []);

  // 再生ボタンを押したときに署名付きURLを取得
  const handlePlay = async (filename) => {
    try {
      const res = await axios.get(
        `https://counseling-ai-backend.onrender.com/signed-url/${filename}`
      );
      setVideoUrls((prev) => ({
        ...prev,
        [filename]: res.data.url, // filenameごとに署名URLを保存
      }));
    } catch (err) {
      console.error("署名付きURLの取得エラー:", err);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>アップロード動画一覧</h1>
      {videos.map((v) => (
        <div key={v.filename} style={{ marginBottom: "20px" }}>
          <p>{v.filename}</p>

          <video
            width="320"
            height="240"
            controls
            src={videoUrls[v.filename] || ""}
          />

          <br />
          <button onClick={() => handlePlay(v.filename)}>▶ 再生する</button>
        </div>
      ))}
    </div>
  );
}

export default App;

import { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [videos, setVideos] = useState([]);
  const [videoUrls, setVideoUrls] = useState({});
  const [staff, setStaff] = useState("staffA");

  // 動画一覧取得（スタッフごと）
  const fetchVideos = async (selectedStaff) => {
    try {
      const res = await axios.get(
        `https://counseling-ai-backend.onrender.com/list/${selectedStaff}`
      );
      setVideos(res.data.files);
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
      await axios.post(
        `https://counseling-ai-backend.onrender.com/upload/${staff}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      alert("アップロード成功！");
      fetchVideos(staff);
    } catch (err) {
      console.error("アップロード失敗:", err);
    }
  };

  // 再生ボタンを押したときに署名付きURLを取得
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
      console.error("署名付きURLの取得エラー:", err);
    }
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

      <h2>{staff} の動画一覧</h2>
      {videos.map((v) => (
        <div key={v.name} style={{ marginBottom: "20px" }}>
          <p>{v.name}</p>
          <video
            width="320"
            height="240"
            controls
            src={videoUrls[v.name] || null}
          />
          <br />
          <button onClick={() => handlePlay(v.name)}>▶ 再生する</button>
        </div>
      ))}
    </div>
  );
}

export default App;

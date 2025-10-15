import { useEffect, useState } from 'react';
import './App.css';

// 本番・開発環境に応じてAPIのURLを切り替えます
// .env.exampleと合わせてVITE_API_BASEを使用
const BASE_URL =
  import.meta.env.DEV
    ? "http://localhost:8000"
    : import.meta.env.VITE_API_BASE || "";

function App() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // 初回読み込み時にAPIからデータを取得
  useEffect(() => {
    // デバッグ用：API URLを表示
    console.log("使用API URL:", BASE_URL);
    
    if (!BASE_URL) {
      setError("API URLが設定されていません。環境変数VITE_API_BASEを確認してください。");
      setLoading(false);
      return;
    }

    fetch(`${BASE_URL}/list/staffA`)
      .then((res) => {
        if (!res.ok) {
          console.error("APIエラーステータス:", res.status);
          throw new Error(`ネットワークエラー: ${res.status} ${res.statusText}`);
        }
        return res.json();
      })
      .then((data) => {
        console.log("取得データ:", data);
        setData(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('API取得エラー:', err);
        setError(err.message);
        setLoading(false);
      });
  }, []);

  return (
    <div className="App">
      <h1>スタッフAの動画リスト</h1>

      {loading && <p>読み込み中...</p>}
      {error && (
        <div>
          <p style={{ color: 'red' }}>エラー: {error}</p>
          <p>API URL: {BASE_URL}</p>
        </div>
      )}

      {!loading && !error && (
        <ul>
          {data.length === 0 ? (
            <li>データがありません</li>
          ) : (
            data.map((item, index) => (
              <li key={index}>{item.name}</li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

export default App;
import { useEffect, useState } from 'react';
import './App.css';

// 本番・開発環境に応じてAPIのURLを切り替えます
const BASE_URL =
  import.meta.env.DEV
    ? "http://localhost:8000"
    : import.meta.env.VITE_API_BASE_URL;

function App() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // 初回読み込み時にAPIからデータを取得
  useEffect(() => {
    fetch(`${BASE_URL}/list/staffA`)
      .then((res) => {
        if (!res.ok) throw new Error('ネットワークエラー');
        return res.json();
      })
      .then((data) => {
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
      {error && <p style={{ color: 'red' }}>エラー: {error}</p>}

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

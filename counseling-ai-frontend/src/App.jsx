import { useState, useEffect, useRef } from 'react';
import './App.css';

// API URLの設定
const BASE_URL = 
  import.meta.env.DEV 
    ? "http://localhost:8000"
    : import.meta.env.VITE_API_BASE || "https://counseling-ai-backend.onrender.com";

function App() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const fileInputRef = useRef(null);

  // デバッグ情報
  console.log("環境変数:", {
    VITE_API_BASE: import.meta.env.VITE_API_BASE,
    使用URL: BASE_URL,
    開発モード: import.meta.env.DEV
  });

  // 動画リストの読み込み
  useEffect(() => {
    fetchVideos();
  }, []);

  // 動画一覧を取得する関数
  const fetchVideos = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${BASE_URL}/list/staffA`);
      if (!response.ok) throw new Error(`API エラー: ${response.status}`);
      
      const data = await response.json();
      setVideos(data);
      setError(null);
    } catch (err) {
      console.error('動画リスト取得エラー:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // 動画の署名付きURLを取得
  const getSignedUrl = async (filename) => {
    try {
      const response = await fetch(`${BASE_URL}/signed-url/staffA/${filename}`);
      if (!response.ok) throw new Error('URLの取得に失敗しました');
      const data = await response.json();
      return data.url;
    } catch (err) {
      console.error('署名付きURL取得エラー:', err);
      return null;
    }
  };

  // 動画を選択
  const handleVideoSelect = async (video) => {
    setSelectedVideo(video);
    // 分析結果をリセット
    setAnalysis(null);
  };

  // 保存済みの分析結果を取得
  const fetchSavedAnalysis = async (video) => {
    if (!video) return;
    
    try {
      setLoading(true);
      const response = await fetch(`${BASE_URL}/analysis/staffA/${video.name}`);
      if (response.ok) {
        const data = await response.json();
        setAnalysis(data);
        return true;
      } else if (response.status === 404) {
        setError(`${video.name}の分析結果が見つかりません。新たに分析を実行してください。`);
        return false;
      } else {
        throw new Error(`分析結果取得エラー: ${response.status}`);
      }
    } catch (err) {
      console.error('分析取得エラー:', err);
      setError(`分析結果取得中にエラーが発生しました: ${err.message}`);
      return false;
    } finally {
      setLoading(false);
    }
  };

  // 分析を実行
  const analyzeVideo = async (video) => {
    if (!video) return;
    
    setAnalyzing(true);
    setError(null);
    
    try {
      const response = await fetch(`${BASE_URL}/analyze/staffA/${video.name}`, {
        method: 'POST',
      });
      
      if (!response.ok) throw new Error('分析に失敗しました');
      
      const data = await response.json();
      setAnalysis(data);
    } catch (err) {
      console.error('分析実行エラー:', err);
      setError('分析中にエラーが発生しました: ' + err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  // 動画を削除
  const deleteVideo = async (video) => {
    if (!confirm(`${video.name} を削除してもよろしいですか？`)) return;
    
    try {
      const response = await fetch(`${BASE_URL}/delete/staffA/${video.name}`, {
        method: 'DELETE',
      });
      
      if (!response.ok) throw new Error('削除に失敗しました');
      
      // 成功したら動画リストを再読み込み
      fetchVideos();
      if (selectedVideo?.name === video.name) {
        setSelectedVideo(null);
        setAnalysis(null);
      }
    } catch (err) {
      console.error('削除エラー:', err);
      setError('削除中にエラーが発生しました: ' + err.message);
    }
  };

  // 動画再生用のURLを取得
  const playVideo = async (video) => {
    const url = await getSignedUrl(video.name);
    if (url) {
      window.open(url, '_blank');
    } else {
      setError('動画URLの取得に失敗しました');
    }
  };

  // ファイル選択ダイアログを開く
  const openFileDialog = () => {
    fileInputRef.current.click();
  };

  // 動画をアップロード
  const uploadVideo = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    // ファイルサイズチェック（50MBまで）
    const maxSize = 50 * 1024 * 1024; // 50MB
    if (file.size > maxSize) {
      setError(`ファイルサイズが大きすぎます（最大50MB）: ${(file.size / (1024 * 1024)).toFixed(1)}MB`);
      return;
    }
    
    setUploading(true);
    setUploadProgress(0);
    setError(null);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      // アップロード（進捗監視）
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/upload/staffA`, true);
      
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const progress = Math.round((event.loaded / event.total) * 100);
          setUploadProgress(progress);
        }
      };
      
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          // 成功時
          fetchVideos(); // リスト更新
          setUploadProgress(100);
          setTimeout(() => {
            setUploading(false);
            setUploadProgress(0);
          }, 1000);
        } else {
          // エラー時
          throw new Error(`アップロードエラー: ${xhr.statusText}`);
        }
      };
      
      xhr.onerror = () => {
        throw new Error('ネットワークエラーが発生しました');
      };
      
      xhr.send(formData);
    } catch (err) {
      console.error('アップロードエラー:', err);
      setError('アップロード中にエラーが発生しました: ' + err.message);
      setUploading(false);
    }
  };

  return (
    <div className="App">
      <header className="app-header">
        <h1>スタッフAの動画リスト</h1>
        
        {/* アップロードボタン */}
        <div className="upload-area">
          <input
            type="file"
            ref={fileInputRef}
            onChange={uploadVideo}
            accept="video/*"
            style={{ display: 'none' }}
          />
          <button
            className="btn btn-upload"
            onClick={openFileDialog}
            disabled={uploading}
          >
            動画をアップロード
          </button>
          
          {uploading && (
            <div className="upload-progress">
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${uploadProgress}%` }}
                ></div>
              </div>
              <span>{uploadProgress}%</span>
            </div>
          )}
        </div>
      </header>
      
      {error && <div className="error-banner">{error}</div>}
      
      <div className="container">
        {/* 左側: 動画リスト */}
        <div className="video-list">
          <div className="section-header">
            <h2>動画一覧</h2>
            {loading && <span className="loader">読み込み中...</span>}
          </div>

          {videos.length === 0 && !loading ? (
            <p className="empty-message">動画はありません</p>
          ) : (
            <ul className="videos">
              {videos.map((video, index) => (
                <li 
                  key={index} 
                  className={selectedVideo?.name === video.name ? 'selected' : ''}
                  onClick={() => handleVideoSelect(video)}
                >
                  <div className="video-item">
                    <span className="video-name">{video.name}</span>
                    <div className="video-actions">
                      {/* 各動画の操作ボタン */}
                      <button 
                        className="btn btn-play" 
                        onClick={(e) => {
                          e.stopPropagation();
                          playVideo(video);
                        }}
                        title="動画を再生"
                      >
                        再生
                      </button>
                      <button
                        className="btn btn-analyze"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleVideoSelect(video);
                          analyzeVideo(video);
                        }}
                        title="AIで分析する"
                      >
                        分析
                      </button>
                      <button 
                        className="btn btn-delete" 
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteVideo(video);
                        }}
                        title="動画を削除"
                      >
                        削除
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        
        {/* 右側: 選択した動画の詳細と分析結果 */}
        {selectedVideo ? (
          <div className="video-details">
            <div className="section-header">
              <h2>選択した動画: {selectedVideo.name}</h2>
            </div>
            
            <div className="actions">
              {/* 詳細画面のメイン操作ボタン */}
              <button className="btn btn-primary" onClick={() => playVideo(selectedVideo)}>
                動画を再生
              </button>
              <button 
                className={`btn ${analyzing ? 'btn-disabled' : 'btn-success'}`}
                onClick={() => analyzeVideo(selectedVideo)}
                disabled={analyzing}
              >
                {analyzing ? '分析中...' : '新規分析'}
              </button>
              {/* 保存済み分析結果呼び出しボタン（新規追加） */}
              <button 
                className="btn btn-secondary"
                onClick={() => fetchSavedAnalysis(selectedVideo)}
                disabled={analyzing}
              >
                保存済み分析を表示
              </button>
            </div>
            
            {/* 分析結果表示 */}
            {analysis && (
              <div className="analysis-card">
                <h3>分析結果</h3>
                
                <div className="analysis-section">
                  <h4>要約</h4>
                  <p>{analysis.summary}</p>
                </div>
                
                <div className="analysis-section">
                  <h4>良い点</h4>
                  <ul className="analysis-list">
                    {analysis.strengths.map((strength, i) => (
                      <li key={i}>{strength}</li>
                    ))}
                  </ul>
                </div>
                
                <div className="analysis-section">
                  <h4>改善点</h4>
                  <ul className="analysis-list">
                    {analysis.improvements.map((improvement, i) => (
                      <li key={i}>{improvement}</li>
                    ))}
                  </ul>
                </div>
                
                {analysis.risk_flags && analysis.risk_flags.length > 0 && (
                  <div className="analysis-section risks">
                    <h4>注意点・リスク</h4>
                    <ul className="analysis-list">
                      {analysis.risk_flags.map((risk, i) => (
                        <li key={i}>{risk}</li>
                      ))}
                    </ul>
                  </div>
                )}
                
                <div className="analysis-section">
                  <h4>スコア</h4>
                  <div className="scores-grid">
                    <div className="score-item">
                      <div className="score-label">共感力</div>
                      <div className="score-value">{analysis.scores.empathy}/5</div>
                    </div>
                    <div className="score-item">
                      <div className="score-label">傾聴力</div>
                      <div className="score-value">{analysis.scores.active_listening}/5</div>
                    </div>
                    <div className="score-item">
                      <div className="score-label">明確さ</div>
                      <div className="score-value">{analysis.scores.clarity}/5</div>
                    </div>
                    <div className="score-item">
                      <div className="score-label">問題解決力</div>
                      <div className="score-value">{analysis.scores.problem_solving}/5</div>
                    </div>
                  </div>
                </div>
                
                <div className="analysis-section">
                  <h4>総評</h4>
                  <p>{analysis.overall_comment}</p>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="video-details empty-selection">
            <p>左側のリストから動画を選択してください</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
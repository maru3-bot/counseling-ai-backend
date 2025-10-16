import { useState, useEffect, useRef, useMemo } from 'react';
import './App.css';

// API URL
const BASE_URL =
  import.meta.env.DEV
    ? 'http://localhost:8000'
    : import.meta.env.VITE_API_BASE || 'https://counseling-ai-backend.onrender.com';

function App() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [videoUrl, setVideoUrl] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // 分析進捗
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisMessage, setAnalysisMessage] = useState('');

  const fileInputRef = useRef(null);
  const videoPlayerRef = useRef(null);

  // デバッグ
  console.log('環境変数:', {
    VITE_API_BASE: import.meta.env.VITE_API_BASE,
    使用URL: BASE_URL,
    開発モード: import.meta.env.DEV,
  });

  // 初回動画一覧
  useEffect(() => {
    fetchVideos();
  }, []);

  const fetchVideos = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${BASE_URL}/list/staffA`);
      if (!res.ok) throw new Error(`API エラー: ${res.status}`);
      const data = await res.json();
      setVideos(data);
      setError(null);
    } catch (e) {
      console.error('動画リスト取得エラー:', e);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const getSignedUrl = async (filename) => {
    try {
      const res = await fetch(`${BASE_URL}/signed-url/staffA/${filename}`);
      if (!res.ok) throw new Error('URLの取得に失敗しました');
      const data = await res.json();
      return data.url;
    } catch (e) {
      console.error('署名付きURL取得エラー:', e);
      return null;
    }
  };

  const handleVideoSelect = (video) => {
    setSelectedVideo(video);
    setVideoUrl(null);
    setAnalysis(null);
  };

  const playVideo = async (video) => {
    if (!video) return;
    if (!videoUrl) {
      setLoading(true);
      const url = await getSignedUrl(video.name);
      setLoading(false);
      if (url) {
        setVideoUrl(url);
        setTimeout(() => {
          if (videoPlayerRef.current) {
            videoPlayerRef.current.scrollIntoView({ behavior: 'smooth' });
            videoPlayerRef.current.setAttribute('type', 'video/mp4');
            videoPlayerRef.current.play().catch((e) => {
              console.error('自動再生できませんでした:', e);
              setError('動画の自動再生に失敗しました。再生ボタンをクリックしてください。');
            });
          }
        }, 300);
      } else {
        setError('動画URLの取得に失敗しました');
      }
    } else {
      if (videoPlayerRef.current) {
        videoPlayerRef.current.scrollIntoView({ behavior: 'smooth' });
        if (videoPlayerRef.current.paused) {
          videoPlayerRef.current.play().catch((e) => {
            console.error('再生エラー:', e);
            setError('動画の再生に失敗しました。');
          });
        } else {
          videoPlayerRef.current.pause();
        }
      }
    }
  };

  const fetchSavedAnalysis = async (video) => {
    if (!video) return false;
    try {
      setLoading(true);
      const res = await fetch(`${BASE_URL}/analysis/staffA/${video.name}`);
      if (res.ok) {
        const data = await res.json();
        setAnalysis(data);
        setError(null);
        return true;
      } else if (res.status === 404) {
        setError(`${video.name}の分析結果が見つかりません。新たに分析を実行してください。`);
        return false;
      } else if (res.status === 202) {
        const body = await res.json();
        setError(body.detail?.message || '分析処理中です。しばらくお待ちください。');
        return false;
      } else {
        throw new Error(`分析結果取得エラー: ${res.status}`);
      }
    } catch (e) {
      console.error('分析取得エラー:', e);
      setError(`分析結果取得中にエラーが発生しました: ${e.message}`);
      return false;
    } finally {
      setLoading(false);
    }
  };

  // 分析（force 再分析も対応）
  const analyzeVideo = async (video, force = false) => {
    if (!video) return;
    setAnalyzing(true);
    setError(null);
    setAnalysisProgress(0);
    setAnalysisMessage('分析を開始しています...');

    try {
      const res = await fetch(`${BASE_URL}/analyze/staffA/${video.name}?force=${force}`, {
        method: 'POST',
      });
      const data = await res.json();

      if (res.ok && data && !data.status) {
        // 既存結果が即返ってきたケース
        setAnalysis(data);
        setAnalysisProgress(100);
        setAnalyzing(false);
      } else if (data.status === 'processing') {
        setAnalysisMessage('分析タスクを開始しました。進捗状況を確認しています...');
        pollAnalysisStatus(video.name);
      } else {
        throw new Error(data.message || '分析の開始に失敗しました');
      }
    } catch (e) {
      console.error('分析実行エラー:', e);
      setError('分析中にエラーが発生しました: ' + e.message);
      setAnalyzing(false);
    }
  };

  const pollAnalysisStatus = async (filename) => {
    let completed = false;
    let attempt = 0;
    const maxAttempts = 1800; // 30分

    while (!completed && attempt < maxAttempts) {
      try {
        const res = await fetch(`${BASE_URL}/task-status/staffA/${filename}`);
        if (res.ok) {
          const task = await res.json();
          const progress = Math.round((task.progress || 0) * 100);
          setAnalysisProgress(progress);
          setAnalysisMessage(task.message || `処理中... ${progress}%`);

          if (task.status === 'completed') {
            const aRes = await fetch(`${BASE_URL}/analysis/staffA/${filename}`);
            if (aRes.ok) {
              const analysisData = await aRes.json();
              setAnalysis(analysisData);
              completed = true;
              setAnalysisMessage('分析が完了しました');
            }
          } else if (task.status === 'error') {
            setError(`分析エラー: ${task.error || '不明なエラー'}`);
            completed = true;
          }
        } else if (res.status === 404) {
          // タスクなし → 直接結果確認
          const aRes = await fetch(`${BASE_URL}/analysis/staffA/${filename}`);
          if (aRes.ok) {
            const analysisData = await aRes.json();
            setAnalysis(analysisData);
            completed = true;
            setAnalysisMessage('分析が完了しました');
          } else {
            attempt++;
          }
        }
      } catch (e) {
        console.error('ステータス確認エラー:', e);
        attempt++;
      }

      if (!completed) {
        await new Promise((r) => setTimeout(r, 2000));
      }
    }

    setAnalyzing(false);
    if (!completed) {
      setError('分析がタイムアウトしました。後ほど結果を確認してください。');
    }
  };

  const deleteVideo = async (video) => {
    if (!confirm(`${video.name} を削除してもよろしいですか？`)) return;
    try {
      const res = await fetch(`${BASE_URL}/delete/staffA/${video.name}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('削除に失敗しました');
      fetchVideos();
      if (selectedVideo?.name === video.name) {
        setSelectedVideo(null);
        setVideoUrl(null);
        setAnalysis(null);
      }
    } catch (e) {
      console.error('削除エラー:', e);
      setError('削除中にエラーが発生しました: ' + e.message);
    }
  };

  const openFileDialog = () => fileInputRef.current?.click();

  const addTimestampToFilename = (filename) => {
    const now = new Date();
    const timestamp = now.toISOString().replace(/[-:]/g, '').replace('T', '_').replace(/\..+/, '');
    const lastDot = filename.lastIndexOf('.');
    if (lastDot === -1) return `${filename}_${timestamp}`;
    const name = filename.substring(0, lastDot);
    const ext = filename.substring(lastDot);
    return `${name}_${timestamp}${ext}`;
  };

  const uploadVideo = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // 1GBまで
    const maxSize = 1024 * 1024 * 1024;
    if (file.size > maxSize) {
      setError(`ファイルサイズが大きすぎます（最大1GB）: ${(file.size / (1024 * 1024)).toFixed(1)}MB`);
      return;
    }
    if (!file.type.startsWith('video/')) {
      setError(`サポートされていないファイルタイプです: ${file.type}。動画ファイルをアップロードしてください。`);
      return;
    }

    setUploading(true);
    setUploadProgress(0);
    setError(null);

    try {
      const newFileName = addTimestampToFilename(file.name);
      const renamedFile = new File([file], newFileName, { type: file.type });

      const formData = new FormData();
      formData.append('file', renamedFile);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/upload/staffA`, true);

      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          const progress = Math.round((ev.loaded / ev.total) * 100);
          setUploadProgress(progress);
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          fetchVideos();
          setUploadProgress(100);
          setTimeout(() => {
            setUploading(false);
            setUploadProgress(0);
          }, 1000);
        } else {
          throw new Error(`アップロードエラー: ${xhr.statusText}`);
        }
      };

      xhr.onerror = () => {
        throw new Error('ネットワークエラーが発生しました');
      };

      xhr.send(formData);
    } catch (e) {
      console.error('アップロードエラー:', e);
      setError('アップロード中にエラーが発生しました: ' + e.message);
      setUploading(false);
    }
  };

  // 受け取った分析結果を安全に描画できる形へ
  const safeAnalysis = useMemo(() => {
    if (!analysis || typeof analysis !== 'object') {
      return {
        summary: '',
        strengths: [],
        improvements: [],
        risk_flags: [],
        scores: { empathy: '-', active_listening: '-', clarity: '-', problem_solving: '-' },
        overall_comment: '',
      };
    }
    const strengths = Array.isArray(analysis.strengths) ? analysis.strengths : [];
    const improvements = Array.isArray(analysis.improvements) ? analysis.improvements : [];
    const riskFlags = Array.isArray(analysis.risk_flags) ? analysis.risk_flags : [];
    const scores = analysis.scores && typeof analysis.scores === 'object' ? analysis.scores : {};
    return {
      summary: analysis.summary ?? '',
      strengths,
      improvements,
      risk_flags: riskFlags,
      scores: {
        empathy: scores.empathy ?? '-',
        active_listening: scores.active_listening ?? '-',
        clarity: scores.clarity ?? '-',
        problem_solving: scores.problem_solving ?? '-',
      },
      overall_comment: analysis.overall_comment ?? '',
    };
  }, [analysis]);

  return (
    <div className="App">
      <header className="app-header">
        <h1>スタッフAの動画リスト</h1>

        <div className="upload-area">
          <input
            type="file"
            ref={fileInputRef}
            onChange={uploadVideo}
            accept="video/*"
            style={{ display: 'none' }}
          />
          <button className="btn btn-upload" onClick={openFileDialog} disabled={uploading}>
            動画をアップロード
          </button>

          {uploading && (
            <div className="upload-progress">
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${uploadProgress}%` }}></div>
              </div>
              <span>{uploadProgress}%</span>
            </div>
          )}
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="container">
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
                      <button
                        className="btn btn-play"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleVideoSelect(video);
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
                          analyzeVideo(video, false);
                        }}
                        title="AIで分析する"
                      >
                        分析
                      </button>
                      <button
                        className="btn btn-warning"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleVideoSelect(video);
                          analyzeVideo(video, true);
                        }}
                        title="保存済み分析を無視して強制的に再分析します"
                      >
                        強制再分析
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

        {selectedVideo ? (
          <div className="video-details">
            <div className="section-header">
              <h2>選択した動画: {selectedVideo.name}</h2>
            </div>

            {videoUrl && (
              <div className="video-player-container">
                <video
                  ref={videoPlayerRef}
                  className="video-player"
                  controls
                  src={videoUrl}
                  poster="/zazalogo.png"
                  type="video/mp4"
                  playsInline
                  onError={(e) => {
                    console.error('動画読み込みエラー:', e);
                    setError('動画の読み込みに失敗しました。フォーマットが正しくない可能性があります。');
                  }}
                >
                  お使いのブラウザは動画再生に対応していません
                </video>
              </div>
            )}

            <div className="actions">
              <button className="btn btn-primary" onClick={() => playVideo(selectedVideo)}>
                {videoUrl ? '再生/一時停止' : '動画を再生'}
              </button>
              <button
                className={`btn ${analyzing ? 'btn-disabled' : 'btn-success'}`}
                onClick={() => analyzeVideo(selectedVideo, false)}
                disabled={analyzing}
              >
                {analyzing ? '分析中...' : '新規分析'}
              </button>
              <button
                className={`btn ${analyzing ? 'btn-disabled' : 'btn-warning'}`}
                onClick={() => analyzeVideo(selectedVideo, true)}
                disabled={analyzing}
              >
                強制再分析
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => fetchSavedAnalysis(selectedVideo)}
                disabled={analyzing || loading}
              >
                保存済み分析を表示
              </button>
            </div>

            {analyzing && (
              <div className="analysis-progress-container">
                <div className="analysis-message">{analysisMessage}</div>
                <div className="progress-bar analysis-progress">
                  <div className="progress-fill" style={{ width: `${analysisProgress}%` }}></div>
                </div>
                <div className="progress-percentage">{analysisProgress}%</div>
              </div>
            )}

            {analysis && (
              <div className="analysis-card">
                <h3>分析結果</h3>

                <div className="analysis-section">
                  <h4>要約</h4>
                  <p>{safeAnalysis.summary}</p>
                </div>

                <div className="analysis-section">
                  <h4>良い点</h4>
                  <ul className="analysis-list">
                    {safeAnalysis.strengths.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>

                <div className="analysis-section">
                  <h4>改善点</h4>
                  <ul className="analysis-list">
                    {safeAnalysis.improvements.map((im, i) => (
                      <li key={i}>{im}</li>
                    ))}
                  </ul>
                </div>

                {safeAnalysis.risk_flags.length > 0 && (
                  <div className="analysis-section risks">
                    <h4>注意点・リスク</h4>
                    <ul className="analysis-list">
                      {safeAnalysis.risk_flags.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="analysis-section">
                  <h4>スコア</h4>
                  <div className="scores-grid">
                    <div className="score-item">
                      <div className="score-label">共感力</div>
                      <div className="score-value">{safeAnalysis.scores.empathy}/5</div>
                    </div>
                    <div className="score-item">
                      <div className="score-label">傾聴力</div>
                      <div className="score-value">{safeAnalysis.scores.active_listening}/5</div>
                    </div>
                    <div className="score-item">
                      <div className="score-label">明確さ</div>
                      <div className="score-value">{safeAnalysis.scores.clarity}/5</div>
                    </div>
                    <div className="score-item">
                      <div className="score-label">問題解決力</div>
                      <div className="score-value">{safeAnalysis.scores.problem_solving}/5</div>
                    </div>
                  </div>
                </div>

                <div className="analysis-section">
                  <h4>総評</h4>
                  <p>{safeAnalysis.overall_comment}</p>
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
import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";

const API = "http://localhost:8000";
const ALLOWED_EXTS = ["mp3", "mp4", "wav", "ogg", "m4a"];

export default function UploadPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState("file");
  const [fileId, setFileId] = useState(null);
  const [filename, setFilename] = useState(null);
  const [previewSrc, setPreviewSrc] = useState(null);
  const [hasPlayed, setHasPlayed] = useState(false);
  const [url, setUrl] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [speakers, setSpeakers] = useState([]);
  const [claimedSpeaker, setClaimedSpeaker] = useState("");
  const fileRef = useRef();

  useEffect(() => {
    fetch(`${API}/speakers`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setSpeakers)
      .catch(() => setSpeakers([]));
  }, []);

  function reset() {
    setFileId(null);
    setFilename(null);
    setPreviewSrc(null);
    setHasPlayed(false);
    setError(null);
  }

  async function handleFileChange(e) {
    const file = e.target.files[0];
    if (!file) return;
    reset();

    const ext = file.name.split(".").pop().toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      setError(`Unsupported format. Use: ${ALLOWED_EXTS.join(", ")}`);
      return;
    }
    if (file.size > 100 * 1024 * 1024) {
      setError("File exceeds 100 MB limit");
      return;
    }

    setPreviewSrc(URL.createObjectURL(file));

    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API}/upload`, { method: "POST", body: form });
      if (!res.ok) throw new Error((await res.json()).detail);
      const data = await res.json();
      setFileId(data.file_id);
      setFilename(data.filename);
    } catch (err) {
      setError(err.message);
      setPreviewSrc(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleUrlSubmit(e) {
    e.preventDefault();
    reset();
    if (!url.startsWith("https://")) {
      setError("URL must start with https://");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API}/ingest-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const data = await res.json();
      setFileId(data.file_id);
      setFilename(data.filename);
      setPreviewSrc(`${API}/preview/${data.file_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    setAnalyzing(true);
    setError(null);
    try {
      const res = await fetch(`${API}/analyze/${fileId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claimed_speaker_id: claimedSpeaker || null,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const data = await res.json();
      navigate(`/results/${data.analysis_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <div className="veritas-container">
      <h1>Veritas</h1>
      <p className="subtitle">AI Voice Authentication Platform</p>

      <div className="tabs">
        <button
          className={mode === "file" ? "active" : ""}
          onClick={() => { setMode("file"); reset(); }}
        >
          Upload File
        </button>
        <button
          className={mode === "url" ? "active" : ""}
          onClick={() => { setMode("url"); reset(); }}
        >
          Paste URL
        </button>
      </div>

      {mode === "file" && (
        <div className="upload-area" onClick={() => fileRef.current.click()}>
          <input
            ref={fileRef}
            type="file"
            accept="audio/*"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
          <p>Click to select an audio file</p>
          <p className="hint">MP3, MP4, WAV, OGG, M4A &mdash; max 100 MB</p>
        </div>
      )}

      {mode === "url" && (
        <form onSubmit={handleUrlSubmit} className="url-form">
          <input
            type="text"
            placeholder="https://youtube.com/..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button type="submit" disabled={loading || !url}>
            {loading ? "Extracting..." : "Load Audio"}
          </button>
        </form>
      )}

      {loading && <p className="status">Processing...</p>}
      {error && <p className="error">{error}</p>}

      {previewSrc && (
        <div className="preview">
          <p className="filename">{filename}</p>
          {speakers.length > 0 && (
            <div className="speaker-picker">
              <label htmlFor="claimed-speaker">
                Claimed speaker <span className="hint-inline">(optional)</span>
              </label>
              <select
                id="claimed-speaker"
                value={claimedSpeaker}
                onChange={(e) => setClaimedSpeaker(e.target.value)}
              >
                <option value="">— None —</option>
                {speakers.map((s) => (
                  <option key={s.speaker_id} value={s.speaker_id}>
                    {s.name}
                    {s.role ? ` — ${s.role}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <audio
            controls
            src={previewSrc}
            onPlay={() => setHasPlayed(true)}
            onPlaying={() => setHasPlayed(true)}
          />
          <button
            className="submit-btn"
            disabled={!hasPlayed || !fileId || analyzing}
            onClick={handleSubmit}
          >
            {analyzing
              ? "Analyzing..."
              : !hasPlayed
                ? "Play audio to enable submit"
                : "Submit for Analysis"}
          </button>
        </div>
      )}
    </div>
  );
}

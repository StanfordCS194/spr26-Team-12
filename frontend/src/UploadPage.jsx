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
  const [dragging, setDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null); // 0–100 or null

  const fileRef = useRef();
  const dragCounter = useRef(0); // tracks nested drag-enter/leave events

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
    setUploadProgress(null);
  }

  function validateFile(file) {
    const ext = file.name.split(".").pop().toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      setError(`Unsupported format. Allowed: ${ALLOWED_EXTS.join(", ")}`);
      return false;
    }
    if (file.size > 100 * 1024 * 1024) {
      setError("File exceeds 100 MB limit");
      return false;
    }
    return true;
  }

  function handleFile(file) {
    reset();
    if (!validateFile(file)) return;
    setPreviewSrc(URL.createObjectURL(file));
    uploadFileXHR(file);
  }

  /**
   * XHR-based upload so we can track real byte-level progress.
   */
  function uploadFileXHR(file) {
    setLoading(true);
    setUploadProgress(0);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/upload`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        setUploadProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      setLoading(false);
      setUploadProgress(null);
      if (xhr.status >= 200 && xhr.status < 300) {
        const data = JSON.parse(xhr.responseText);
        setFileId(data.file_id);
        setFilename(data.filename);
      } else {
        const detail =
          (JSON.parse(xhr.responseText) || {}).detail || "Upload failed";
        setError(detail);
        setPreviewSrc(null);
      }
    };

    xhr.onerror = () => {
      setLoading(false);
      setUploadProgress(null);
      setError("Upload failed — check your connection");
      setPreviewSrc(null);
    };

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  }

  // ── Drag-and-drop handlers ──────────────────────────────────────

  function handleDragEnter(e) {
    e.preventDefault();
    dragCounter.current += 1;
    setDragging(true);
  }

  function handleDragOver(e) {
    e.preventDefault(); // required to allow drop
  }

  function handleDragLeave(e) {
    e.preventDefault();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setDragging(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    dragCounter.current = 0;
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  // ── URL ingestion ───────────────────────────────────────────────

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

  // ── Analysis submission ─────────────────────────────────────────

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
          onClick={() => {
            setMode("file");
            reset();
            dragCounter.current = 0;
            setDragging(false);
          }}
        >
          Upload File
        </button>
        <button
          className={mode === "url" ? "active" : ""}
          onClick={() => {
            setMode("url");
            reset();
          }}
        >
          Paste URL
        </button>
      </div>

      {mode === "file" && (
        <>
          <div
            className={`upload-area${dragging ? " drag-over" : ""}`}
            onClick={() => fileRef.current.click()}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              ref={fileRef}
              type="file"
              accept="audio/*"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files[0];
                if (file) handleFile(file);
                e.target.value = ""; // reset so same file can be re-selected
              }}
            />
            {dragging ? (
              <p className="drag-label">Drop your audio file here</p>
            ) : (
              <>
                <p>Drag &amp; drop or click to select an audio file</p>
                <p className="hint">MP3, MP4, WAV, OGG, M4A &mdash; max 100 MB</p>
              </>
            )}
          </div>

          {uploadProgress !== null && (
            <div className="upload-progress-wrapper">
              <div
                className="upload-progress-bar"
                style={{ width: `${uploadProgress}%` }}
              />
              <span className="upload-progress-label">
                Uploading&hellip; {uploadProgress}%
              </span>
            </div>
          )}
        </>
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

      {/* Generic loading indicator for URL ingestion (no progress bar) */}
      {loading && uploadProgress === null && (
        <p className="status">Processing...</p>
      )}
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
              ? "Analyzing\u2026 (up to 45 s)"
              : !hasPlayed
              ? "Play audio to enable submit"
              : "Submit for Analysis"}
          </button>
        </div>
      )}
    </div>
  );
}

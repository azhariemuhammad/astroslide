import React, { useEffect, useRef, useState } from 'react';
import Slider from './Slider';
import { VIDEO_EXTENSIONS, isVideo } from '../utils/video';
import { cancelStack, cancelStackOnExit, getStackPreview, getStackResult, getStackStatus, startStack } from '../api/enhance';
import type { BayerPattern, StackUploadSession } from '../api/stackUpload';
import type { StackStatus } from '../types';
import '../styles/VideoStackPanel.css';

interface VideoStackPanelProps {
  clips: File[];
  onClipsChange: (clips: File[]) => void;
  // The stacked image, ready to open in the editor, the job's final status, and for a
  // FITS result, a JPEG to display it (null if unavailable)
  onStacked: (image: File, status: StackStatus, preview: string | null) => void;
  onCancel: () => void;
}

const DEFAULT_KEEP = 0.7;
const DEFAULT_SHARPEN = 0.5;
const POLL_MS = 1000;

const BAYER_OPTIONS: { value: BayerPattern; label: string }[] = [
  { value: 'auto', label: 'Detect automatically' },
  { value: 'GRBG', label: 'GRBG (Seestar)' },
  { value: 'RGGB', label: 'RGGB (most ZWO, Player One, Dwarf)' },
  { value: 'BGGR', label: 'BGGR' },
  { value: 'GBRG', label: 'GBRG' },
];

const formatSize = (bytes: number) =>
  bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;

// 75 s -> "1:15", 3725 s -> "1:02:05"
const formatElapsed = (seconds: number) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
};

type Phase =
  | { kind: 'setup' }
  | { kind: 'uploading'; progress: number }
  | { kind: 'stacking'; status: StackStatus }
  | { kind: 'error'; message: string };

// Upload is the first slice of the bar; stacking fills the rest
const UPLOAD_SHARE = 0.2;

const VideoStackPanel: React.FC<VideoStackPanelProps> = ({ clips, onClipsChange, onStacked, onCancel }) => {
  const [keep, setKeep] = useState(DEFAULT_KEEP);
  const [sharpen, setSharpen] = useState(DEFAULT_SHARPEN);
  const [bayer, setBayer] = useState<BayerPattern>('auto');
  const [phase, setPhase] = useState<Phase>({ kind: 'setup' });
  const addInput = useRef<HTMLInputElement>(null);
  // The current upload, so "Try again" after an interruption resumes it instead of
  // uploading everything again as a new job
  const session = useRef<StackUploadSession | null>(null);
  // The job being stacked once its upload is done, so it can be cancelled
  const job = useRef<string | null>(null);
  const upload = useRef<AbortController | null>(null);
  // Bumped to stop the current run: its upload and poll loop see it and quit
  const runId = useRef(0);

  // Stop the upload and tell the server to abandon the job: it would otherwise keep
  // stacking for nobody, holding the server and a job slot
  const stopJob = (onExit = false) => {
    runId.current++;
    upload.current?.abort();
    const jobId = job.current ?? session.current?.jobId;
    if (jobId) {
      if (onExit) cancelStackOnExit(jobId);
      else void cancelStack(jobId);
    }
    upload.current = null;
    job.current = null;
    session.current = null;
  };
  const stopJobRef = useRef(stopJob);
  stopJobRef.current = stopJob;

  // Unmounting mid-job (the panel replaced) abandons the job too (StrictMode's extra
  // unmount happens before any job starts, so it has nothing to stop)
  useEffect(() => () => stopJobRef.current(), []);

  const totalSize = clips.reduce((sum, clip) => sum + clip.size, 0);
  const working = phase.kind === 'uploading' || phase.kind === 'stacking';

  // Reloading or closing the tab mid-job loses the upload or the stacked result, so ask
  // first (browsers show their own generic wording, not a custom message)
  useEffect(() => {
    if (!working) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    // Left anyway: the page can't wait for a reply, but a beacon still reaches the server
    const leave = () => stopJobRef.current(true);
    window.addEventListener('beforeunload', warn);
    window.addEventListener('pagehide', leave);
    return () => {
      window.removeEventListener('beforeunload', warn);
      window.removeEventListener('pagehide', leave);
    };
  }, [working]);

  // Time since Stack was pressed, ticking once a second while the job runs
  const startedAt = useRef(0);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!working) return;
    const tick = () => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [working]);
  // Seestar records RAW as .avi and processed video as .mp4; the stacker can't mix them,
  // so say so before a long upload rather than after it
  const raw = clips.some(c => c.name.toLowerCase().endsWith('.avi'));
  const mixed = clips.some(c => c.name.toLowerCase().endsWith('.avi')) && clips.some(c => !c.name.toLowerCase().endsWith('.avi'));

  const addClips = (e: React.ChangeEvent<HTMLInputElement>) => {
    const added = Array.from(e.target.files ?? []).filter(isVideo);
    const known = new Set(clips.map(c => `${c.name}:${c.size}`));
    onClipsChange([...clips, ...added.filter(c => !known.has(`${c.name}:${c.size}`))]);
    e.target.value = '';
  };

  const run = async () => {
    const id = ++runId.current;
    const stopped = () => runId.current !== id;
    const controller = new AbortController();
    upload.current = controller;
    startedAt.current = Date.now();
    setPhase({ kind: 'uploading', progress: 0 });
    try {
      const jobId = await startStack(clips, {
        keep,
        sharpen,
        bayer: raw ? bayer : 'auto',
        signal: controller.signal,
        previous: session.current,
        onSession: started => { session.current = started; },
        onProgress: progress => {
          if (!stopped()) setPhase({ kind: 'uploading', progress });
        },
      });
      if (stopped()) return;
      // Uploaded and queued: a later attempt is a new job
      session.current = null;
      upload.current = null;
      job.current = jobId;
      for (;;) {
        await new Promise(resolve => setTimeout(resolve, POLL_MS));
        if (stopped()) return;
        const status = await getStackStatus(jobId);
        if (stopped()) return;
        if (status.state === 'error') throw new Error(status.message);
        if (status.state === 'cancelled') throw new Error('Stacking was cancelled.');
        setPhase({ kind: 'stacking', status });
        if (status.state === 'done' && status.result_file) {
          const [image, preview] = await Promise.all([
            getStackResult(jobId, status.result_file),
            status.preview_file ? getStackPreview(jobId) : null,
          ]);
          if (stopped()) return;
          job.current = null;
          onStacked(image, status, preview);
          return;
        }
      }
    } catch (err) {
      if (!stopped()) {
        job.current = null;
        setPhase({ kind: 'error', message: err instanceof Error ? err.message : 'Stacking failed' });
      }
    }
  };

  const stop = () => {
    stopJob();
    setPhase({ kind: 'setup' });
  };

  const progress = phase.kind === 'uploading'
    ? UPLOAD_SHARE * phase.progress
    : phase.kind === 'stacking'
      ? UPLOAD_SHARE + (1 - UPLOAD_SHARE) * phase.status.progress
      : 0;
  // The bar shows the whole job; the text shows how far the current step is
  const stage = phase.kind === 'uploading'
    ? `Uploading ${formatSize(totalSize * phase.progress)} of ${formatSize(totalSize)} · ${Math.round(phase.progress * 100)}%`
    : phase.kind === 'stacking'
      ? phase.status.state === 'running'
        ? `${phase.status.message} · ${Math.round(phase.status.progress * 100)}%`
        : phase.status.message
      : '';

  return (
    <div className="video-stack">
      <div className="video-stack-header">
        <h2 className="video-stack-title">Stack Moon video</h2>
        <p className="video-stack-intro">
          Every frame is checked for sharpness, aligned (including field rotation between clips and seeing
          wobble), and averaged into one low-noise 16-bit image that opens in the editor.
        </p>
      </div>

      <ul className="video-stack-clips">
        {clips.map((clip, i) => (
          <li key={`${clip.name}:${clip.size}`} className="video-stack-clip">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.55-2.28A1 1 0 0121 8.62v6.76a1 1 0 01-1.45.9L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <span className="video-stack-clip-name">{clip.name}</span>
            <span className="video-stack-clip-size">{formatSize(clip.size)}</span>
            {!working && (
              <button
                type="button"
                className="video-stack-remove"
                onClick={() => onClipsChange(clips.filter((_, j) => j !== i))}
                aria-label={`Remove ${clip.name}`}
              >
                ×
              </button>
            )}
          </li>
        ))}
      </ul>

      {!working && (
        <>
          <button type="button" className="video-stack-add" onClick={() => addInput.current?.click()}>
            + Add clips from the same night
          </button>
          <input
            ref={addInput}
            type="file"
            accept={VIDEO_EXTENSIONS.join(',')}
            multiple
            onChange={addClips}
            style={{ display: 'none' }}
          />
          <Slider
            label="Frames to keep"
            hint="Only the sharpest frames are stacked. A Seestar's frames differ little in sharpness, so keeping most of them gives the smoothest, lowest-noise result. Lower it on nights of unsteady seeing."
            value={keep}
            defaultValue={DEFAULT_KEEP}
            display={`${Math.round(keep * 100)}%`}
            min={0.1}
            max={1}
            step={0.05}
            onChange={setKeep}
          />
          <Slider
            label="Sharpening"
            hint="Deconvolution with the blur measured on the Moon's edge. 50% restores the detail the video really holds; higher looks crisper but starts to exaggerate edges. 0% leaves the stack soft for your own sharpening."
            value={sharpen}
            defaultValue={DEFAULT_SHARPEN}
            display={`${Math.round(sharpen * 100)}%`}
            min={0}
            max={1}
            step={0.05}
            onChange={setSharpen}
          />
          {raw && (
            <label className="video-stack-bayer">
              <span className="video-stack-bayer-label">Colour pattern</span>
              <select value={bayer} onChange={e => setBayer(e.target.value as BayerPattern)}>
                {BAYER_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <span className="video-stack-bayer-hint">
                Your camera's colour-filter layout. Leave it on Detect unless the stacked colours look wrong:
                red and blue swapped, a green or magenta tint, or a fine checkerboard.
              </span>
            </label>
          )}
        </>
      )}

      {working && (
        <div className="video-stack-progress" role="status" aria-live="polite">
          <div className="video-stack-bar">
            <div className="video-stack-bar-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          <div className="video-stack-stage">
            <span>{stage}</span>
            <span className="video-stack-elapsed">{formatElapsed(elapsed)}</span>
          </div>
        </div>
      )}

      {mixed && !working && (
        <p className="video-stack-error">
          RAW (.avi) and processed (.mp4) clips can't be stacked together. Remove one kind.
        </p>
      )}
      {phase.kind === 'error' && !mixed && <p className="video-stack-error">{phase.message}</p>}

      <div className="video-stack-actions">
        <button type="button" className="video-stack-cancel" onClick={working ? stop : onCancel}>
          Cancel
        </button>
        <button type="button" className="enhance-btn video-stack-start" onClick={run} disabled={working || mixed || clips.length === 0}>
          {working ? (
            <>
              <span className="btn-spinner"></span>
              <span>{phase.kind === 'uploading' ? 'Uploading…' : 'Stacking…'}</span>
            </>
          ) : (
            <span>{phase.kind === 'error' ? 'Try again' : `Stack ${clips.length} ${clips.length === 1 ? 'clip' : 'clips'}`}</span>
          )}
        </button>
      </div>
    </div>
  );
};

export default VideoStackPanel;

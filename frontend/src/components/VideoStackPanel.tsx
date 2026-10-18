import React, { useEffect, useRef, useState } from 'react';
import Slider from './Slider';
import { VIDEO_EXTENSIONS, isVideo } from '../utils/video';
import { getStackResult, getStackStatus, startStack } from '../api/enhance';
import type { StackStatus } from '../types';
import '../styles/VideoStackPanel.css';

interface VideoStackPanelProps {
  clips: File[];
  onClipsChange: (clips: File[]) => void;
  // The stacked image, ready to open in the editor, and the job's final status
  onStacked: (image: File, status: StackStatus) => void;
  onCancel: () => void;
}

const DEFAULT_KEEP = 0.7;
const POLL_MS = 1000;

const formatSize = (bytes: number) =>
  bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;

type Phase =
  | { kind: 'setup' }
  | { kind: 'uploading'; progress: number }
  | { kind: 'stacking'; status: StackStatus }
  | { kind: 'error'; message: string };

// Upload is the first slice of the bar; stacking fills the rest
const UPLOAD_SHARE = 0.2;

const VideoStackPanel: React.FC<VideoStackPanelProps> = ({ clips, onClipsChange, onStacked, onCancel }) => {
  const [keep, setKeep] = useState(DEFAULT_KEEP);
  const [phase, setPhase] = useState<Phase>({ kind: 'setup' });
  const addInput = useRef<HTMLInputElement>(null);
  // Set on unmount so a running poll loop stops touching state (reset on mount:
  // StrictMode mounts, unmounts and mounts again)
  const cancelled = useRef(false);
  useEffect(() => {
    cancelled.current = false;
    return () => { cancelled.current = true; };
  }, []);

  const totalSize = clips.reduce((sum, clip) => sum + clip.size, 0);
  const working = phase.kind === 'uploading' || phase.kind === 'stacking';
  // Seestar records RAW as .avi and processed video as .mp4; the stacker can't mix them,
  // so say so before a long upload rather than after it
  const mixed = clips.some(c => c.name.toLowerCase().endsWith('.avi')) && clips.some(c => !c.name.toLowerCase().endsWith('.avi'));

  const addClips = (e: React.ChangeEvent<HTMLInputElement>) => {
    const added = Array.from(e.target.files ?? []).filter(isVideo);
    const known = new Set(clips.map(c => `${c.name}:${c.size}`));
    onClipsChange([...clips, ...added.filter(c => !known.has(`${c.name}:${c.size}`))]);
    e.target.value = '';
  };

  const run = async () => {
    setPhase({ kind: 'uploading', progress: 0 });
    try {
      const jobId = await startStack(clips, keep, progress => {
        if (!cancelled.current) setPhase({ kind: 'uploading', progress });
      });
      for (;;) {
        await new Promise(resolve => setTimeout(resolve, POLL_MS));
        if (cancelled.current) return;
        const status = await getStackStatus(jobId);
        if (cancelled.current) return;
        if (status.state === 'error') throw new Error(status.message);
        setPhase({ kind: 'stacking', status });
        if (status.state === 'done' && status.result_file) {
          const image = await getStackResult(jobId, status.result_file);
          if (!cancelled.current) onStacked(image, status);
          return;
        }
      }
    } catch (err) {
      if (!cancelled.current) {
        setPhase({ kind: 'error', message: err instanceof Error ? err.message : 'Stacking failed' });
      }
    }
  };

  const progress = phase.kind === 'uploading'
    ? UPLOAD_SHARE * phase.progress
    : phase.kind === 'stacking'
      ? UPLOAD_SHARE + (1 - UPLOAD_SHARE) * phase.status.progress
      : 0;
  const stage = phase.kind === 'uploading'
    ? `Uploading ${formatSize(totalSize * phase.progress)} of ${formatSize(totalSize)}`
    : phase.kind === 'stacking'
      ? phase.status.message
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
        </>
      )}

      {working && (
        <div className="video-stack-progress" role="status" aria-live="polite">
          <div className="video-stack-bar">
            <div className="video-stack-bar-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          <div className="video-stack-stage">
            <span>{stage}</span>
            <span>{Math.round(progress * 100)}%</span>
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
        <button type="button" className="video-stack-cancel" onClick={onCancel} disabled={working}>
          Cancel
        </button>
        <button type="button" className="enhance-btn video-stack-start" onClick={run} disabled={working || mixed || clips.length === 0}>
          {working ? (
            <>
              <span className="btn-spinner"></span>
              <span>Stacking…</span>
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

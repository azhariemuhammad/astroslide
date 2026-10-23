import React, { useRef, useState } from 'react';
import Slider from './Slider';
import type { CompositeSettings } from '../utils/composite';
import '../styles/CompositeControls.css';

type SliderKey = 'size' | 'glow' | 'glowSize' | 'brightness' | 'darkness';

interface CompositeControlsProps {
  starName: string | null;
  starLoading: boolean;
  onStarFile: (file: File) => void;
  settings: CompositeSettings;
  defaults: CompositeSettings;
  onChange: (key: SliderKey, value: number) => void;
  // Moon size at the same pixel scale as the stars (same telescope); null until both are loaded
  trueSize: number | null;
  // No processed Moon on screen yet: the composite uses the original
  unprocessed: boolean;
  // The sliders, until both photos are in; picking a star photo is always possible
  disabled?: boolean;
}

const STAR_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.fits', '.fit'];
const MAX_FILE_SIZE = 50 * 1024 * 1024;

const percent = (v: number) => `${Math.round(v * 100)}%`;

const SLIDERS: { key: SliderKey; label: string; hint: string; min: number; max: number }[] = [
  { key: 'size', label: 'Moon size', min: 0.03, max: 0.9,
    hint: 'Moon diameter as a share of the picture. "True size" matches the stars when both photos come from the same telescope.' },
  { key: 'glow', label: 'Glow', min: 0, max: 1,
    hint: 'Moonlight scattered by the air around the Moon, strongest beside its lit edge.' },
  { key: 'glowSize', label: 'Glow size', min: 0, max: 1,
    hint: 'How far the glow spreads, like a brush size: small hugs the lit edge, large is a wide, soft halo (it can reach round the dark side).' },
  { key: 'brightness', label: 'Moon brightness', min: 0.3, max: 1,
    hint: 'Dim the Moon to balance it against the stars.' },
  { key: 'darkness', label: 'Sky darkness', min: 0, max: 1,
    hint: 'Darkens the star photo\'s sky. Light pollution and the gradient are already removed; this sets how black the sky is.' },
];

// The "Add stars" tab: pick a star photo, then a few sliders; the Moon is placed by dragging it
const CompositeControls: React.FC<CompositeControlsProps> = ({
  starName, starLoading, onStarFile, settings, defaults, onChange, trueSize, unprocessed, disabled = false,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    if (!STAR_EXTENSIONS.some(ext => file.name.toLowerCase().endsWith(ext))) {
      setError('Choose a photo: JPEG, PNG, TIFF or FITS');
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      setError(`File too large. Maximum size is 50MB, this one is ${(file.size / 1024 / 1024).toFixed(1)}MB`);
      return;
    }
    setError(null);
    onStarFile(file);
  };

  const input = (
    <input
      ref={inputRef}
      type="file"
      accept={STAR_EXTENSIONS.join(',')}
      onChange={(e) => { pick(e.target.files); e.target.value = ''; }}
      style={{ display: 'none' }}
    />
  );

  if (!starName) {
    return (
      <div className="composite-controls">
        <p className="composite-intro">
          Put your Moon on a star field. The sky's glow is cleaned up and the stars behind the Moon,
          its dark side too, are hidden automatically.
        </p>
        {input}
        <button
          type="button"
          className={`composite-drop ${dragging ? 'dragging' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files); }}
          disabled={starLoading}
        >
          {starLoading ? (
            <>
              <span className="btn-spinner" />
              <span className="composite-drop-title">Cleaning up the sky…</span>
            </>
          ) : (
            <>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="26" height="26" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 3l1.9 4.6L19 8.3l-3.8 3.4 1.1 5L12 14.1 7.7 16.7l1.1-5L5 8.3l5.1-.7z" />
              </svg>
              <span className="composite-drop-title">Add a star photo</span>
              <span className="composite-drop-hint">A Seestar stack or any night-sky shot · JPEG, PNG, TIFF, FITS</span>
            </>
          )}
        </button>
        {error && <p className="composite-error">{error}</p>}
        <p className="composite-tip">
          Best match: stars from the same night, near where the Moon was, taken with the same telescope.
        </p>
      </div>
    );
  }

  return (
    <div className="composite-controls">
      {input}
      <div className="composite-file">
        <span className="composite-file-name" title={starName}>{starName}</span>
        <button
          type="button"
          className="composite-file-change"
          onClick={() => inputRef.current?.click()}
          disabled={starLoading}
        >
          {starLoading ? 'Opening…' : 'Change'}
        </button>
      </div>
      {error && <p className="composite-error">{error}</p>}
      {unprocessed && (
        <p className="composite-tip">Tip: enhance the Moon in Presets first. The composite uses whatever is on screen.</p>
      )}

      <section className="mineral-moon-group" aria-label="Composite">
        {SLIDERS.map(({ key, label, hint, min, max }) => (
          <Slider
            key={key}
            label={label}
            hint={hint}
            value={settings[key]}
            defaultValue={defaults[key]}
            display={percent(settings[key])}
            min={min}
            max={max}
            step={0.01}
            disabled={disabled}
            onChange={(v) => onChange(key, v)}
          />
        ))}
        {trueSize !== null && Math.abs(settings.size - trueSize) > 0.005 && trueSize >= 0.03 && trueSize <= 0.9 && (
          <button type="button" className="composite-true-size" onClick={() => onChange('size', trueSize)} disabled={disabled}>
            Use true size (same telescope)
          </button>
        )}
      </section>

      <p className="composite-tip">
        Drag the Moon in the picture to place it. The download's file name says "composite", so viewers know two photos were combined.
      </p>
    </div>
  );
};

export default CompositeControls;

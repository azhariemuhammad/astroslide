import React, { useId, useState } from 'react';
import '../styles/Slider.css';

interface SliderProps {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  // Explanation shown under the label when the (i) button is pressed
  hint?: string;
  // When set, a reset button appears once the value differs; double-click also resets
  defaultValue?: number;
  onChange: (value: number) => void;
}

// Where the filled part of the track starts and ends, in percent. A range that spans
// zero (like Warmth) fills from the centre, so -25 reads as "slightly cool"
const fillRange = (value: number, min: number, max: number) => {
  const pct = (v: number) => ((v - min) / (max - min)) * 100;
  const origin = min < 0 && max > 0 ? pct(0) : 0;
  const at = pct(value);
  return { from: Math.min(origin, at), to: Math.max(origin, at) };
};

// Labelled range input: label and value on one line, full-width track below
const Slider: React.FC<SliderProps> = ({ label, value, display, min, max, step, disabled = false, hint, defaultValue, onChange }) => {
  const [showHint, setShowHint] = useState(false);
  const id = useId();
  const fill = fillRange(value, min, max);
  const changed = defaultValue !== undefined && Math.abs(value - defaultValue) > step / 2;
  const reset = () => {
    if (defaultValue !== undefined && !disabled) onChange(defaultValue);
  };

  return (
    <div className="control-group">
      <div className="control-header">
        <label htmlFor={id}>{label}</label>
        {hint && (
          <button
            type="button"
            className={`control-icon-btn control-info ${showHint ? 'active' : ''}`}
            onClick={() => setShowHint(s => !s)}
            aria-label={`About ${label}`}
            aria-expanded={showHint}
            aria-controls={`${id}-hint`}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="14" height="14">
              <circle cx="12" cy="12" r="9" strokeWidth={2} />
              <path strokeLinecap="round" strokeWidth={2} d="M12 11v5M12 8h.01" />
            </svg>
          </button>
        )}
        <span className="control-spacer" />
        {changed && (
          <button
            type="button"
            className="control-icon-btn control-reset"
            onClick={reset}
            disabled={disabled}
            title="Reset to default (or double-click the slider)"
            aria-label={`Reset ${label}`}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="13" height="13">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h5M4.6 15a8 8 0 101.9-8.4L4 9" />
            </svg>
          </button>
        )}
        <span className="value">{display}</span>
      </div>
      {hint && showHint && <p className="control-hint" id={`${id}-hint`}>{hint}</p>}
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        onDoubleClick={reset}
        disabled={disabled}
        style={{ '--fill-from': `${fill.from}%`, '--fill-to': `${fill.to}%` } as React.CSSProperties}
      />
    </div>
  );
};

export default Slider;

import React from 'react';
import '../styles/Slider.css';

interface SliderProps {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  title?: string;
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
const Slider: React.FC<SliderProps> = ({ label, value, display, min, max, step, disabled = false, title, onChange }) => {
  const fill = fillRange(value, min, max);
  return (
    <div className="control-group" title={title}>
      <label>
        <span>{label}</span>
        <span className="value">{display}</span>
      </label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        disabled={disabled}
        style={{ '--fill-from': `${fill.from}%`, '--fill-to': `${fill.to}%` } as React.CSSProperties}
      />
    </div>
  );
};

export default Slider;

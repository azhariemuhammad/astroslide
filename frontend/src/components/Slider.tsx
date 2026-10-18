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

// Labelled range input: label and value on one line, full-width track below
const Slider: React.FC<SliderProps> = ({ label, value, display, min, max, step, disabled = false, title, onChange }) => (
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
    />
  </div>
);

export default Slider;

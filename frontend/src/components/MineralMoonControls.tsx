import React from 'react';
import Slider from './Slider';
import '../styles/MineralMoonControls.css';

export interface MineralMoonSettings {
  intensity: number; // colour strength
  warmth: number;    // -1 (cool / silver-blue) .. 1 (warm / bronze)
  sharpen: number;
  hdr: number;
  halo: number;
}

interface MineralMoonControlsProps {
  settings: MineralMoonSettings;
  onChange: (key: keyof MineralMoonSettings, value: number) => void;
  disabled?: boolean;
}

const percent = (v: number) => `${Math.round(v * 100)}%`;
const signedPercent = (v: number) => (v > 0 ? `+${Math.round(v * 100)}` : `${Math.round(v * 100)}`);

const SLIDERS: {
  key: keyof MineralMoonSettings;
  label: string;
  title: string;
  min: number;
  format: (v: number) => string;
}[] = [
  { key: 'intensity', label: 'Color', min: 0, format: percent,
    title: 'How strongly the blue (titanium) and orange (iron) mineral colours are shown' },
  { key: 'warmth', label: 'Warmth', min: -1, format: signedPercent,
    title: 'Colour balance: lower keeps the moon silver-blue, higher turns the maria bronze' },
  { key: 'sharpen', label: 'Sharpen', min: 0, format: percent,
    title: 'Multi-scale detail sharpening of the surface (colour is not affected)' },
  { key: 'hdr', label: 'HDR', min: 0, format: percent,
    title: 'Local tone mapping: evens out bright and dark areas and lifts surface detail' },
  { key: 'halo', label: 'Halo', min: 0, format: percent,
    title: 'Soft glow around the moon' },
];

// Mineral Moon adjustments: each slider controls one thing, so they can be tuned independently
const MineralMoonControls: React.FC<MineralMoonControlsProps> = ({ settings, onChange, disabled = false }) => (
  <div className="mineral-moon-controls">
    <h3 className="mineral-moon-title">Mineral Moon</h3>
    {SLIDERS.map(({ key, label, title, min, format }) => (
      <Slider
        key={key}
        label={label}
        title={title}
        value={settings[key]}
        display={format(settings[key])}
        min={min}
        max={1}
        step={0.01}
        disabled={disabled}
        onChange={(v) => onChange(key, v)}
      />
    ))}
    <p className="mineral-moon-hint">Adjust, then press Enhance.</p>
  </div>
);

export default MineralMoonControls;

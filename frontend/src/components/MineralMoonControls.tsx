import React from 'react';
import Slider from './Slider';
import '../styles/MineralMoonControls.css';

export interface MineralMoonSettings {
  intensity: number; // colour strength
  warmth: number;    // -1 (cool / silver-blue) .. 1 (warm / bronze)
  deconvolve: number;
  sharpen: number;
  hdr: number;
  halo: number;
}

interface MineralMoonControlsProps {
  settings: MineralMoonSettings;
  defaults: MineralMoonSettings;
  onChange: (key: keyof MineralMoonSettings, value: number) => void;
  onReset: () => void;
  notes?: string[];
  disabled?: boolean;
}

const percent = (v: number) => `${Math.round(v * 100)}%`;
const signedPercent = (v: number) => (v > 0 ? `+${Math.round(v * 100)}` : `${Math.round(v * 100)}`);

interface SliderSpec {
  key: keyof MineralMoonSettings;
  label: string;
  hint: string;
  min: number;
  format: (v: number) => string;
}

const GROUPS: { title: string; sliders: SliderSpec[] }[] = [
  {
    title: 'Color',
    sliders: [
      { key: 'intensity', label: 'Strength', min: 0, format: percent,
        hint: 'How strongly the blue (titanium) and orange (iron) mineral colours are shown.' },
      { key: 'warmth', label: 'Warmth', min: -1, format: signedPercent,
        hint: 'Colour balance: lower keeps the moon silver-blue, higher turns the maria bronze.' },
    ],
  },
  {
    title: 'Detail',
    sliders: [
      { key: 'deconvolve', label: 'Deblur', min: 0, format: percent,
        hint: 'Deconvolution: undoes the blur from seeing and optics, measured from the edge of the moon (like BlurXTerminator).' },
      { key: 'sharpen', label: 'Sharpen', min: 0, format: percent,
        hint: 'Multi-scale sharpening of surface detail. Colour is not affected.' },
    ],
  },
  {
    title: 'Tone',
    sliders: [
      { key: 'hdr', label: 'HDR', min: 0, format: percent,
        hint: 'Local tone mapping: evens out bright and dark areas and lifts surface detail.' },
      { key: 'halo', label: 'Halo', min: 0, format: percent,
        hint: 'Soft glow around the moon.' },
    ],
  },
];

const KEYS = GROUPS.flatMap(g => g.sliders.map(s => s.key));

// Mineral Moon adjustments, grouped by what they change; each slider controls one thing
const MineralMoonControls: React.FC<MineralMoonControlsProps> = ({ settings, defaults, onChange, onReset, notes = [], disabled = false }) => {
  const changed = KEYS.some(key => Math.abs(settings[key] - defaults[key]) > 0.005);

  return (
    <div className="mineral-moon-controls">
      <div className="mineral-moon-header">
        <h3 className="mineral-moon-title">Adjustments</h3>
        {changed && (
          <button type="button" className="mineral-moon-reset" onClick={onReset} disabled={disabled}>
            Reset all
          </button>
        )}
      </div>
      {notes.length > 0 && (
        <ul className="mineral-moon-notes">
          {notes.map(note => <li key={note}>{note}</li>)}
        </ul>
      )}
      {GROUPS.map(group => (
        <section key={group.title} className="mineral-moon-group" aria-label={group.title}>
          <h4 className="mineral-moon-group-title">{group.title}</h4>
          {group.sliders.map(({ key, label, hint, min, format }) => (
            <Slider
              key={key}
              label={label}
              hint={hint}
              value={settings[key]}
              defaultValue={defaults[key]}
              display={format(settings[key])}
              min={min}
              max={1}
              step={0.01}
              disabled={disabled}
              onChange={(v) => onChange(key, v)}
            />
          ))}
        </section>
      ))}
    </div>
  );
};

export default MineralMoonControls;

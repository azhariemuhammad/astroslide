import Slider from './Slider';
import '../styles/ProModeControls.css';

export interface ProModeSettings {
  denoiseStrength: number;
  starReduction: number;
  saturationBoost: number;
  sharpening: number;
}

interface ProModeControlsProps {
  settings: ProModeSettings;
  defaults: ProModeSettings;
  onSettingsChange: (settings: ProModeSettings) => void;
  disabled?: boolean;
}

const SLIDERS: { key: keyof ProModeSettings; label: string; max: number; hint: string }[] = [
  { key: 'denoiseStrength', label: 'Denoise', max: 1,
    hint: 'Smooths grain and sensor noise. High values soften fine detail.' },
  { key: 'starReduction', label: 'Star Reduction', max: 1,
    hint: 'Shrinks stars so nebulae and galaxies stand out.' },
  { key: 'saturationBoost', label: 'Saturation', max: 2,
    hint: 'Colour intensity. 100% leaves colours unchanged.' },
  { key: 'sharpening', label: 'Sharpening', max: 1,
    hint: 'Extra sharpening applied after the preset.' },
];

export default function ProModeControls({ 
  settings, 
  defaults,
  onSettingsChange, 
  disabled = false 
}: ProModeControlsProps) {
  return (
    <div className="pro-mode-controls">
      {SLIDERS.map(({ key, label, max, hint }) => (
        <Slider
          key={key}
          label={label}
          hint={hint}
          defaultValue={defaults[key]}
          value={settings[key]}
          display={`${Math.round(settings[key] * 100)}%`}
          min={0}
          max={max}
          step={0.01}
          disabled={disabled}
          onChange={(v) => onSettingsChange({ ...settings, [key]: v })}
        />
      ))}
    </div>
  );
}

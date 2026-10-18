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
  onSettingsChange: (settings: ProModeSettings) => void;
  disabled?: boolean;
}

const SLIDERS: { key: keyof ProModeSettings; label: string; max: number }[] = [
  { key: 'denoiseStrength', label: 'Denoise', max: 1 },
  { key: 'starReduction', label: 'Star Reduction', max: 1 },
  { key: 'saturationBoost', label: 'Saturation', max: 2 },
  { key: 'sharpening', label: 'Sharpening', max: 1 },
];

export default function ProModeControls({ 
  settings, 
  onSettingsChange, 
  disabled = false 
}: ProModeControlsProps) {
  return (
    <div className="pro-mode-controls">
      {SLIDERS.map(({ key, label, max }) => (
        <Slider
          key={key}
          label={label}
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

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

export default function ProModeControls({ 
  settings, 
  onSettingsChange, 
  disabled = false 
}: ProModeControlsProps) {
  
  const handleChange = (key: keyof ProModeSettings, value: number) => {
    onSettingsChange({
      ...settings,
      [key]: value
    });
  };

  return (
    <div className="pro-mode-controls">
      <div className="pro-control-group">
        <label className="pro-control-label">
          <span className="pro-control-name">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="14" height="14">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            Denoise
          </span>
          <span className="pro-control-value">{Math.round(settings.denoiseStrength * 100)}%</span>
        </label>
        <input
          type="range"
          min="0"
          max="100"
          value={settings.denoiseStrength * 100}
          onChange={(e) => handleChange('denoiseStrength', Number(e.target.value) / 100)}
          className="pro-slider"
          disabled={disabled}
        />
      </div>

      <div className="pro-control-group">
        <label className="pro-control-label">
          <span className="pro-control-name">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="14" height="14">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
            Star Reduction
          </span>
          <span className="pro-control-value">{Math.round(settings.starReduction * 100)}%</span>
        </label>
        <input
          type="range"
          min="0"
          max="100"
          value={settings.starReduction * 100}
          onChange={(e) => handleChange('starReduction', Number(e.target.value) / 100)}
          className="pro-slider"
          disabled={disabled}
        />
      </div>

      <div className="pro-control-group">
        <label className="pro-control-label">
          <span className="pro-control-name">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="14" height="14">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
            </svg>
            Saturation
          </span>
          <span className="pro-control-value">{Math.round(settings.saturationBoost * 100)}%</span>
        </label>
        <input
          type="range"
          min="0"
          max="200"
          value={settings.saturationBoost * 100}
          onChange={(e) => handleChange('saturationBoost', Number(e.target.value) / 100)}
          className="pro-slider"
          disabled={disabled}
        />
      </div>

      <div className="pro-control-group">
        <label className="pro-control-label">
          <span className="pro-control-name">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="14" height="14">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            Sharpening
          </span>
          <span className="pro-control-value">{Math.round(settings.sharpening * 100)}%</span>
        </label>
        <input
          type="range"
          min="0"
          max="100"
          value={settings.sharpening * 100}
          onChange={(e) => handleChange('sharpening', Number(e.target.value) / 100)}
          className="pro-slider"
          disabled={disabled}
        />
      </div>
    </div>
  );
}

import React from 'react';
import type { Preset, PresetType } from '../types';
import '../styles/PresetSelector.css';

interface PresetSelectorProps {
  presets: Preset[];
  selectedPreset: PresetType;
  onPresetChange: (preset: PresetType) => void;
  disabled?: boolean;
}

const PresetSelector: React.FC<PresetSelectorProps> = ({
  presets,
  selectedPreset,
  onPresetChange,
  disabled = false,
}) => {
  return (
    <div className="preset-selector">
      <div className="preset-list">
        {presets.map((preset) => (
          <button
            key={preset.id}
            className={`preset-item ${selectedPreset === preset.id ? 'selected' : ''} ${disabled ? 'disabled' : ''}`}
            onClick={() => !disabled && onPresetChange(preset.id)}
            disabled={disabled}
            data-preset={preset.id}
          >
            <div className="preset-item-content">
              <span className="preset-item-name">{preset.name}</span>
              <span className="preset-item-desc">{preset.description}</span>
            </div>
            <svg className="preset-item-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
};

export default PresetSelector;

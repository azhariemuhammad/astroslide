import React, { useState, useRef, useEffect } from 'react';
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
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedPresetData = presets.find(p => p.id === selectedPreset);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const handleSelect = (presetId: PresetType) => {
    onPresetChange(presetId);
    setIsOpen(false);
  };

  return (
    <div className="preset-selector-dropdown" ref={dropdownRef}>
      <button
        className={`preset-dropdown-trigger ${isOpen ? 'open' : ''} ${disabled ? 'disabled' : ''}`}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
      >
        <div className="preset-trigger-content">
          <span className="preset-trigger-label">Preset:</span>
          <span className="preset-trigger-value">{selectedPresetData?.name || 'Select'}</span>
        </div>
        <svg 
          className="preset-trigger-icon" 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          width="16" 
          height="16"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="preset-dropdown-menu">
          {presets.map((preset) => (
            <button
              key={preset.id}
              className={`preset-dropdown-item ${selectedPreset === preset.id ? 'selected' : ''}`}
              onClick={() => handleSelect(preset.id)}
            >
              <div className="preset-dropdown-item-content">
                <span className="preset-dropdown-item-name">{preset.name}</span>
                <span className="preset-dropdown-item-desc">{preset.description}</span>
              </div>
              {selectedPreset === preset.id && (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default PresetSelector;

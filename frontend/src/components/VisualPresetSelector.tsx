import { useState, useRef, useEffect } from 'react';
import type { Preset, PresetType } from '../types';
import '../styles/VisualPresetSelector.css';

interface VisualPresetSelectorProps {
  presets: Preset[];
  selectedPreset: string;
  onPresetChange: (presetId: PresetType) => void;
  currentFile: File | null;
  disabled?: boolean;
}

export default function VisualPresetSelector({
  presets,
  selectedPreset,
  onPresetChange,
  disabled = false
}: VisualPresetSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  const selectedPresetObj = presets.find(p => p.id === selectedPreset);

  useEffect(() => {
    function handleClickOutside(event: PointerEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('pointerdown', handleClickOutside);
    return () => {
      document.removeEventListener('pointerdown', handleClickOutside);
    };
  }, []);

  const handleSelect = (presetId: PresetType) => {
    if (!disabled) {
      onPresetChange(presetId);
      setIsOpen(false);
    }
  };

  return (
    <div className="visual-preset-selector">
      <h3 className="preset-selector-title">Preset</h3>
      <div className="preset-dropdown-container">
        <div className={`custom-select-wrapper ${isOpen ? 'open' : ''} ${disabled ? 'disabled' : ''}`} ref={dropdownRef}>
          <button
            type="button"
            className="custom-select-trigger"
            onClick={() => setIsOpen(!isOpen)}
            disabled={disabled}
            aria-haspopup="listbox"
            aria-expanded={isOpen}
          >
            <span className="selected-value">{selectedPresetObj?.name || 'Select Preset'}</span>
            <svg 
              className={`select-arrow ${isOpen ? 'open' : ''}`} 
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
            <div className="custom-select-options">
              {presets.map((preset) => (
                <div 
                  key={preset.id} 
                  className={`custom-option ${selectedPreset === preset.id ? 'selected' : ''}`}
                  onClick={() => handleSelect(preset.id as PresetType)}
                >
                  <div className="option-content">
                    <span className="option-name">{preset.name}</span>
                    <span className="option-badge">{preset.best_for}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        
        {selectedPresetObj && (
          <p className="preset-description">{selectedPresetObj.description}</p>
        )}
      </div>
    </div>
  );
}

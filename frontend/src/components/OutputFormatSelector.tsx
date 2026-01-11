import type { OutputFormatOption, OutputFormat } from '../types';
import '../styles/OutputFormatSelector.css';

interface OutputFormatSelectorProps {
  formats: OutputFormatOption[];
  selectedFormat: OutputFormat;
  onFormatChange: (format: OutputFormat) => void;
  disabled?: boolean;
}

function OutputFormatSelector({ 
  formats, 
  selectedFormat, 
  onFormatChange, 
  disabled = false 
}: OutputFormatSelectorProps) {
  return (
    <div className="output-format-selector">
      <span className="format-label">Format:</span>
      <div className="format-options">
        {formats.map((format) => (
          <button
            key={format.id}
            className={`format-option ${selectedFormat === format.id ? 'selected' : ''}`}
            onClick={() => onFormatChange(format.id)}
            disabled={disabled}
            title={format.description}
          >
            <span className="format-name">{format.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default OutputFormatSelector;

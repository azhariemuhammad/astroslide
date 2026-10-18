import React from 'react';
import type { StretchParams } from '../types';
import Slider from './Slider';
import '../styles/InteractiveStretchPanel.css';

interface InteractiveStretchPanelProps {
  params: StretchParams;
  onParamsChange: (params: StretchParams) => void;
  onAutoStretch?: () => void;
  isAutoStretching?: boolean;
  disabled?: boolean;
}

const InteractiveStretchPanel: React.FC<InteractiveStretchPanelProps> = ({
  params,
  onParamsChange,
  onAutoStretch,
  isAutoStretching = false,
  disabled = false
}) => {
  const update = <K extends keyof StretchParams>(key: K, value: StretchParams[K]) => {
    onParamsChange({ ...params, [key]: value });
  };

  return (
    <div className="interactive-stretch-panel">
      <div className="panel-section">
        {onAutoStretch && (
          <button
            type="button"
            className="auto-stretch-btn"
            onClick={onAutoStretch}
            disabled={disabled || isAutoStretching}
            title="Set shadows and midtones automatically from the background level (like PixInsight's AutoSTF)"
          >
            {isAutoStretching ? 'Calculating…' : 'Auto Stretch'}
          </button>
        )}
        <Slider
          label="Shadows (Black Point)"
          value={params.shadows}
          display={params.shadows.toFixed(3)}
          min={0}
          max={0.5}
          step={0.001}
          disabled={disabled}
          onChange={(v) => update('shadows', v)}
        />
        <Slider
          label="Midtones (Stretch)"
          value={params.midtones}
          display={params.midtones.toFixed(3)}
          min={0.001}
          max={0.999}
          step={0.001}
          disabled={disabled}
          onChange={(v) => update('midtones', v)}
        />
        <Slider
          label="Highlights (White Point)"
          value={params.highlights}
          display={params.highlights.toFixed(3)}
          min={0.5}
          max={1.0}
          step={0.001}
          disabled={disabled}
          onChange={(v) => update('highlights', v)}
        />
      </div>

      <div className="panel-divider" />

      <div className="panel-section">
        <div className="control-group checkbox-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={params.remove_stars}
              onChange={(e) => update('remove_stars', e.target.checked)}
              disabled={disabled}
            />
            <span>Remove Stars (Starless)</span>
          </label>
        </div>

        {params.remove_stars && (
          <>
            <Slider
              label="Star Sensitivity"
              value={params.star_sensitivity}
              display={params.star_sensitivity.toFixed(2)}
              min={0.1}
              max={1.0}
              step={0.05}
              disabled={disabled}
              onChange={(v) => update('star_sensitivity', v)}
            />
            <Slider
              label="Halo Mask Size"
              value={params.inpaint_radius}
              display={`${params.inpaint_radius}px`}
              min={1}
              max={20}
              step={1}
              disabled={disabled}
              onChange={(v) => update('inpaint_radius', Math.round(v))}
            />
          </>
        )}
      </div>
    </div>
  );
};

export default InteractiveStretchPanel;

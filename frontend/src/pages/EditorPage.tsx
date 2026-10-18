import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import FileUpload from '../components/FileUpload';
import ImageViewer from '../components/ImageViewer';
import Histogram from '../components/Histogram';
import VisualPresetSelector from '../components/VisualPresetSelector';
import ProModeControls, { type ProModeSettings } from '../components/ProModeControls';
import OutputFormatSelector from '../components/OutputFormatSelector';
import { 
  enhanceImage, 
  getPresets,
  getOutputFormats, 
  calculateHistogram,
  interactiveStretch,
  getStretchPreview,
  getAutoStf
} from '../api/enhance';
import { computeHistogramFromUrl } from '../utils/histogram';
import type { PresetType, OutputFormat, HistogramData, StretchParams } from '../types';
import InteractiveStretchPanel from '../components/InteractiveStretchPanel';
import MineralMoonControls from '../components/MineralMoonControls';
import { useHistory } from '../hooks/useHistory';

// Consolidated state types
interface ImageState {
  original: string | null;
  enhanced: string | null;
  currentFile: File | null;
  fileName: string;
  dimensions: { width: number; height: number } | null;
  outputExtension: string;
}

interface UIState {
  isLoading: boolean;
  error: string | null;
  showProMode: boolean;
  showHistogram: boolean;
  sidebarTab: 'presets' | 'interactive';
}

interface SelectionState {
  preset: PresetType;
  format: OutputFormat;
  intensity: number;
  halo: number;
  hdr: number;
  sharpen: number;
  warmth: number;
  deconvolve: number;
}

// One undo step: the result on screen plus every setting that produced it
interface Snapshot {
  label: string;
  image: string | null;
  outputExtension: string;
  sidebarTab: UIState['sidebarTab'];
  selection: SelectionState;
  proMode: ProModeSettings;
  stretch: StretchParams;
}

const DEFAULT_SELECTION: SelectionState = { preset: 'mineral_moon', format: 'jpeg', intensity: 0.75, halo: 0.2, hdr: 0.25, sharpen: 0.3, warmth: -0.25, deconvolve: 0.4 };

// Neutral defaults: opening Pro Mode doesn't change the result until a slider moves
const DEFAULT_PRO_MODE: ProModeSettings = {
  denoiseStrength: 0,
  starReduction: 0,
  saturationBoost: 1.0,
  sharpening: 0,
};

const DEFAULT_STRETCH: StretchParams = {
  shadows: 0.0,
  midtones: 0.5,
  highlights: 1.0,
  remove_stars: false,
  star_sensitivity: 0.5,
  inpaint_radius: 5,
};

// Identifies the stretch inputs behind a rendered result
const stretchKey = (params: StretchParams, format: OutputFormat) => JSON.stringify([params, format]);

export default function EditorPage() {
  // Consolidated state objects
  const [imageState, setImageState] = useState<ImageState>({
    original: null,
    enhanced: null,
    currentFile: null,
    fileName: '',
    dimensions: null,
    outputExtension: 'jpg',
  });

  const [uiState, setUIState] = useState<UIState>({
    isLoading: false,
    error: null,
    showProMode: false,
    showHistogram: true,
    sidebarTab: 'presets',
  });

  const [selectionState, setSelectionState] = useState<SelectionState>(DEFAULT_SELECTION);
  const [proModeSettings, setProModeSettings] = useState<ProModeSettings>(DEFAULT_PRO_MODE);
  const [stretchParams, setStretchParams] = useState<StretchParams>(DEFAULT_STRETCH);

  const [histogramData, setHistogramData] = useState<HistogramData | null>(null);
  // Feedback on the capture from the last Mineral Moon run (exposure, measured blur)
  const [moonNotes, setMoonNotes] = useState<string[]>([]);
  const [isAutoStretching, setIsAutoStretching] = useState(false);

  const history = useHistory<Snapshot>();
  // Stretch inputs whose result is already on screen (or restored from history),
  // so the stretch effect doesn't re-render it and wipe the redo stack
  const renderedStretchKey = useRef<string | null>(null);

  const snapshot = (label: string, image: string | null, outputExtension: string, overrides: Partial<Snapshot> = {}): Snapshot => ({
    label,
    image,
    outputExtension,
    sidebarTab: uiState.sidebarTab,
    selection: selectionState,
    proMode: proModeSettings,
    stretch: stretchParams,
    ...overrides,
  });

  // Lets the stretch effect's async callback snapshot the latest settings, not stale ones
  const snapshotRef = useRef(snapshot);
  useEffect(() => {
    snapshotRef.current = snapshot;
  });
  const pushHistory = history.push;

  const restore = (entry: Snapshot | undefined) => {
    if (!entry) return;
    // A restored stretch result is already on screen; a preset result isn't a stretch,
    // so opening the Interactive tab afterwards should render one
    renderedStretchKey.current = entry.sidebarTab === 'interactive'
      ? stretchKey(entry.stretch, entry.selection.format)
      : null;
    setImageState(prev => ({ ...prev, enhanced: entry.image, outputExtension: entry.outputExtension }));
    setSelectionState(entry.selection);
    setProModeSettings(entry.proMode);
    setStretchParams(entry.stretch);
    setUIState(prev => ({ ...prev, sidebarTab: entry.sidebarTab, error: null }));
  };

  const handleUndo = () => restore(history.undo());
  const handleRedo = () => restore(history.redo());

  const handleRevert = () => {
    const original = snapshot('Revert to original', null, 'jpg', {
      selection: { ...DEFAULT_SELECTION, format: selectionState.format },
      proMode: DEFAULT_PRO_MODE,
      stretch: DEFAULT_STRETCH,
    });
    history.push(original);
    restore(original);
  };

  // Fetch presets using TanStack Query
  const { data: presets = [] } = useQuery({
    queryKey: ['presets'],
    queryFn: getPresets,
    select: (response) => response.presets,
  });

  // Fetch output formats using TanStack Query
  const { data: outputFormats = [] } = useQuery({
    queryKey: ['outputFormats'],
    queryFn: getOutputFormats,
    select: (response) => response.formats,
  });

  const handleFileSelect = (file: File) => {
    setUIState(prev => ({ ...prev, error: null }));
    
    const originalUrl = URL.createObjectURL(file);
    
    const loadImage = (dimensions: ImageState['dimensions']) => {
      setImageState({
        original: originalUrl,
        enhanced: null,
        currentFile: file,
        fileName: file.name,
        dimensions,
        outputExtension: 'jpg',
      });
    };
    const img = new Image();
    img.onload = () => loadImage({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = async () => {
      // Browsers can't display FITS (or most TIFF): load the file anyway and show a
      // backend-rendered, unstretched JPEG of the original in its place
      loadImage(null);
      try {
        const { preview_image } = await getStretchPreview(file, DEFAULT_STRETCH);
        setImageState(prev => (prev.currentFile === file ? { ...prev, original: preview_image } : prev));
      } catch (err) {
        setUIState(prev => ({ ...prev, error: err instanceof Error ? err.message : 'Could not preview this file' }));
      }
    };
    img.src = originalUrl;

    renderedStretchKey.current = null;
    setMoonNotes([]);
    history.reset(snapshot('Original', null, 'jpg'));
  };

  const handleEnhance = async () => {
    if (!imageState.currentFile) return;
    const presetName = presets.find(p => p.id === selectionState.preset)?.name ?? 'Enhance';
    
    setUIState(prev => ({ ...prev, error: null, isLoading: true }));

    try {
      const response = await enhanceImage(
        imageState.currentFile,
        selectionState.preset,
        selectionState.format,
        selectionState.intensity,
        {
          halo: selectionState.halo,
          hdr: selectionState.hdr,
          sharpen: selectionState.sharpen,
          warmth: selectionState.warmth,
          deconvolve: selectionState.deconvolve,
          ...(uiState.showProMode
            ? {
                denoise: proModeSettings.denoiseStrength,
                starReduction: proModeSettings.starReduction,
                saturation: proModeSettings.saturationBoost,
                sharpening: proModeSettings.sharpening,
              }
            : {}),
        },
      );
      const outputExtension = response.output_extension || 'jpg';
      setImageState(prev => ({
        ...prev,
        enhanced: response.enhanced_image,
        outputExtension,
      }));
      setMoonNotes(response.notes ?? []);
      renderedStretchKey.current = null;
      history.push(snapshot(presetName, response.enhanced_image, outputExtension));
    } catch (err) {
      setUIState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Failed to enhance image',
      }));
    } finally {
      setUIState(prev => ({ ...prev, isLoading: false }));
    }
  };

  const handlePresetChange = (preset: PresetType) => {
    setSelectionState(prev => ({ ...prev, preset }));
  };

  const handleIntensityChange = (intensity: number) => {
    setSelectionState(prev => ({ ...prev, intensity }));
  };

  const handleFormatChange = (format: OutputFormat) => {
    setSelectionState(prev => ({ ...prev, format }));
  };

  // Interactive stretch: quick low-res preview, then a full-res render once sliders settle.
  // Both are debounced, and responses that arrive after the params changed are dropped,
  // so a stale or low-res response can never overwrite a newer result.
  useEffect(() => {
    if (!imageState.currentFile || uiState.sidebarTab !== 'interactive') return;
    const key = stretchKey(stretchParams, selectionState.format);
    if (key === renderedStretchKey.current) return;

    const file = imageState.currentFile;
    let cancelled = false;
    let fullApplied = false;

    const previewTimer = setTimeout(async () => {
      try {
        const response = await getStretchPreview(file, stretchParams);
        if (!cancelled && !fullApplied) {
          setImageState(prev => ({ ...prev, enhanced: response.preview_image }));
        }
      } catch (err) {
        console.error('Fast preview failed:', err);
      }
    }, 120);

    const fullTimer = setTimeout(async () => {
      try {
        const response = await interactiveStretch(file, stretchParams, selectionState.format);
        if (!cancelled) {
          fullApplied = true;
          const outputExtension = selectionState.format === 'jpeg' ? 'jpg' : selectionState.format;
          setImageState(prev => ({ ...prev, enhanced: response.enhanced_image, outputExtension }));
          renderedStretchKey.current = key;
          pushHistory(snapshotRef.current('Stretch', response.enhanced_image, outputExtension));
        }
      } catch (err) {
        if (!cancelled) {
          setUIState(prev => ({
            ...prev,
            error: err instanceof Error ? err.message : 'Stretch failed',
          }));
        }
      }
    }, 500);

    return () => {
      clearTimeout(previewTimer);
      clearTimeout(fullTimer);
      // Drop in-flight responses (params changed, tab switched, or new file)
      cancelled = true;
    };
  }, [stretchParams, uiState.sidebarTab, selectionState.format, imageState.currentFile, pushHistory]);

  const handleAutoStretch = async () => {
    if (!imageState.currentFile) return;
    setIsAutoStretching(true);
    try {
      const stf = await getAutoStf(imageState.currentFile);
      setStretchParams(prev => ({
        ...prev,
        shadows: stf.shadows,
        midtones: stf.midtones,
        highlights: stf.highlights,
      }));
    } catch (err) {
      setUIState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Auto stretch failed',
      }));
    } finally {
      setIsAutoStretching(false);
    }
  };

  const handleDownload = () => {
    if (!imageState.enhanced) return;

    const link = document.createElement('a');
    link.href = imageState.enhanced;
    const filename = imageState.fileName.replace(/\.[^/.]+$/, '') + '_enhanced.' + imageState.outputExtension;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Histogram follows whatever is on screen: the result, or the original
  useEffect(() => {
    const shownUrl = imageState.enhanced ?? imageState.original;
    if (!shownUrl || !uiState.showHistogram) return;
    const originalFile = imageState.enhanced ? null : imageState.currentFile;
    let cancelled = false;

    computeHistogramFromUrl(shownUrl)
      .catch(async () => {
        // Browser can't decode FITS/TIFF; let the backend do it
        const file = originalFile ?? new File([await (await fetch(shownUrl)).blob()], 'enhanced.tiff');
        return (await calculateHistogram(file)).histogram;
      })
      .then(histogram => { if (!cancelled) setHistogramData(histogram); })
      .catch(error => console.error('Failed to calculate histogram:', error));

    return () => { cancelled = true; };
  }, [imageState.enhanced, imageState.original, imageState.currentFile, uiState.showHistogram]);

  // Keyboard shortcuts: Cmd/Ctrl+Z undo, Cmd/Ctrl+Shift+Z or Ctrl+Y redo
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || uiState.isLoading) return;
      const target = e.target as HTMLElement;
      if (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && (target as HTMLInputElement).type === 'text')) return;

      const key = e.key.toLowerCase();
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if ((key === 'z' && e.shiftKey) || key === 'y') {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  return (
    <div className="app">
      {/* Top Navigation Bar */}
      <nav className="top-nav">
        <div className="nav-left">
          <span className="nav-logo">
            <span className="logo-icon">✨</span>
            AstroSlide
          </span>
        </div>
        <div className="nav-right">
          {imageState.original && (
            <div className="history-controls">
              <button
                className="nav-link"
                onClick={handleUndo}
                disabled={!history.canUndo || uiState.isLoading}
                title={history.canUndo ? `Undo ${history.current?.label} (⌘Z)` : 'Nothing to undo'}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a5 5 0 015 5v2M3 10l5-5M3 10l5 5" />
                </svg>
                Undo
              </button>
              <button
                className="nav-link"
                onClick={handleRedo}
                disabled={!history.canRedo || uiState.isLoading}
                title={history.canRedo ? `Redo ${history.next?.label} (⇧⌘Z)` : 'Nothing to redo'}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 10H11a5 5 0 00-5 5v2M21 10l-5-5M21 10l-5 5" />
                </svg>
                Redo
              </button>
              <button
                className="nav-link"
                onClick={handleRevert}
                disabled={!imageState.enhanced || uiState.isLoading}
                title="Go back to the original image (can be undone)"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h5M4.6 15a8 8 0 101.9-8.4L4 9" />
                </svg>
                Revert
              </button>
            </div>
          )}
          <button 
            className={`nav-link ${uiState.showHistogram ? 'active' : ''}`}
            onClick={() => setUIState(prev => ({ ...prev, showHistogram: !prev.showHistogram }))}
            title="Toggle histogram"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Histogram
          </button>
          {imageState.enhanced && (
            <button className="nav-download-btn" onClick={handleDownload}>
              <svg className="download-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download
            </button>
          )}
        </div>
      </nav>

      {/* Main Layout - Center Content */}
      <div className="main-layout">
        <div className="editor-layout">
          {/* Left Sidebar - Histogram */}
          {uiState.showHistogram && imageState.original && (
            <aside className="left-sidebar">
              <Histogram data={histogramData} />
            </aside>
          )}

          {/* Center - Image Comparison Area */}
          <main className="center-content">
            {!imageState.original ? (
              <div className="empty-state">
                <FileUpload onFileSelect={handleFileSelect} isLoading={uiState.isLoading} />
              </div>
            ) : (
              <div className="image-viewer">
                <ImageViewer
                  key={imageState.fileName}
                  before={imageState.original}
                  after={imageState.enhanced}
                  overlay={!imageState.enhanced && (
                    <div className="image-info">
                      <span className="info-badge">{imageState.fileName}</span>
                      {imageState.dimensions && (
                        <span className="info-badge">{imageState.dimensions.width} × {imageState.dimensions.height}</span>
                      )}
                    </div>
                  )}
                  loading={uiState.isLoading && (
                    <>
                      <div className="loading-spinner-large"></div>
                      <p>Processing your image...</p>
                      <p className="processing-subtext">Using {presets.find(p => p.id === selectionState.preset)?.name}</p>
                    </>
                  )}
                />
              </div>
            )}

            {uiState.error && (
              <div className="error-toast">
                <p>{uiState.error}</p>
                <button onClick={() => setUIState(prev => ({ ...prev, error: null }))}>×</button>
              </div>
            )}
          </main>

          {/* Right Sidebar - Tabbed Logic */}
          {imageState.original && (
            <aside className="right-sidebar">
              <div className="sidebar-tabs">
                <button 
                  className={`sidebar-tab ${uiState.sidebarTab === 'presets' ? 'active' : ''}`}
                  onClick={() => setUIState(prev => ({ ...prev, sidebarTab: 'presets' }))}
                >
                  Presets
                </button>
                <button 
                  className={`sidebar-tab ${uiState.sidebarTab === 'interactive' ? 'active' : ''}`}
                  onClick={() => setUIState(prev => ({ ...prev, sidebarTab: 'interactive' }))}
                >
                  Interactive
                </button>
              </div>
              
              <div className="sidebar-content">
                {uiState.sidebarTab === 'presets' ? (
                  <>
                    <VisualPresetSelector
                      presets={presets}
                      selectedPreset={selectionState.preset}
                      onPresetChange={handlePresetChange}
                      currentFile={imageState.currentFile}
                      disabled={uiState.isLoading}
                    />
                    {selectionState.preset === 'mineral_moon' && (
                      <MineralMoonControls
                        settings={selectionState}
                        onChange={(key, value) => setSelectionState(prev => ({ ...prev, [key]: value }))}
                        notes={moonNotes}
                        disabled={uiState.isLoading}
                      />
                    )}
                  </>
                ) : (
                  <InteractiveStretchPanel
                    params={stretchParams}
                    onParamsChange={setStretchParams}
                    onAutoStretch={handleAutoStretch}
                    isAutoStretching={isAutoStretching}
                    disabled={uiState.isLoading}
                  />
                )}
              </div>
            </aside>
          )}
        </div>
      </div>

      {/* Footer - Controls */}
      {imageState.original && (
        <footer className="app-footer">
          <div className="footer-content">
            {/* Pro Mode Toggle */}
            <div className="footer-section footer-mode-toggle">
              <button 
                className={`mode-toggle-btn ${uiState.showProMode ? 'active' : ''}`}
                onClick={() => setUIState(prev => ({ ...prev, showProMode: !prev.showProMode }))}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
                {uiState.showProMode ? 'Simple Mode' : 'Pro Mode'}
              </button>
            </div>

            {!uiState.showProMode ? (
              <>
                {/* Output Format Selector */}
                <div className="footer-section footer-format">
                  <OutputFormatSelector
                    formats={outputFormats}
                    selectedFormat={selectionState.format}
                    onFormatChange={handleFormatChange}
                    disabled={uiState.isLoading}
                  />
                </div>

                {/* Intensity Slider (Mineral Moon has its own Color slider below) */}
                {selectionState.preset !== 'mineral_moon' && <div className="footer-section footer-intensity">
                  <label className="intensity-label">
                    <span className="intensity-label-text">Intensity</span>
                    <span className="intensity-value">{Math.round(selectionState.intensity * 100)}%</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={selectionState.intensity * 100}
                    onChange={(e) => handleIntensityChange(Number(e.target.value) / 100)}
                    className="intensity-slider"
                    disabled={uiState.isLoading}
                  />
                </div>}
              </>
            ) : null}

            {/* Action Buttons Group */}
            <div className="footer-section footer-actions">
              {/* New Upload Button */}
              <button 
                className="action-btn action-btn-secondary"
                onClick={() => {
                  setImageState({
                    original: null,
                    enhanced: null,
                    currentFile: null,
                    fileName: '',
                    dimensions: null,
                    outputExtension: 'jpg',
                  });
                  setUIState(prev => ({ ...prev, error: null }));
                  setHistogramData(null);
                  renderedStretchKey.current = null;
                }}
                disabled={uiState.isLoading}
                title="Upload new image"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <span className="action-btn-text">New</span>
              </button>

              {/* Apply Button - Primary CTA */}
              <button 
                className="action-btn action-btn-primary" 
                onClick={handleEnhance}
                disabled={uiState.isLoading}
              >
                {uiState.isLoading ? (
                  <>
                    <span className="btn-spinner"></span>
                    <span>Processing...</span>
                  </>
                ) : (
                  <>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                    </svg>
                    <span>Enhance</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Pro Mode Controls */}
          {uiState.showProMode && (
            <ProModeControls
              settings={proModeSettings}
              onSettingsChange={setProModeSettings}
              disabled={uiState.isLoading}
            />
          )}
        </footer>
      )}
    </div>
  );
}

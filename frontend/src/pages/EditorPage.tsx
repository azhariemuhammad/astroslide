import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import FileUpload from '../components/FileUpload';
import ImageViewer from '../components/ImageViewer';
import Histogram from '../components/Histogram';
import VisualPresetSelector from '../components/VisualPresetSelector';
import ProModeControls, { type ProModeSettings } from '../components/ProModeControls';
import ExportMenu from '../components/ExportMenu';
import Slider from '../components/Slider';
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
import type { PresetType, OutputFormat, HistogramData, StretchParams, EnhanceOptions } from '../types';
import InteractiveStretchPanel from '../components/InteractiveStretchPanel';
import MineralMoonControls from '../components/MineralMoonControls';
import { useHistory } from '../hooks/useHistory';
import { useMediaQuery } from '../hooks/useMediaQuery';

// Consolidated state types
interface ImageState {
  original: string | null;
  enhanced: string | null; // always a JPEG, so the browser can show it
  currentFile: File | null;
  fileName: string;
  dimensions: { width: number; height: number } | null;
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
  sidebarTab: UIState['sidebarTab'];
  selection: SelectionState;
  proEnabled: boolean;
  proMode: ProModeSettings;
  stretch: StretchParams;
}

const DEFAULT_SELECTION: SelectionState = { preset: 'mineral_moon', intensity: 0.75, halo: 0.2, hdr: 0.25, sharpen: 0.3, warmth: -0.25, deconvolve: 0.4 };

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

const EXTENSIONS: Record<OutputFormat, string> = { jpeg: 'jpg', png: 'png', tiff: 'tiff' };
const EXPORT_FORMAT_KEY = 'astroslide.exportFormat';
// Phones, portrait or landscape
const COMPACT_QUERY = '(max-width: 768px), (max-height: 500px)';

const EMPTY_IMAGE: ImageState = { original: null, enhanced: null, currentFile: null, fileName: '', dimensions: null };

// Identifies the stretch inputs behind a rendered result
const stretchKey = (params: StretchParams) => JSON.stringify(params);

// Preset request options for a set of settings (Pro adjustments only when enabled)
const presetOptions = (selection: SelectionState, proEnabled: boolean, proMode: ProModeSettings): EnhanceOptions => ({
  halo: selection.halo,
  hdr: selection.hdr,
  sharpen: selection.sharpen,
  warmth: selection.warmth,
  deconvolve: selection.deconvolve,
  ...(proEnabled
    ? {
        denoise: proMode.denoiseStrength,
        starReduction: proMode.starReduction,
        saturation: proMode.saturationBoost,
        sharpening: proMode.sharpening,
      }
    : {}),
});

const loadExportFormat = (): OutputFormat => {
  try {
    const saved = localStorage.getItem(EXPORT_FORMAT_KEY);
    if (saved === 'jpeg' || saved === 'png' || saved === 'tiff') return saved;
  } catch {
    // Storage unavailable (private window); fall back to the default
  }
  return 'jpeg';
};

const saveFile = (url: string, filename: string) => {
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export default function EditorPage() {
  // Consolidated state objects
  const [imageState, setImageState] = useState<ImageState>(EMPTY_IMAGE);

  const [uiState, setUIState] = useState<UIState>({
    isLoading: false,
    error: null,
    showProMode: false,
    // Off by default on phones, where the controls need the room; the nav toggle shows it
    showHistogram: !window.matchMedia(COMPACT_QUERY).matches,
    sidebarTab: 'presets',
  });

  const [selectionState, setSelectionState] = useState<SelectionState>(DEFAULT_SELECTION);
  const [proModeSettings, setProModeSettings] = useState<ProModeSettings>(DEFAULT_PRO_MODE);
  const [stretchParams, setStretchParams] = useState<StretchParams>(DEFAULT_STRETCH);
  const [exportFormat, setExportFormat] = useState<OutputFormat>(loadExportFormat);
  const [isExporting, setIsExporting] = useState(false);

  const [histogramData, setHistogramData] = useState<HistogramData | null>(null);
  // Feedback on the capture from the last Mineral Moon run (exposure, measured blur)
  const [moonNotes, setMoonNotes] = useState<string[]>([]);
  const [isAutoStretching, setIsAutoStretching] = useState(false);
  // Phone portrait: the controls are a bottom sheet that can be folded away to see the image
  const [sheetCollapsed, setSheetCollapsed] = useState(false);
  const sheetDrag = useRef<{ y: number; swiped: boolean } | null>(null);
  // Small screens (phone, or landscape phone) get a shorter histogram
  const compact = useMediaQuery(COMPACT_QUERY);

  const history = useHistory<Snapshot>();
  // Stretch inputs whose result is already on screen (or restored from history),
  // so the stretch effect doesn't re-render it and wipe the redo stack
  const renderedStretchKey = useRef<string | null>(null);

  const snapshot = (label: string, image: string | null, overrides: Partial<Snapshot> = {}): Snapshot => ({
    label,
    image,
    sidebarTab: uiState.sidebarTab,
    selection: selectionState,
    proEnabled: uiState.showProMode,
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
    renderedStretchKey.current = entry.sidebarTab === 'interactive' ? stretchKey(entry.stretch) : null;
    setImageState(prev => ({ ...prev, enhanced: entry.image }));
    setSelectionState(entry.selection);
    setProModeSettings(entry.proMode);
    setStretchParams(entry.stretch);
    setUIState(prev => ({ ...prev, sidebarTab: entry.sidebarTab, showProMode: entry.proEnabled, error: null }));
  };

  const handleUndo = () => restore(history.undo());
  const handleRedo = () => restore(history.redo());

  const handleRevert = () => {
    const original = snapshot('Revert to original', null, {
      selection: DEFAULT_SELECTION,
      proEnabled: false,
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
    history.reset(snapshot('Original', null));
  };

  const handleNewImage = () => {
    setImageState(EMPTY_IMAGE);
    setUIState(prev => ({ ...prev, error: null }));
    setHistogramData(null);
    setMoonNotes([]);
    renderedStretchKey.current = null;
  };

  const handleEnhance = async () => {
    if (!imageState.currentFile) return;
    const presetName = presets.find(p => p.id === selectionState.preset)?.name ?? 'Enhance';

    setUIState(prev => ({ ...prev, error: null, isLoading: true }));

    try {
      const response = await enhanceImage(
        imageState.currentFile,
        selectionState.preset,
        'jpeg',
        selectionState.intensity,
        presetOptions(selectionState, uiState.showProMode, proModeSettings),
      );
      setImageState(prev => ({ ...prev, enhanced: response.enhanced_image }));
      setMoonNotes(response.notes ?? []);
      renderedStretchKey.current = null;
      history.push(snapshot(presetName, response.enhanced_image));
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

  const handleExportFormatChange = (format: OutputFormat) => {
    setExportFormat(format);
    try {
      localStorage.setItem(EXPORT_FORMAT_KEY, format);
    } catch {
      // Storage unavailable; the choice still applies for this session
    }
  };

  // Interactive stretch: quick low-res preview, then a full-res render once sliders settle.
  // Both are debounced, and responses that arrive after the params changed are dropped,
  // so a stale or low-res response can never overwrite a newer result.
  useEffect(() => {
    if (!imageState.currentFile || uiState.sidebarTab !== 'interactive') return;
    const key = stretchKey(stretchParams);
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
        const response = await interactiveStretch(file, stretchParams, 'jpeg');
        if (!cancelled) {
          fullApplied = true;
          setImageState(prev => ({ ...prev, enhanced: response.enhanced_image }));
          renderedStretchKey.current = key;
          pushHistory(snapshotRef.current('Stretch', response.enhanced_image));
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
  }, [stretchParams, uiState.sidebarTab, imageState.currentFile, pushHistory]);

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

  // The result on screen is a JPEG; other formats are rendered again from the settings
  // that produced it (the history entry), not from sliders moved since
  const handleDownload = async () => {
    const shown = history.current;
    if (!imageState.enhanced || !imageState.currentFile || !shown) return;
    const filename = `${imageState.fileName.replace(/\.[^/.]+$/, '')}_enhanced.${EXTENSIONS[exportFormat]}`;

    if (exportFormat === 'jpeg') {
      saveFile(imageState.enhanced, filename);
      return;
    }

    setIsExporting(true);
    try {
      const file = imageState.currentFile;
      const response = shown.sidebarTab === 'interactive'
        ? await interactiveStretch(file, shown.stretch, exportFormat)
        : await enhanceImage(
            file,
            shown.selection.preset,
            exportFormat,
            shown.selection.intensity,
            presetOptions(shown.selection, shown.proEnabled, shown.proMode),
          );
      saveFile(response.enhanced_image, filename);
    } catch (err) {
      setUIState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Export failed',
      }));
    } finally {
      setIsExporting(false);
    }
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

  const busy = uiState.isLoading || isExporting;

  const showTab = (sidebarTab: UIState['sidebarTab']) => {
    setUIState(prev => ({ ...prev, sidebarTab }));
    setSheetCollapsed(false);
  };

  // Sheet handle: tap toggles, swipe down folds the sheet, swipe up opens it
  const onSheetHandleDown = (e: React.PointerEvent) => {
    // Capture, so the release still reaches the handle after the finger has moved off it
    e.currentTarget.setPointerCapture(e.pointerId);
    sheetDrag.current = { y: e.clientY, swiped: false };
  };
  const onSheetHandleUp = (e: React.PointerEvent) => {
    const drag = sheetDrag.current;
    if (!drag) return;
    const dy = e.clientY - drag.y;
    if (Math.abs(dy) > 24) {
      setSheetCollapsed(dy > 0);
      drag.swiped = true; // the click that follows is part of the swipe
    }
  };
  const onSheetHandleClick = () => {
    if (!sheetDrag.current?.swiped) setSheetCollapsed(c => !c);
    sheetDrag.current = null;
  };

  // Whether the preset settings differ from those behind the preset result on screen
  const shown = history.current;
  const presetSettings = (selection: SelectionState, proEnabled: boolean, proMode: ProModeSettings) =>
    JSON.stringify([selection, proEnabled && proMode]);
  const presetUpToDate = !!shown?.image && shown.sidebarTab === 'presets'
    && presetSettings(shown.selection, shown.proEnabled, shown.proMode) === presetSettings(selectionState, uiState.showProMode, proModeSettings);

  return (
    <div className="app">
      {/* Top Navigation Bar */}
      <nav className="top-nav">
        <div className="nav-left">
          <span className="nav-logo">
            <svg className="logo-icon" viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
              <defs>
                <linearGradient id="logo-moon" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#ffd7a8" />
                  <stop offset="1" stopColor="var(--accent-hover)" />
                </linearGradient>
              </defs>
              <path d="M20.5 4.5a12 12 0 1 0 7 18.6A10 10 0 0 1 20.5 4.5z" fill="url(#logo-moon)" />
              <path d="M24 5l.9 2.1L27 8l-2.1.9L24 11l-.9-2.1L21 8l2.1-.9z" fill="var(--text-primary)" />
            </svg>
            <span className="nav-logo-text">AstroSlide</span>
          </span>
        </div>
        <div className="nav-right">
          {imageState.original && (
            <div className="nav-group">
              <button
                className="nav-link"
                onClick={handleUndo}
                disabled={!history.canUndo || busy}
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
                disabled={!history.canRedo || busy}
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
                disabled={!imageState.enhanced || busy}
                title="Go back to the original image (can be undone)"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h5M4.6 15a8 8 0 101.9-8.4L4 9" />
                </svg>
                Revert
              </button>
            </div>
          )}
          {imageState.original && (
            <div className="nav-group">
              <button
                className={`nav-link ${uiState.showHistogram ? 'active' : ''}`}
                onClick={() => setUIState(prev => ({ ...prev, showHistogram: !prev.showHistogram }))}
                title="Toggle histogram"
                aria-pressed={uiState.showHistogram}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                Histogram
              </button>
              <button
                className="nav-link"
                onClick={handleNewImage}
                disabled={busy}
                title="Open a different image"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                New image
              </button>
            </div>
          )}
          {imageState.enhanced && (
            <ExportMenu
              formats={outputFormats}
              format={exportFormat}
              onFormatChange={handleExportFormatChange}
              onDownload={handleDownload}
              isExporting={isExporting}
              disabled={uiState.isLoading}
            />
          )}
        </div>
      </nav>

      {/* Main Layout - Center Content */}
      <div className="main-layout">
        <div className="editor-layout">
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
            <aside className={`right-sidebar ${sheetCollapsed ? 'collapsed' : ''}`}>
              <button
                type="button"
                className="sheet-handle"
                onPointerDown={onSheetHandleDown}
                onPointerUp={onSheetHandleUp}
                onClick={onSheetHandleClick}
                aria-expanded={!sheetCollapsed}
                aria-label={sheetCollapsed ? 'Show controls' : 'Hide controls'}
              >
                <span className="sheet-grip" />
              </button>
              {uiState.showHistogram && (
                <div className="sidebar-histogram">
                  <Histogram data={histogramData} height={compact ? 44 : 72} />
                </div>
              )}
              <div className="sidebar-tabs" role="tablist">
                <button
                  role="tab"
                  aria-selected={uiState.sidebarTab === 'presets'}
                  className={`sidebar-tab ${uiState.sidebarTab === 'presets' ? 'active' : ''}`}
                  onClick={() => showTab('presets')}
                >
                  Presets
                </button>
                <button
                  role="tab"
                  aria-selected={uiState.sidebarTab === 'interactive'}
                  className={`sidebar-tab ${uiState.sidebarTab === 'interactive' ? 'active' : ''}`}
                  onClick={() => showTab('interactive')}
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
                    {selectionState.preset === 'mineral_moon' ? (
                      <MineralMoonControls
                        settings={selectionState}
                        defaults={DEFAULT_SELECTION}
                        onChange={(key, value) => setSelectionState(prev => ({ ...prev, [key]: value }))}
                        onReset={() => setSelectionState(prev => ({ ...DEFAULT_SELECTION, preset: prev.preset }))}
                        notes={moonNotes}
                        disabled={uiState.isLoading}
                      />
                    ) : (
                      <div className="sidebar-section">
                        <Slider
                          label="Intensity"
                          hint="How strongly the preset is applied."
                          defaultValue={DEFAULT_SELECTION.intensity}
                          value={selectionState.intensity}
                          display={`${Math.round(selectionState.intensity * 100)}%`}
                          min={0}
                          max={1}
                          step={0.01}
                          disabled={uiState.isLoading}
                          onChange={(intensity) => setSelectionState(prev => ({ ...prev, intensity }))}
                        />
                      </div>
                    )}

                    <div className="sidebar-section pro-section">
                      <label className="pro-toggle">
                        <input
                          type="checkbox"
                          checked={uiState.showProMode}
                          onChange={(e) => setUIState(prev => ({ ...prev, showProMode: e.target.checked }))}
                          disabled={uiState.isLoading}
                        />
                        <span className="pro-toggle-text">
                          <span className="pro-toggle-title">Pro adjustments</span>
                          <span className="pro-toggle-hint">Denoise, star reduction, saturation, sharpening</span>
                        </span>
                      </label>
                      {uiState.showProMode && (
                        <ProModeControls
                          settings={proModeSettings}
                          defaults={DEFAULT_PRO_MODE}
                          onSettingsChange={setProModeSettings}
                          disabled={uiState.isLoading}
                        />
                      )}
                    </div>
                  </>
                ) : (
                  <InteractiveStretchPanel
                    params={stretchParams}
                    defaults={DEFAULT_STRETCH}
                    onParamsChange={setStretchParams}
                    onAutoStretch={handleAutoStretch}
                    isAutoStretching={isAutoStretching}
                    disabled={uiState.isLoading}
                  />
                )}
              </div>

              {uiState.sidebarTab === 'presets' ? (
                <div className="sidebar-footer">
                  <button
                    className={`enhance-btn ${presetUpToDate && !uiState.isLoading ? 'applied' : ''}`}
                    onClick={handleEnhance}
                    disabled={busy || presetUpToDate}
                    title={presetUpToDate ? 'These settings are applied. Move a slider to make changes.' : undefined}
                  >
                    {uiState.isLoading ? (
                      <>
                        <span className="btn-spinner"></span>
                        <span>Processing…</span>
                      </>
                    ) : presetUpToDate ? (
                      <>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                        </svg>
                        <span>Applied</span>
                      </>
                    ) : (
                      <>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                        </svg>
                        <span>{shown?.image ? 'Apply changes' : 'Enhance'}</span>
                      </>
                    )}
                  </button>
                </div>
              ) : (
                <div className="sidebar-footer sidebar-footer-note">Changes apply as you move the sliders.</div>
              )}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}

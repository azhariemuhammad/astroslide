import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import FileUpload from '../components/FileUpload';
import ReactCompareImage from 'react-compare-image';
import Histogram from '../components/Histogram';
import VisualPresetSelector from '../components/VisualPresetSelector';
import ProModeControls, { type ProModeSettings } from '../components/ProModeControls';
import OutputFormatSelector from '../components/OutputFormatSelector';
import { 
  enhanceImage, 
  getPresets, 
  getOutputFormats, 
  calculateHistogram
} from '../api/enhance';
import type { PresetType, OutputFormat, HistogramData } from '../types';

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
}

interface SelectionState {
  preset: PresetType;
  format: OutputFormat;
  intensity: number;
}

export default function EditorPage() {
  const navigate = useNavigate();

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
  });

  const [selectionState, setSelectionState] = useState<SelectionState>({
    preset: 'general',
    format: 'jpeg',
    intensity: 0.75,
  });

  const [proModeSettings, setProModeSettings] = useState<ProModeSettings>({
    denoiseStrength: 0.5,
    starReduction: 0,
    saturationBoost: 1.0,
    sharpening: 0.5,
  });

  const [histogramData, setHistogramData] = useState<HistogramData | null>(null);

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

  const handleFileSelect = async (file: File) => {
    setUIState(prev => ({ ...prev, error: null }));
    
    const originalUrl = URL.createObjectURL(file);
    
    const img = new Image();
    img.onload = () => {
      setImageState({
        original: originalUrl,
        enhanced: null,
        currentFile: file,
        fileName: file.name,
        dimensions: { width: img.naturalWidth, height: img.naturalHeight },
        outputExtension: 'jpg',
      });
    };
    img.src = originalUrl;

    // Calculate histogram for the uploaded image
    if (uiState.showHistogram) {
      try {
        const histResponse = await calculateHistogram(file);
        setHistogramData(histResponse.histogram);
      } catch (error) {
        console.error('Failed to calculate histogram:', error);
      }
    }
  };

  const handleEnhance = async () => {
    if (!imageState.currentFile) return;
    
    setUIState(prev => ({ ...prev, error: null, isLoading: true }));

    try {
      const response = await enhanceImage(
        imageState.currentFile,
        selectionState.preset,
        selectionState.format,
        selectionState.intensity,
      );
      setImageState(prev => ({
        ...prev,
        enhanced: response.enhanced_image,
        outputExtension: response.output_extension || 'jpg',
      }));
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

  // Update histogram when enhanced image changes
  useEffect(() => {
    if (imageState.enhanced && uiState.showHistogram) {
      // Convert base64 to blob and calculate histogram
      const base64Data = imageState.enhanced.split(',')[1];
      const byteCharacters = atob(base64Data);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: 'image/jpeg' });
      const file = new File([blob], 'enhanced.jpg', { type: 'image/jpeg' });
      
      calculateHistogram(file)
        .then(response => setHistogramData(response.histogram))
        .catch(error => console.error('Failed to calculate histogram:', error));
    }
  }, [imageState.enhanced, uiState.showHistogram]);

  return (
    <div className="app">
      {/* Top Navigation Bar */}
      <nav className="top-nav">
        <div className="nav-left">
          <span className="nav-logo nav-logo-clickable" onClick={() => navigate('/')}>
            <span className="logo-icon">✨</span>
            AstroSlide
          </span>
        </div>
        <div className="nav-right">
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
                {uiState.isLoading ? (
                  <div className="processing">
                    <div className="loading-spinner-large"></div>
                    <p>Processing your image...</p>
                    <p className="processing-subtext">Using {presets.find(p => p.id === selectionState.preset)?.name}</p>
                  </div>
                ) : imageState.enhanced ? (
                  <div className="comparison-container">
                    <div className="comparison-wrapper">
                      <div className="compare-container-inner">
                        <ReactCompareImage
                          leftImage={imageState.original!}
                          rightImage={imageState.enhanced}
                          sliderLineWidth={2}
                          handle={
                            <div className="compare-handle">
                              <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24">
                                <path d="M8 5v14l-7-7 7-7zm8 0v14l7-7-7-7z" />
                              </svg>
                            </div>
                          }
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="preview-container">
                    <img src={imageState.original} alt="Original" className="preview-image" />
                    <div className="image-info">
                      <span className="info-badge">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="14" height="14">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        {imageState.fileName}
                      </span>
                      {imageState.dimensions && (
                        <span className="info-badge">{imageState.dimensions.width} × {imageState.dimensions.height}</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {uiState.error && (
              <div className="error-toast">
                <p>{uiState.error}</p>
                <button onClick={() => setUIState(prev => ({ ...prev, error: null }))}>×</button>
              </div>
            )}
          </main>

          {/* Right Sidebar - Visual Preset Selector */}
          {imageState.original && (
            <aside className="right-sidebar">
              <VisualPresetSelector
                presets={presets}
                selectedPreset={selectionState.preset}
                onPresetChange={handlePresetChange}
                currentFile={imageState.currentFile}
                disabled={uiState.isLoading}
              />
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

                {/* Intensity Slider */}
                <div className="footer-section footer-intensity">
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
                </div>


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

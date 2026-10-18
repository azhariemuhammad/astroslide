import { useEffect, useRef, useState } from 'react';
import type { OutputFormatOption, OutputFormat } from '../types';
import '../styles/ExportMenu.css';

interface ExportMenuProps {
  formats: OutputFormatOption[];
  format: OutputFormat;
  onFormatChange: (format: OutputFormat) => void;
  onDownload: () => Promise<void>;
  isExporting?: boolean;
  disabled?: boolean;
}

// Download button with a popover for the file format; closes on outside click or Escape
export default function ExportMenu({ formats, format, onFormatChange, onDownload, isExporting = false, disabled = false }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const selected = formats.find(f => f.id === format);

  const download = async () => {
    await onDownload();
    setOpen(false);
  };

  return (
    <div className="export-menu" ref={rootRef}>
      <button
        className="nav-download-btn"
        onClick={() => setOpen(o => !o)}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <svg className="download-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
        Download
        <svg className="export-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="export-popover" role="dialog" aria-label="Download options">
          <span className="export-label">Format</span>
          <div className="export-formats" role="radiogroup">
            {formats.map(f => (
              <button
                key={f.id}
                role="radio"
                aria-checked={f.id === format}
                className={`export-format ${f.id === format ? 'selected' : ''}`}
                onClick={() => onFormatChange(f.id)}
                disabled={isExporting}
              >
                {f.name}
              </button>
            ))}
          </div>
          <p className="export-hint">
            {format === 'jpeg'
              ? 'Smallest file, 8-bit. Best for sharing.'
              : `${selected?.name ?? format.toUpperCase()} keeps 16-bit precision for further editing.`}
          </p>
          <button className="export-confirm" onClick={download} disabled={isExporting}>
            {isExporting ? (
              <>
                <span className="btn-spinner" />
                Preparing {selected?.name ?? format.toUpperCase()}…
              </>
            ) : (
              `Download ${selected?.name ?? format.toUpperCase()}`
            )}
          </button>
        </div>
      )}
    </div>
  );
}

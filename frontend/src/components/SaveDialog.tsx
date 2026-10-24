import { useEffect, useMemo, useRef, useState } from 'react';
import { IN_APP, downloadFile } from '../utils/save';
import '../styles/SaveDialog.css';

interface SaveDialogProps {
  file: File | null;
  onClose: () => void;
}

// The finished file, with a Save button that opens the share sheet (Save Image, Save to Files).
// The tap on Save is the user gesture iOS requires; the export before it may take seconds.
export default function SaveDialog({ file, onClose }: SaveDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const previewUrl = useMemo(() => file && URL.createObjectURL(file), [file]);
  // Some browsers can't show TIFF; then the hint skips the press-and-hold part
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const previewFailed = !!previewUrl && failedUrl === previewUrl;

  useEffect(() => {
    if (!previewUrl) return;
    dialogRef.current?.showModal();
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const close = () => dialogRef.current?.close();

  const save = async () => {
    if (!file) return;
    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file] });
        close();
        return;
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
      }
    }
    downloadFile(file);
  };

  return (
    <dialog
      ref={dialogRef}
      className="save-dialog"
      aria-labelledby="save-title"
      onClose={onClose}
      onClick={e => { if (e.target === e.currentTarget) close(); }}
    >
      <div className="save-body">
        <h2 id="save-title" className="save-title">Your image is ready</h2>
        {previewUrl && !previewFailed && (
          <img className="save-preview" src={previewUrl} alt={file?.name} onError={() => setFailedUrl(previewUrl)} />
        )}
        <p className="save-hint">
          Tap Save, then choose Save Image or Save to Files.
          {!previewFailed && ' You can also press and hold the picture.'}
        </p>
        {IN_APP && (
          <p className="save-hint">
            If saving doesn't work in this app, open astroslide.me in Safari or Chrome.
          </p>
        )}
        <div className="save-actions">
          <button type="button" className="save-cancel" onClick={close}>Close</button>
          <button type="button" className="save-submit" onClick={save} autoFocus>Save</button>
        </div>
      </div>
    </dialog>
  );
}

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import '../styles/ImageViewer.css';

interface ImageViewerProps {
  before: string;
  after?: string | null;
  // Shown over the image (file name / size badges)
  overlay?: ReactNode;
  // Shown over the image while processing; the view (zoom/pan) is kept
  loading?: ReactNode;
}

interface View {
  zoom: number; // multiple of "fit to view" (1 = whole image visible)
  x: number;    // layer translation in viewport pixels
  y: number;
}

const FIT: View = { zoom: 1, x: 0, y: 0 };
const ZOOM_STEP = 1.5;
const MAX_ACTUAL_ZOOM = 8; // 800% of real image pixels

/**
 * Before/after image viewer with zoom and pan.
 *
 * Both images live in identically transformed layers, so they stay aligned at any zoom.
 * The "after" layer is clipped in screen space, so the divider stays put while panning.
 * Zoom: wheel / trackpad pinch (towards the cursor), touch pinch, double-click or double-tap (fit <-> 1:1),
 * toolbar, keys + - 0 1. Drag pans when zoomed in; drag the handle to move the divider.
 * Fullscreen (toolbar or F) uses the Fullscreen API where it exists, and otherwise
 * (iPhone Safari) just covers the window, so it works everywhere.
 * Give it key={before} so a new original image starts again at fit.
 */
export default function ImageViewer({ before, after, overlay, loading }: ImageViewerProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ w: 0, h: 0 });
  const [natural, setNatural] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View>(FIT);
  const [split, setSplit] = useState(0.5);
  const [fullscreen, setFullscreen] = useState(false);

  // Fit scale: screen pixels per image pixel when the whole image fits the view
  const fitScale = natural.w && viewport.w ? Math.min(viewport.w / natural.w, viewport.h / natural.h) : 1;
  const maxZoom = Math.max(1, MAX_ACTUAL_ZOOM / fitScale);

  // Keep the image inside the view: centred when smaller, edges never pulled inward when larger
  const clamp = useCallback((v: View): View => {
    if (!natural.w || !viewport.w) return FIT;
    const zoom = Math.min(Math.max(v.zoom, 1), maxZoom);
    const dw = natural.w * fitScale, dh = natural.h * fitScale;
    const ox = (viewport.w - dw) / 2, oy = (viewport.h - dh) / 2;
    const axis = (t: number, size: number, offset: number, drawn: number) =>
      drawn * zoom <= size
        ? (size - drawn * zoom) / 2 - offset * zoom
        : Math.min(-offset * zoom, Math.max(size - (offset + drawn) * zoom, t));
    return { zoom, x: axis(v.x, viewport.w, ox, dw), y: axis(v.y, viewport.h, oy, dh) };
  }, [natural, viewport, fitScale, maxZoom]);

  // The stored view may predate a resize or a new image size; always show it clamped
  const shown = clamp(view);
  const actualZoom = shown.zoom * fitScale;

  // Zoom so the image point under (px, py) stays under it
  const zoomAt = useCallback((targetZoom: number, px: number, py: number) => {
    setView(raw => {
      const prev = clamp(raw);
      const zoom = Math.min(Math.max(targetZoom, 1), maxZoom);
      const lx = (px - prev.x) / prev.zoom, ly = (py - prev.y) / prev.zoom;
      return clamp({ zoom, x: px - lx * zoom, y: py - ly * zoom });
    });
  }, [clamp, maxZoom]);

  const center = () => [viewport.w / 2, viewport.h / 2] as const;
  const zoomBy = (factor: number) => zoomAt(shown.zoom * factor, ...center());
  const fit = () => setView(FIT);
  const actualPixels = () => zoomAt(1 / fitScale, ...center());

  // Fullscreen: the viewer covers the window (CSS), and the browser chrome is hidden too
  // where the Fullscreen API exists; leaving browser fullscreen (Esc) leaves ours as well
  const toggleFullscreen = () => {
    const el = viewportRef.current;
    if (fullscreen) {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      setFullscreen(false);
    } else {
      setFullscreen(true);
      if (el?.requestFullscreen && document.fullscreenEnabled) el.requestFullscreen().catch(() => {});
      el?.focus();
    }
  };

  useEffect(() => {
    if (!fullscreen) return;
    const onChange = () => {
      if (!document.fullscreenElement) setFullscreen(false);
    };
    // Without the Fullscreen API nothing else catches Esc
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.fullscreenElement) setFullscreen(false);
    };
    document.addEventListener('fullscreenchange', onChange);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('fullscreenchange', onChange);
      window.removeEventListener('keydown', onKey);
    };
  }, [fullscreen]);

  // Track the viewport size
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setViewport({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Wheel zoom needs a non-passive listener to stop the page from scrolling
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)); // ctrlKey = trackpad pinch
      setView(raw => {
        const prev = clamp(raw);
        const zoom = Math.min(Math.max(prev.zoom * factor, 1), maxZoom);
        const px = e.clientX - rect.left, py = e.clientY - rect.top;
        const lx = (px - prev.x) / prev.zoom, ly = (py - prev.y) / prev.zoom;
        return clamp({ zoom, x: px - lx * zoom, y: py - ly * zoom });
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [clamp, maxZoom]);

  // Pointer gestures: one pointer pans, two pointers pinch, the handle moves the divider
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ kind: 'pan' | 'pinch' | 'split'; dist?: number; zoom?: number } | null>(null);
  // Touch double-tap, done by hand: mobile Safari doesn't reliably fire dblclick
  const tapStart = useRef<{ x: number; y: number; t: number } | null>(null);
  const lastTap = useRef<{ x: number; y: number; t: number } | null>(null);
  const lastPointerType = useRef('mouse');

  const local = (e: React.PointerEvent) => {
    const rect = viewportRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const onPointerDown = (e: React.PointerEvent) => {
    viewportRef.current?.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, local(e));
    lastPointerType.current = e.pointerType;
    tapStart.current = e.pointerType === 'touch' && pointers.current.size === 1
      ? { ...local(e), t: e.timeStamp }
      : null;
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      gesture.current = { kind: 'pinch', dist: Math.hypot(a.x - b.x, a.y - b.y), zoom: shown.zoom };
    } else {
      gesture.current = { kind: 'pan' };
    }
  };

  const onHandleDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    viewportRef.current?.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, local(e));
    tapStart.current = null;
    gesture.current = { kind: 'split' };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId) || !gesture.current) return;
    const prevPoint = pointers.current.get(e.pointerId)!;
    const point = local(e);
    pointers.current.set(e.pointerId, point);
    const g = gesture.current;
    if (tapStart.current && Math.hypot(point.x - tapStart.current.x, point.y - tapStart.current.y) > 10) {
      tapStart.current = null;
    }

    if (g.kind === 'split') {
      setSplit(Math.min(1, Math.max(0, point.x / viewport.w)));
    } else if (g.kind === 'pinch' && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      zoomAt(g.zoom! * dist / g.dist!, (a.x + b.x) / 2, (a.y + b.y) / 2);
    } else if (g.kind === 'pan') {
      setView(raw => {
        const prev = clamp(raw);
        return clamp({ ...prev, x: prev.x + point.x - prevPoint.x, y: prev.y + point.y - prevPoint.y });
      });
    }
  };

  // Fit -> actual pixels around the point, anything else -> fit
  const toggleZoomAt = (px: number, py: number) => {
    if (actualZoom < 0.99) zoomAt(1 / fitScale, px, py);
    else fit();
  };

  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    gesture.current = pointers.current.size === 1 ? { kind: 'pan' } : null;

    const start = tapStart.current;
    tapStart.current = null;
    if (e.type !== 'pointerup' || !start || e.timeStamp - start.t > 300) return;
    const prev = lastTap.current;
    if (prev && start.t - prev.t < 350 && Math.hypot(start.x - prev.x, start.y - prev.y) < 40) {
      lastTap.current = null;
      toggleZoomAt(start.x, start.y);
    } else {
      lastTap.current = start;
    }
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    if (lastPointerType.current === 'touch') return; // handled as a double-tap
    const rect = viewportRef.current!.getBoundingClientRect();
    toggleZoomAt(e.clientX - rect.left, e.clientY - rect.top);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '+' || e.key === '=') zoomBy(ZOOM_STEP);
    else if (e.key === '-' || e.key === '_') zoomBy(1 / ZOOM_STEP);
    else if (e.key === '0') fit();
    else if (e.key === '1') actualPixels();
    else if (e.key === 'f' || e.key === 'F') toggleFullscreen();
    else return;
    e.preventDefault();
  };

  const layerStyle = {
    transform: `translate(${shown.x}px, ${shown.y}px) scale(${shown.zoom})`,
    // Show real pixels crisply when zoomed far in
    imageRendering: actualZoom >= 2 ? 'pixelated' as const : 'auto' as const,
  };
  const zoomed = shown.zoom > 1.001;

  return (
    <div
      ref={viewportRef}
      className={`iv-viewport ${zoomed ? 'iv-zoomed' : ''} ${fullscreen ? 'iv-fullscreen' : ''}`}
      tabIndex={0}
      aria-label="Image viewer. Scroll or pinch to zoom, double-tap for 1:1, drag to pan, keys + - 0 1, F for fullscreen."
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
    >
      <div className="iv-layer" style={layerStyle}>
        <img
          src={before}
          alt="Original"
          draggable={false}
          onLoad={after ? undefined : (e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
      </div>

      {after && (
        <>
          <div className="iv-clip" style={{ clipPath: `inset(0 0 0 ${split * 100}%)` }}>
            <div className="iv-layer" style={layerStyle}>
              <img
                src={after}
                alt="Enhanced"
                draggable={false}
                onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              />
            </div>
          </div>
          <div className="iv-divider" style={{ left: `${split * 100}%` }}>
            <div
              className="iv-handle"
              onPointerDown={onHandleDown}
              role="slider"
              aria-label="Before/after divider"
              aria-valuenow={Math.round(split * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
                <path d="M8 5v14l-7-7 7-7zm8 0v14l7-7-7-7z" />
              </svg>
            </div>
          </div>
          <span className="iv-label iv-label-before">Before</span>
          <span className="iv-label iv-label-after">After</span>
        </>
      )}

      {overlay && <div className="iv-overlay">{overlay}</div>}

      <div className="iv-toolbar" onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
        <button type="button" className="iv-step" onClick={() => zoomBy(1 / ZOOM_STEP)} disabled={!zoomed} title="Zoom out (-)" aria-label="Zoom out">−</button>
        <span className="iv-zoom-value" title="Zoom in actual image pixels">{Math.round(actualZoom * 100)}%</span>
        <button type="button" className="iv-step" onClick={() => zoomBy(ZOOM_STEP)} disabled={shown.zoom >= maxZoom - 1e-3} title="Zoom in (+)" aria-label="Zoom in">+</button>
        <button type="button" onClick={fit} disabled={!zoomed} title="Fit to view (0)">Fit</button>
        <button type="button" onClick={actualPixels} title="Actual pixels, 100% (1)">1:1</button>
        <button
          type="button"
          className="iv-fullscreen-btn"
          onClick={toggleFullscreen}
          title={fullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}
          aria-label={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          aria-pressed={fullscreen}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16">
            {fullscreen
              ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
              : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
          </svg>
        </button>
      </div>

      {loading && <div className="iv-loading">{loading}</div>}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { clampSize, drawComposite, levelStars, type CompositeSettings, type MoonLayer, type StarLayer } from '../utils/composite';
import '../styles/CompositeView.css';

interface CompositeViewProps {
  stars: StarLayer;
  moon: MoonLayer | null;
  settings: CompositeSettings;
  onMove: (x: number, y: number) => void;
  onResize: (size: number) => void;
  // Shown over the picture while the Moon is being cut out
  loading?: ReactNode;
}

// Grid lines, as fractions of the picture: the centre and the thirds
const GRID_LINES = [1 / 3, 1 / 2, 2 / 3];
// With the grid on, the Moon's centre snaps to a line within this many screen pixels
const SNAP_PX = 10;
const GRID_KEY = 'astroslide.compositeGrid';

const loadGrid = () => {
  try {
    return localStorage.getItem(GRID_KEY) === '1';
  } catch {
    return false; // storage unavailable (private window)
  }
};

// The nearest grid line within SNAP_PX, else the position itself
const snap = (value: number, size: number) => {
  const line = GRID_LINES.find(l => Math.abs(value - l) * size <= SNAP_PX);
  return line ?? value;
};

const onLine = (value: number, line: number) => Math.abs(value - line) < 1e-6;

/**
 * The star photo with the Moon on it, fitted to the view. Drag anywhere to move the Moon,
 * scroll or pinch to resize it. The grid toggle shows the centre and thirds, and the Moon
 * snaps to them. Drawn at screen resolution; the download is rendered again at full size
 * (utils/composite.renderComposite).
 */
export default function CompositeView({ stars, moon, settings, onMove, onResize, loading }: CompositeViewProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const [grid, setGrid] = useState(loadGrid);
  // Where the drag would put the Moon without snapping, so it can be pulled off a line again
  const dragFrom = useRef<{ x: number; y: number } | null>(null);
  // Latest settings for the gesture handlers, which outlive a render
  const latest = useRef(settings);
  useEffect(() => {
    latest.current = settings;
  });

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setBox({ w: entry.contentRect.width, h: entry.contentRect.height }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Shown size: the photo fitted to the view; drawn at device pixels, never above the photo's own
  const fit = box.w && box.h ? Math.min(box.w / stars.width, box.h / stars.height) : 0;
  const cssW = Math.round(stars.width * fit);
  const cssH = Math.round(stars.height * fit);
  const dpr = Math.min(window.devicePixelRatio || 1, 1 / Math.max(fit, 1e-6));
  const pxW = Math.max(1, Math.round(cssW * dpr));
  const pxH = Math.max(1, Math.round(cssH * dpr));

  // Levelling touches every pixel: only again when the darkness or the view size changes
  const levelled = useMemo(
    () => (cssW > 0 ? levelStars(stars, settings.darkness, pxW, pxH) : null),
    [stars, settings.darkness, pxW, pxH, cssW],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !levelled) return;
    canvas.width = pxW;
    canvas.height = pxH;
    const ctx = canvas.getContext('2d')!;
    if (moon) {
      drawComposite(ctx, pxW, pxH, levelled, stars, moon, settings);
    } else {
      ctx.drawImage(levelled, 0, 0);
    }
  }, [levelled, moon, stars, settings, pxW, pxH]);

  // Wheel needs a non-passive listener to keep the page from scrolling
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      onResize(clampSize(latest.current.size * Math.exp(-e.deltaY * 0.0015)));
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [onResize]);

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    dragFrom.current = { x: latest.current.x, y: latest.current.y };
  };

  const toggleGrid = () => {
    setGrid(on => {
      try {
        localStorage.setItem(GRID_KEY, on ? '0' : '1');
      } catch {
        // storage unavailable; the choice still applies until the page is closed
      }
      return !on;
    });
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const previous = pointers.current.get(e.pointerId);
    if (!previous || !cssW) return;
    const all = [...pointers.current.entries()];
    if (all.length === 2) {
      // Pinch: resize by the change in finger distance
      const [other] = all.filter(([id]) => id !== e.pointerId).map(([, p]) => p);
      const before = Math.hypot(previous.x - other.x, previous.y - other.y);
      const after = Math.hypot(e.clientX - other.x, e.clientY - other.y);
      if (before > 0) onResize(clampSize(latest.current.size * (after / before)));
    } else if (all.length === 1 && dragFrom.current) {
      const raw = {
        x: Math.min(1, Math.max(0, dragFrom.current.x + (e.clientX - previous.x) / cssW)),
        y: Math.min(1, Math.max(0, dragFrom.current.y + (e.clientY - previous.y) / cssH)),
      };
      dragFrom.current = raw;
      onMove(grid ? snap(raw.x, cssW) : raw.x, grid ? snap(raw.y, cssH) : raw.y);
    }
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    pointers.current.delete(e.pointerId);
    // After a pinch, the finger left on the screen drags from where the Moon is now
    dragFrom.current = pointers.current.size ? { x: latest.current.x, y: latest.current.y } : null;
  };

  return (
    <div className="cv-viewport" ref={boxRef}>
      <div className="cv-frame" style={{ width: cssW, height: cssH }}>
        <canvas
          ref={canvasRef}
          className="cv-canvas"
          style={{ width: cssW, height: cssH }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          aria-label="Composite preview: drag to move the Moon, scroll or pinch to resize it"
        />
        {grid && moon && (
          <svg className="cv-grid" width={cssW} height={cssH} aria-hidden="true">
            {GRID_LINES.map(line => (
              <g key={line} className={line === 1 / 2 ? 'cv-grid-centre' : 'cv-grid-third'}>
                <line x1={line * cssW} x2={line * cssW} y1={0} y2={cssH}
                  className={onLine(settings.x, line) ? 'cv-grid-on' : undefined} />
                <line x1={0} x2={cssW} y1={line * cssH} y2={line * cssH}
                  className={onLine(settings.y, line) ? 'cv-grid-on' : undefined} />
              </g>
            ))}
          </svg>
        )}
      </div>
      {moon && (
        <button
          type="button"
          className={`cv-grid-toggle ${grid ? 'active' : ''}`}
          onClick={toggleGrid}
          aria-pressed={grid}
          title={grid ? 'Hide grid' : 'Show grid: the Moon snaps to the centre and thirds'}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
            <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth={2} />
            <path strokeWidth={2} d="M9 3v18M15 3v18M3 9h18M3 15h18" />
          </svg>
          Grid
        </button>
      )}
      {moon && !loading && (
        <span className="cv-hint">
          <span className="cv-hint-pointer">Drag to move the Moon · scroll to resize</span>
          <span className="cv-hint-touch">Drag to move the Moon · pinch to resize</span>
        </span>
      )}
      {loading && <div className="cv-loading">{loading}</div>}
    </div>
  );
}

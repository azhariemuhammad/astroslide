// Moon-on-stars composite, drawn on a canvas so the Moon follows a drag at screen rate.
// The server prepares the layers (backend/composite.py); this only places and blends them.

export interface CompositeSettings {
  x: number;          // Moon centre as a fraction of the star photo's width
  y: number;          // ... and height
  size: number;       // Moon diameter as a fraction of the star photo's short side
  glow: number;       // 0-1
  glowSize: number;   // 0-1, how far the glow spreads (like a brush size)
  brightness: number; // Moon brightness, 0.3-1
  darkness: number;   // Sky darkness, 0-1: 0 keeps the prepared sky, 1 takes it to black
}

export interface StarLayer {
  image: HTMLImageElement;
  width: number;
  height: number;
  sky: number;        // level of the prepared sky, 0-1
}

export interface MoonLayer {
  moon: HTMLImageElement;
  glows: HTMLImageElement[]; // narrow to wide, equally bright at the limb
  size: number;       // moon layer side, px
  radius: number;     // disk radius in moon layer px
  glowReach: number;  // glow layers span the centre +- glowReach * radius
}

export const DEFAULT_COMPOSITE: Omit<CompositeSettings, 'size'> = {
  x: 0.68,
  y: 0.32,
  glow: 0.5,
  glowSize: 0.25,
  brightness: 1,
  darkness: 0.85,
};

// Moon size limits, as a fraction of the star photo's short side
export const MIN_SIZE = 0.03;
export const MAX_SIZE = 0.9;
export const clampSize = (size: number) => Math.min(MAX_SIZE, Math.max(MIN_SIZE, size));

// Moon diameter as a fraction of the short side when both photos have the same pixel scale
// (same telescope): the Moon at its true size against the stars
export const trueSize = (stars: StarLayer, moon: MoonLayer) =>
  (2 * moon.radius) / Math.min(stars.width, stars.height);

// True size when that makes a reasonable picture, else a Moon about a fifth of the frame
export const defaultSize = (stars: StarLayer, moon: MoonLayer) => {
  const size = trueSize(stars, moon);
  return size >= 0.08 && size <= 0.45 ? size : 0.22;
};

export const loadImage = (src: string) =>
  new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Could not load image'));
    img.src = src;
  });

// How much of each glow layer (narrow to wide) a Glow size takes: a bump that slides from
// the narrowest to the widest, summing to 1 so the limb stays as bright at any size
export const glowWeights = (glowSize: number, layers: number) => {
  const centre = glowSize * (layers - 1);
  const bumps = Array.from({ length: layers }, (_, i) => Math.exp(-((i - centre) ** 2) / (2 * 0.7 ** 2)));
  const total = bumps.reduce((a, b) => a + b, 0);
  return bumps.map(b => b / total);
};

// Black point for a Sky darkness: 1 puts the prepared sky's level at black
const blackPoint = (stars: StarLayer, darkness: number) => darkness * stars.sky;

// The star photo at width x height with the black point applied (a levels adjustment,
// which keeps the stars' colour and spreads them over the full range)
export const levelStars = (stars: StarLayer, darkness: number, width: number, height: number) => {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
  ctx.drawImage(stars.image, 0, 0, width, height);
  const black = blackPoint(stars, darkness) * 255;
  if (black > 0) {
    const lut = new Uint8ClampedArray(256);
    for (let v = 0; v < 256; v++) lut[v] = ((v - black) * 255) / (255 - black);
    const pixels = ctx.getImageData(0, 0, width, height);
    const data = pixels.data;
    for (let i = 0; i < data.length; i += 4) {
      data[i] = lut[data[i]];
      data[i + 1] = lut[data[i + 1]];
      data[i + 2] = lut[data[i + 2]];
    }
    ctx.putImageData(pixels, 0, 0);
  }
  return canvas;
};

/**
 * Draw the composite onto ctx at width x height, over `levelled` (levelStars at that size).
 * The disk is first painted in the sky's colour, so the stars behind the Moon (dark side
 * included) disappear but the sky in front of it stays; then the glow and the Moon are
 * added, as light is.
 */
export const drawComposite = (
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  levelled: CanvasImageSource,
  stars: StarLayer,
  moon: MoonLayer,
  settings: CompositeSettings,
) => {
  const scale = width / stars.width; // canvas px per star-photo px
  const k = (settings.size * Math.min(stars.width, stars.height) * scale) / (2 * moon.radius);
  const cx = settings.x * width;
  const cy = settings.y * height;

  ctx.save();
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;
  ctx.drawImage(levelled, 0, 0, width, height);

  const black = blackPoint(stars, settings.darkness);
  const sky = Math.round((Math.max(0, stars.sky - black) / (1 - black)) * 255);
  ctx.fillStyle = `rgb(${sky}, ${sky}, ${sky})`;
  ctx.beginPath();
  ctx.arc(cx, cy, moon.radius * k, 0, 2 * Math.PI);
  ctx.fill();

  ctx.globalCompositeOperation = 'lighter';
  ctx.imageSmoothingQuality = 'high';
  if (settings.glow > 0) {
    const glowSide = 2 * moon.glowReach * moon.radius * k;
    glowWeights(settings.glowSize, moon.glows.length).forEach((weight, i) => {
      if (weight < 0.01) return;
      ctx.globalAlpha = settings.glow * weight;
      ctx.drawImage(moon.glows[i], cx - glowSide / 2, cy - glowSide / 2, glowSide, glowSide);
    });
  }
  const moonSide = moon.size * k;
  ctx.globalAlpha = settings.brightness;
  ctx.drawImage(moon.moon, cx - moonSide / 2, cy - moonSide / 2, moonSide, moonSide);
  ctx.restore();
};

// The composite at the star photo's full resolution, as a file
export const renderComposite = (stars: StarLayer, moon: MoonLayer, settings: CompositeSettings, type: 'image/jpeg' | 'image/png') =>
  new Promise<Blob>((resolve, reject) => {
    const canvas = document.createElement('canvas');
    canvas.width = stars.width;
    canvas.height = stars.height;
    const ctx = canvas.getContext('2d')!;
    drawComposite(ctx, stars.width, stars.height, levelStars(stars, settings.darkness, stars.width, stars.height), stars, moon, settings);
    canvas.toBlob(blob => (blob ? resolve(blob) : reject(new Error('Could not save the composite'))), type, 0.95);
  });

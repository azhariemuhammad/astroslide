import type { HistogramData } from '../types';

// Statistics are stable well below full resolution; keeps this fast on large images
const MAX_SAMPLE_SIZE = 1024;

/**
 * Compute RGB + luminance histograms (256 bins) in the browser.
 * Rejects if the browser cannot decode the image (e.g. FITS or TIFF),
 * so callers can fall back to the backend endpoint.
 */
export const computeHistogramFromUrl = (url: string): Promise<HistogramData> =>
  new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, MAX_SAMPLE_SIZE / Math.max(img.naturalWidth, img.naturalHeight));
      const width = Math.max(1, Math.round(img.naturalWidth * scale));
      const height = Math.max(1, Math.round(img.naturalHeight * scale));

      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Canvas not supported'));
        return;
      }
      ctx.drawImage(img, 0, 0, width, height);
      const pixels = ctx.getImageData(0, 0, width, height).data;

      const red = new Array(256).fill(0);
      const green = new Array(256).fill(0);
      const blue = new Array(256).fill(0);
      const luminance = new Array(256).fill(0);

      for (let i = 0; i < pixels.length; i += 4) {
        const r = pixels[i];
        const g = pixels[i + 1];
        const b = pixels[i + 2];
        red[r]++;
        green[g]++;
        blue[b]++;
        // Same weights as OpenCV's RGB→GRAY, matching the backend histogram
        luminance[Math.round(0.299 * r + 0.587 * g + 0.114 * b)]++;
      }

      resolve({ red, green, blue, luminance });
    };
    img.onerror = () => reject(new Error('Browser cannot decode this image'));
    img.src = url;
  });

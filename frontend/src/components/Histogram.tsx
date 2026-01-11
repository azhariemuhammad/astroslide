import { useEffect, useRef } from 'react';
import '../styles/Histogram.css';

interface HistogramProps {
  data: {
    red: number[];
    green: number[];
    blue: number[];
    luminance: number[];
  } | null;
  width?: number;
  height?: number;
}

export default function Histogram({ data, width = 256, height = 100 }: HistogramProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!data || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size
    canvas.width = width;
    canvas.height = height;

    // Clear canvas
    ctx.fillStyle = 'rgba(13, 27, 42, 0.9)';
    ctx.fillRect(0, 0, width, height);

    // Find max value for normalization
    const allValues = [
      ...data.red,
      ...data.green,
      ...data.blue,
      ...data.luminance
    ];
    const maxValue = Math.max(...allValues);

    // Draw grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = (height / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    // Helper function to draw histogram channel
    const drawChannel = (channelData: number[], color: string, alpha: number = 0.6) => {
      ctx.fillStyle = color;
      ctx.globalAlpha = alpha;

      const barWidth = width / 256;
      
      for (let i = 0; i < 256; i++) {
        const value = channelData[i];
        const normalizedValue = (value / maxValue) * height;
        const x = i * barWidth;
        const y = height - normalizedValue;
        
        ctx.fillRect(x, y, barWidth, normalizedValue);
      }
      
      ctx.globalAlpha = 1;
    };

    // Draw RGB channels
    drawChannel(data.red, 'rgb(239, 68, 68)', 0.5);
    drawChannel(data.green, 'rgb(34, 197, 94)', 0.5);
    drawChannel(data.blue, 'rgb(59, 130, 246)', 0.5);

    // Draw luminance as overlay
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    
    const barWidth = width / 256;
    for (let i = 0; i < 256; i++) {
      const value = data.luminance[i];
      const normalizedValue = (value / maxValue) * height;
      const x = i * barWidth;
      const y = height - normalizedValue;
      
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();

  }, [data, width, height]);

  if (!data) {
    return (
      <div className="histogram-container">
        <div className="histogram-placeholder">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="32" height="32">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <p>Upload an image to see histogram</p>
        </div>
      </div>
    );
  }

  return (
    <div className="histogram-container">
      <div className="histogram-header">
        <h3>Histogram</h3>
        <div className="histogram-legend">
          <span className="legend-item legend-red">R</span>
          <span className="legend-item legend-green">G</span>
          <span className="legend-item legend-blue">B</span>
          <span className="legend-item legend-lum">L</span>
        </div>
      </div>
      <canvas ref={canvasRef} className="histogram-canvas" />
      <div className="histogram-labels">
        <span>0</span>
        <span>128</span>
        <span>255</span>
      </div>
    </div>
  );
}

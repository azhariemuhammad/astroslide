export type PresetType = "mineral_moon" | "nebula";

export type OutputFormat = "jpeg" | "png" | "tiff";

export interface Preset {
  id: PresetType;
  name: string;
  description: string;
  best_for: string;
}

export interface OutputFormatOption {
  id: OutputFormat;
  name: string;
  description: string;
  extension: string;
  mime_type: string;
}

export interface EnhanceResponse {
  status: string;
  enhanced_image: string;
  original_filename: string;
  preset_used?: string;
  preset_name?: string;
  output_format?: string;
  output_extension?: string;
  bit_depth?: number;
  notes?: string[];      // plain-language feedback on the capture (Mineral Moon)
  message: string;
}

export interface PresetsResponse {
  presets: Preset[];
}

export interface OutputFormatsResponse {
  formats: OutputFormatOption[];
}


export interface HistogramData {
  red: number[];
  green: number[];
  blue: number[];
  luminance: number[];
}

export interface HistogramResponse {
  status: string;
  histogram: HistogramData;
}

// MTF stretch (PixInsight Histogram Transformation) + optional star removal
export interface StretchParams {
  shadows: number;
  midtones: number;
  highlights: number;
  remove_stars: boolean;
  star_sensitivity: number;
  inpaint_radius: number;
}

export interface StretchResponse {
  status: string;
  enhanced_image: string;
  output_format: string;
}

export interface StretchPreviewResponse {
  status: string;
  preview_image: string;
}

export interface AutoStfResponse {
  status: string;
  shadows: number;
  midtones: number;
  highlights: number;
}

// Pro Mode fine-tuning applied on top of a preset (neutral values = no change)
export interface EnhanceOptions {
  halo?: number;
  hdr?: number;
  sharpen?: number;
  warmth?: number;
  deconvolve?: number;
  denoise?: number;
  starReduction?: number;
  saturation?: number;
  sharpening?: number;
}

// Video stacking (lucky imaging) job, see backend/stack_jobs.py
export interface StackClipReport {
  name: string;
  frames: number;
  usable: number;
  used: number;
  raw: boolean;
  bayer?: string | null;     // colour-filter pattern used for RAW video
  rejected: Record<string, number>;
}

export interface StackReport {
  clips: StackClipReport[];
  frames_used: number;
  frames_total: number;
  quality_spread: number;
  size: number;
  seconds: number;
  linear: boolean;
  sharpen?: number;          // post-stack sharpening applied, 0-1
  psf_before?: number | null;
  psf_after?: number | null;
}

export interface StackStatus {
  state: 'uploading' | 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  progress: number;
  message: string;
  result_file?: string;
  preview_file?: string | null;  // JPEG for display, when the result is FITS
  linear?: boolean;
  notes?: string[];
  report?: StackReport;
}

// Moon-on-stars composite, see backend/composite.py. Both layers are added onto the star field
export interface MoonLayersResponse {
  status: string;
  moon: string;        // PNG data URL: the full disk, sky removed, black outside it
  glows: string[];     // PNG data URLs: scattered moonlight outside the disk, narrow to wide
  moon_size: number;   // side of the moon layer, centred on the disk
  radius: number;      // disk radius in moon-layer pixels
  glow_reach: number;  // the glow layers span the centre +- glow_reach * radius
}

export interface StarFieldResponse {
  status: string;
  image: string;       // JPEG data URL, gradient and colour cast removed
  width: number;
  height: number;
  sky: number;         // the prepared sky's level, 0-1 (neutral grey)
}

export type PresetType = "moon_hdr" | "mineral_moon" | "nebula";

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
  denoise?: number;
  starReduction?: number;
  saturation?: number;
  sharpening?: number;
}

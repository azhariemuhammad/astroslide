export type PresetType = "mineral_moon_subtle" | "deep_sky" | "general" | "moon_hdr" | "nebula" | "galaxy" | "star_cluster";

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

export interface ErrorResponse {
  detail: string;
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

export interface PreviewResponse {
  status: string;
  preview_image: string;
  preset: string;
}

export interface StarReductionResponse {
  status: string;
  enhanced_image: string;
  original_filename: string;
  output_extension: string;
  reduction_amount: number;
  message: string;
}


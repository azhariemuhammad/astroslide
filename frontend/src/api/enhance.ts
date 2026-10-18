import axios from 'axios';
import type {
  EnhanceResponse,
  PresetsResponse,
  PresetType,
  OutputFormatsResponse,
  OutputFormat,
  HistogramResponse,
  StretchParams,
  StretchResponse,
  StretchPreviewResponse,
  AutoStfResponse,
  EnhanceOptions
} from '../types';

// Use relative URL if VITE_API_BASE_URL is empty or undefined in production (for nginx proxy)
// Otherwise use the provided URL or default to localhost for development
const envApiUrl = import.meta.env.VITE_API_BASE_URL;
const isProduction = import.meta.env.MODE === 'production';
const API_BASE_URL = (envApiUrl === '' || (isProduction && !envApiUrl))
  ? ''  // Empty/undefined in production = relative URL (nginx will proxy /api to backend)
  : (envApiUrl || 'http://localhost:8000');  // Default to localhost for dev

const toError = (error: unknown, fallback: string): Error => {
  if (axios.isAxiosError(error) && error.response) {
    return new Error(error.response.data.detail || fallback);
  }
  return new Error('Network error. Please try again.');
};

const get = async <T>(path: string, errorMessage: string): Promise<T> => {
  try {
    const response = await axios.get<T>(`${API_BASE_URL}${path}`);
    return response.data;
  } catch (error) {
    throw toError(error, errorMessage);
  }
};

// Multipart POST: the file plus any fields; undefined fields are skipped
const postForm = async <T>(
  path: string,
  file: File,
  fields: Record<string, string | number | boolean | undefined>,
  errorMessage: string
): Promise<T> => {
  const formData = new FormData();
  formData.append('file', file);
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) formData.append(key, value.toString());
  }

  try {
    const response = await axios.post<T>(`${API_BASE_URL}${path}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    throw toError(error, errorMessage);
  }
};

export const getPresets = () =>
  get<PresetsResponse>('/api/presets', 'Failed to fetch presets');

export const getOutputFormats = () =>
  get<OutputFormatsResponse>('/api/output-formats', 'Failed to fetch output formats');

export const enhanceImage = (
  file: File,
  preset: PresetType = 'moon_hdr',
  outputFormat: OutputFormat = 'jpeg',
  intensity: number = 0.75,
  options: EnhanceOptions = {}
) =>
  postForm<EnhanceResponse>('/api/enhance', file, {
    preset,
    output_format: outputFormat,
    intensity,
    halo: options.halo,
    hdr: options.hdr,
    sharpen: options.sharpen,
    warmth: options.warmth,
    denoise: options.denoise,
    star_reduction: options.starReduction,
    saturation: options.saturation,
    sharpening: options.sharpening,
  }, 'Failed to enhance image');

export const getAutoStf = (file: File) =>
  postForm<AutoStfResponse>('/api/auto-stf', file, {}, 'Failed to compute auto stretch');

export const calculateHistogram = (file: File) =>
  postForm<HistogramResponse>('/api/histogram', file, {}, 'Failed to calculate histogram');

export const interactiveStretch = (file: File, params: StretchParams, outputFormat: OutputFormat = 'jpeg') =>
  postForm<StretchResponse>('/api/stretch', file, { ...params, output_format: outputFormat }, 'Failed to stretch image');

export const getStretchPreview = (file: File, params: StretchParams) =>
  postForm<StretchPreviewResponse>('/api/stretch-preview', file, { ...params }, 'Failed to generate stretch preview');

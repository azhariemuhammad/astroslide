import axios from 'axios';
import type { 
  EnhanceResponse, 
  PresetsResponse, 
  PresetType, 
  OutputFormatsResponse, 
  OutputFormat,
  HistogramResponse,
  PreviewResponse,
  StarReductionResponse
} from '../types';

// Use relative URL if VITE_API_BASE_URL is empty or undefined in production (for nginx proxy)
// Otherwise use the provided URL or default to localhost for development
const envApiUrl = import.meta.env.VITE_API_BASE_URL;
const isProduction = import.meta.env.MODE === 'production';
const API_BASE_URL = (envApiUrl === '' || (isProduction && !envApiUrl))
  ? ''  // Empty/undefined in production = relative URL (nginx will proxy /api to backend)
  : (envApiUrl || 'http://localhost:8000');  // Default to localhost for dev

export const getPresets = async (): Promise<PresetsResponse> => {
  try {
    const response = await axios.get<PresetsResponse>(`${API_BASE_URL}/api/presets`);
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response) {
      throw new Error(error.response.data.detail || 'Failed to fetch presets');
    }
    throw new Error('Network error. Please try again.');
  }
};

export const getOutputFormats = async (): Promise<OutputFormatsResponse> => {
  try {
    const response = await axios.get<OutputFormatsResponse>(`${API_BASE_URL}/api/output-formats`);
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response) {
      throw new Error(error.response.data.detail || 'Failed to fetch output formats');
    }
    throw new Error('Network error. Please try again.');
  }
};

export const enhanceImage = async (
  file: File,
  preset: PresetType = 'general',
  outputFormat: OutputFormat = 'jpeg',
  intensity: number = 0.75
): Promise<EnhanceResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('preset', preset);
  formData.append('output_format', outputFormat);
  formData.append('intensity', intensity.toString());

  try {
    const response = await axios.post<EnhanceResponse>(
      `${API_BASE_URL}/api/enhance`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response) {
      throw new Error(error.response.data.detail || 'Failed to enhance image');
    }
    throw new Error('Network error. Please try again.');
  }
};

export const calculateHistogram = async (file: File): Promise<HistogramResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await axios.post<HistogramResponse>(
      `${API_BASE_URL}/api/histogram`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response) {
      throw new Error(error.response.data.detail || 'Failed to calculate histogram');
    }
    throw new Error('Network error. Please try again.');
  }
};

export const getPresetPreview = async (
  file: File,
  preset: PresetType
): Promise<PreviewResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('preset', preset);

  try {
    const response = await axios.post<PreviewResponse>(
      `${API_BASE_URL}/api/preview-preset`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response) {
      throw new Error(error.response.data.detail || 'Failed to generate preview');
    }
    throw new Error('Network error. Please try again.');
  }
};

export const reduceStars = async (
  file: File,
  reductionAmount: number = 0.5,
  outputFormat: OutputFormat = 'jpeg'
): Promise<StarReductionResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('reduction_amount', reductionAmount.toString());
  formData.append('output_format', outputFormat);

  try {
    const response = await axios.post<StarReductionResponse>(
      `${API_BASE_URL}/api/reduce-stars`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response) {
      throw new Error(error.response.data.detail || 'Failed to reduce stars');
    }
    throw new Error('Network error. Please try again.');
  }
};


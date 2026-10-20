import React, { useState, useRef } from 'react';
import type { DragEvent, ChangeEvent } from 'react';
import { VIDEO_EXTENSIONS, isVideo } from '../utils/video';
import '../styles/FileUpload.css';

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  // Moon videos (one or more clips) go to the stacker instead of the editor
  onVideosSelect: (files: File[]) => void;
  isLoading: boolean;
}

const FileUpload: React.FC<FileUploadProps> = ({ onFileSelect, onVideosSelect, isLoading }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const allowedExtensions = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.fits', '.fit'];
  const maxFileSize = 50 * 1024 * 1024; // 50MB

  const validateFile = (file: File): string | null => {
    // Check file extension
    const fileName = file.name.toLowerCase();
    const hasValidExt = allowedExtensions.some(ext => fileName.endsWith(ext));
    
    if (!hasValidExt) {
      return `Invalid file type. Supported formats: ${allowedExtensions.join(', ')}`;
    }

    // Check file size
    if (file.size > maxFileSize) {
      return `File too large. Maximum size is 50MB, your file is ${(file.size / 1024 / 1024).toFixed(1)}MB`;
    }

    return null;
  };

  const handleFiles = (files: File[]) => {
    const videos = files.filter(isVideo);
    if (videos.length > 0) {
      setError(null);
      onVideosSelect(videos);
      return;
    }
    handleFile(files[0]);
  };

  const handleFile = (file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    onFileSelect(file);
  };

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFiles(Array.from(files));
    }
  };

  const handleFileInput = (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFiles(Array.from(files));
    }
    e.target.value = ''; // choosing the same file again still fires onChange
  };

  const handleClick = () => {
    if (!isLoading) {
      fileInputRef.current?.click();
    }
  };

  return (
    <div className="file-upload-container">
      <div
        className={`file-upload-zone ${isDragging ? 'dragging' : ''} ${isLoading ? 'loading' : ''}`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={handleClick}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={[...allowedExtensions, ...VIDEO_EXTENSIONS].join(',')}
          multiple
          onChange={handleFileInput}
          style={{ display: 'none' }}
          disabled={isLoading}
        />
        
        <div className="upload-content">
          {isLoading ? (
            <>
              <div className="loading-spinner"></div>
              <p className="upload-text">Processing your image...</p>
              <p className="upload-subtext">This may take a moment</p>
            </>
          ) : (
            <>
              <svg className="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="upload-text">
                <span className="upload-pointer-only">Drag & drop an image or Moon videos here</span>
                <span className="upload-touch-only">Tap to choose an image or videos</span>
              </p>
              <p className="upload-subtext">
                <span className="upload-pointer-only">or click to browse</span>
                <span className="upload-touch-only">From your photos or files</span>
              </p>
              <p className="upload-formats">
                Images: JPEG, PNG, TIFF, FITS (max 50MB)
              </p>
              <p className="upload-formats">
                Videos: Seestar .avi (RAW) or .mp4, one or more clips from the same night
              </p>
            </>
          )}
        </div>
      </div>
      
      {error && (
        <div className="upload-error">
          {error}
        </div>
      )}
    </div>
  );
};

export default FileUpload;


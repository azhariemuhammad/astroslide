// Video formats the stacker accepts (matches backend stacking.VIDEO_EXTENSIONS)
export const VIDEO_EXTENSIONS = ['.avi', '.mp4', '.mov', '.mkv'];

export const isVideo = (file: File) => VIDEO_EXTENSIONS.some(ext => file.name.toLowerCase().endsWith(ext));

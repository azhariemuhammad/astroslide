import axios from 'axios';

// Large videos go up in chunks, one short request each: a router's request timeout or a
// dropped connection then costs one retried chunk, not the whole upload, and "Try again"
// resumes the same job instead of starting (and paying the rate limit for) a new one.

export interface StackUploadSession {
  jobId: string;
  chunkSize: number;
  // The files and settings the session was opened for; anything else needs a new session
  key: string;
}

export interface UploadOptions {
  keep: number;
  sharpen: number;
  onProgress: (fraction: number) => void;
  // A session from an earlier, interrupted attempt with the same files and settings
  previous?: StackUploadSession | null;
  onSession?: (session: StackUploadSession) => void;
  // Waits between retries of a failed chunk, in ms (shortened in tests)
  retryDelays?: number[];
}

const RETRY_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000];

export const sessionKey = (files: File[], keep: number, sharpen: number) =>
  [...files.map(f => `${f.name}:${f.size}:${f.lastModified}`), keep, sharpen].join('|');

const detail = (error: unknown, fallback: string) =>
  axios.isAxiosError(error) && error.response?.data?.detail ? String(error.response.data.detail) : fallback;

// Worth retrying: no response at all, the server busy or restarting, or a timeout
const transient = (error: unknown) =>
  axios.isAxiosError(error) && (!error.response || [408, 429, 500, 502, 503, 504].includes(error.response.status));

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

class SessionGone extends Error {}

// After a 404 for the upload: the job may already be queued (a lost reply to "start")
const alreadyStarted = async (baseUrl: string, jobId: string) => {
  try {
    const response = await axios.get<{ state: string }>(`${baseUrl}/api/stack/${jobId}`);
    return response.data.state !== 'uploading';
  } catch {
    return false;
  }
};

/**
 * Upload `files` for stacking and start the job; resolves to the job id.
 * Throws an Error with a user-facing message; after an interrupted upload, calling
 * again with the session passed to onSession resumes where it stopped.
 */
export async function uploadAndStartStack(baseUrl: string, files: File[], options: UploadOptions): Promise<string> {
  const key = sessionKey(files, options.keep, options.sharpen);
  if (options.previous?.key === key) {
    try {
      return await sendAll(baseUrl, files, options.previous, options);
    } catch (error) {
      if (!(error instanceof SessionGone)) throw error;
      if (await alreadyStarted(baseUrl, options.previous.jobId)) return options.previous.jobId;
      // The interrupted upload expired on the server: start over below
    }
  }
  let session: StackUploadSession;
  try {
    const response = await axios.post<{ job_id: string; chunk_size: number }>(`${baseUrl}/api/stack/uploads`, {
      files: files.map(f => ({ name: f.name, size: f.size })),
      keep: options.keep,
      sharpen: options.sharpen,
    });
    session = { jobId: response.data.job_id, chunkSize: response.data.chunk_size, key };
  } catch (error) {
    throw new Error(detail(error, 'Could not reach the server. Check your connection and try again.'));
  }
  options.onSession?.(session);
  try {
    return await sendAll(baseUrl, files, session, options);
  } catch (error) {
    if (error instanceof SessionGone) throw new Error('The upload expired on the server. Please try again.');
    throw error;
  }
}

async function sendAll(baseUrl: string, files: File[], session: StackUploadSession, options: UploadOptions): Promise<string> {
  const total = files.reduce((sum, f) => sum + f.size, 0);
  const delays = options.retryDelays ?? RETRY_DELAYS;
  let before = 0;  // bytes of the files already sent
  for (let index = 0; index < files.length; index++) {
    const file = files[index];
    let offset = 0;
    let failures = 0;
    while (offset < file.size) {
      const chunk = file.slice(offset, Math.min(offset + session.chunkSize, file.size));
      try {
        const response = await axios.put<{ received: number }>(
          `${baseUrl}/api/stack/${session.jobId}/files/${index}`, chunk, {
            params: { offset },
            headers: { 'Content-Type': 'application/octet-stream' },
            onUploadProgress: event => options.onProgress((before + offset + (event.loaded ?? 0)) / total),
          });
        // The server says how much it has: after a resumed upload that can jump ahead
        offset = response.data.received;
        failures = 0;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 409 && typeof error.response.data?.received === 'number') {
          offset = error.response.data.received;  // out of step with the server: resume where it is
        } else if (axios.isAxiosError(error) && error.response?.status === 404) {
          throw new SessionGone();
        } else if (transient(error) && failures < delays.length) {
          await sleep(delays[failures++]);
        } else if (transient(error)) {
          throw new Error('The upload was interrupted. Press Try again to continue where it stopped.');
        } else {
          throw new Error(detail(error, 'Failed to upload the videos'));
        }
      }
      options.onProgress((before + offset) / total);
    }
    before += file.size;
  }

  for (let failures = 0; ; failures++) {
    try {
      await axios.post(`${baseUrl}/api/stack/${session.jobId}/start`);
      return session.jobId;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        if (await alreadyStarted(baseUrl, session.jobId)) return session.jobId;
        throw new SessionGone();
      }
      if (!transient(error) || failures >= delays.length) throw new Error(detail(error, 'Failed to start stacking'));
      await sleep(delays[failures]);
    }
  }
}

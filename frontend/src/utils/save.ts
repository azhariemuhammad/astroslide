// iPads report themselves as Macs; touch tells them apart
const APPLE_TOUCH = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
// Facebook, Instagram, Messenger and similar in-app browsers drop downloads
export const IN_APP = /FBAN|FBAV|FB_IAB|Instagram|Messenger|Line\/|Snapchat|TikTok/i.test(navigator.userAgent);

// Where <a download> works, files are saved directly; elsewhere SaveDialog is shown
export const canDownloadDirectly = !APPLE_TOUCH && !IN_APP;

export const downloadFile = (file: File) => {
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
};

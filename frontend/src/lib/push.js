// Web Push on this device: service worker, permission and subscription (sent to the server)
import { del, get, post } from './api.js';

export const pushSupported = () =>
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
/** iPhone/iPad outside the installed app: push only works from the Home Screen app */
export const iosNeedsInstall = () =>
  /iPhone|iPad|iPod/.test(navigator.userAgent) && !window.matchMedia('(display-mode: standalone)').matches && !navigator.standalone;

export async function registration() {
  if (!('serviceWorker' in navigator)) return null;
  return (await navigator.serviceWorker.getRegistration('/')) ?? navigator.serviceWorker.register('/sw.js');
}

export async function currentSubscription() {
  if (!pushSupported()) return null;
  const reg = await registration();
  return reg ? reg.pushManager.getSubscription() : null;
}

function keyBytes(base64url) {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Ask permission, subscribe and register the device on the server. Returns the subscription. */
export async function enablePush() {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error('denied');
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const { key } = await get('/push/key');
  let sub = await reg.pushManager.getSubscription();
  // A subscription made with another server key can't receive our messages
  if (sub && sub.options?.applicationServerKey) {
    const current = new Uint8Array(sub.options.applicationServerKey);
    const wanted = keyBytes(key);
    if (current.length !== wanted.length || current.some((b, i) => b !== wanted[i])) { await sub.unsubscribe(); sub = null; }
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  await post('/push/subscriptions', sub.toJSON());
  return sub;
}

export async function disablePush() {
  const sub = await currentSubscription();
  if (!sub) return;
  await del('/push/subscriptions', { endpoint: sub.endpoint }).catch(() => {});
  await sub.unsubscribe();
}

/** On start: if this device is subscribed, make sure the server knows (e.g. after signing in again) */
export async function resyncPush() {
  try {
    if (!pushSupported() || Notification.permission !== 'granted') return;
    const sub = await currentSubscription();
    if (sub) await post('/push/subscriptions', sub.toJSON());
  } catch { /* not important */ }
}

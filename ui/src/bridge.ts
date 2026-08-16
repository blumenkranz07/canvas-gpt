import type { BridgeResponse, DesktopBridge } from './types';

let bridgePromise: Promise<DesktopBridge> | null = null;

function waitForBridge(): Promise<DesktopBridge> {
  if (window.pywebview?.api) {
    return Promise.resolve(window.pywebview.api);
  }
  if (bridgePromise) {
    return bridgePromise;
  }
  bridgePromise = new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error('Desktop bridge unavailable. Launch the UI through Canvas GPT Desktop.'));
    }, 4000);
    window.addEventListener(
      'pywebviewready',
      () => {
        window.clearTimeout(timeout);
        if (window.pywebview?.api) {
          resolve(window.pywebview.api);
        } else {
          reject(new Error('Desktop bridge failed to initialize.'));
        }
      },
      { once: true },
    );
  });
  return bridgePromise;
}

export async function callBridge<T>(method: string, ...args: unknown[]): Promise<T> {
  const bridge = await waitForBridge();
  const action = bridge[method];
  if (!action) {
    throw new Error(`Desktop method '${method}' is unavailable.`);
  }
  const response = (await action(...args)) as BridgeResponse<T>;
  if (!response.ok || response.data === undefined) {
    throw new Error(response.error || 'Desktop operation failed.');
  }
  return response.data;
}

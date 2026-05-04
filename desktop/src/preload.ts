import { contextBridge } from "electron";

export interface DesktopApi {
  readonly appName: "Transport Matters";
}

export function createDesktopApi(): DesktopApi {
  return Object.freeze({
    appName: "Transport Matters",
  });
}

const desktopApi = createDesktopApi();

contextBridge.exposeInMainWorld("transportMattersDesktop", desktopApi);

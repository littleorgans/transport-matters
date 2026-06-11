export {};

declare global {
  interface Window {
    /** Present only inside the Electron shell; absence means plain browser. */
    transportMattersDesktop?: {
      appName: string;
      getPathForFile?: (file: File) => string;
    };
  }
}

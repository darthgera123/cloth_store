/* Firebase configuration comes from the build environment. The web config is
   public by design; access is enforced by Realtime Database rules. */

export interface FirebaseSettings {
  apiKey: string;
  authDomain: string;
  databaseURL: string;
  projectId: string;
  appId: string;
}

export function firebaseSettings(): FirebaseSettings | null {
  const env = import.meta.env;
  const settings: FirebaseSettings = {
    apiKey: env.VITE_FIREBASE_API_KEY ?? "",
    authDomain: env.VITE_FIREBASE_AUTH_DOMAIN ?? "",
    databaseURL: env.VITE_FIREBASE_DATABASE_URL ?? "",
    projectId: env.VITE_FIREBASE_PROJECT_ID ?? "",
    appId: env.VITE_FIREBASE_APP_ID ?? "",
  };
  const ready = Object.values(settings).every((value) => value.trim().length > 0);
  return ready ? settings : null;
}

export const firebaseConfigured = (): boolean => firebaseSettings() !== null;

export const authEmulatorUrl = (): string | null =>
  import.meta.env.VITE_FIREBASE_AUTH_EMULATOR?.trim() || null;

/* Lazily initialised Firebase client. The SDK is imported only when multiplayer
   is actually used, so the local game keeps working without Firebase. */

import { authEmulatorUrl, firebaseSettings } from "./config";

export interface FirebaseHandle {
  uid: string;
  get(path: string): Promise<Record<string, unknown> | null>;
  set(path: string, value: unknown): Promise<void>;
  update(path: string, value: Record<string, unknown>): Promise<void>;
  remove(path: string): Promise<void>;
  subscribe(
    path: string,
    callback: (value: Record<string, unknown> | null) => void,
    onError?: (error: unknown) => void,
  ): () => void;
}

let boot: Promise<FirebaseHandle> | null = null;

export function getFirebase(): Promise<FirebaseHandle> {
  boot ??= (async () => {
    const settings = firebaseSettings();
    if (!settings) throw new Error("Firebase is not configured");

    // The Firebase SDK (~250 kB) is loaded only on paths that actually use
    // multiplayer, so the offline/local game never pays for it.
    const { initializeApp, getApps } = await import("firebase/app");
    const { connectAuthEmulator, getAuth, signInAnonymously } = await import("firebase/auth");
    const { get, getDatabase, onValue, ref, remove, set, update } = await import(
      "firebase/database"
    );

    const app = getApps()[0] ?? initializeApp(settings);
    const auth = getAuth(app);
    const emulator = authEmulatorUrl();
    if (emulator && !auth.emulatorConfig) connectAuthEmulator(auth, emulator, { disableWarnings: true });

    const user = auth.currentUser ?? (await signInAnonymously(auth)).user;
    const db = getDatabase(app);

    return {
      uid: user.uid,
      async get(path) {
        const snapshot = await get(ref(db, path));
        return snapshot.exists() ? (snapshot.val() as Record<string, unknown>) : null;
      },
      async set(path, value) {
        await set(ref(db, path), value);
      },
      async update(path, value) {
        await update(ref(db, path), value);
      },
      async remove(path) {
        await remove(ref(db, path));
      },
      subscribe(path, callback, onError) {
        return onValue(
          ref(db, path),
          (snapshot) => {
            callback(snapshot.exists() ? (snapshot.val() as Record<string, unknown>) : null);
          },
          (error) => onError?.(error),
        );
      },
    };
  })();

  return boot;
}

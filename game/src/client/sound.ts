const MUTE_KEY = "gn:muted";

let context: AudioContext | null = null;

function tone(frequency: number, at: number, duration: number, gain = 0.045) {
  if (!context) return;
  const oscillator = context.createOscillator();
  const envelope = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = frequency;
  envelope.gain.setValueAtTime(0.0001, context.currentTime + at);
  envelope.gain.exponentialRampToValueAtTime(gain, context.currentTime + at + 0.02);
  envelope.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + at + duration);
  oscillator.connect(envelope).connect(context.destination);
  oscillator.start(context.currentTime + at);
  oscillator.stop(context.currentTime + at + duration + 0.05);
}

export function isMuted(): boolean {
  try {
    return sessionStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setMuted(muted: boolean): void {
  try {
    sessionStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  } catch {
    /* private mode */
  }
}

export function chime(kind: "reveal" | "win"): void {
  if (isMuted()) return;
  try {
    context ??= new AudioContext();
    if (context.state === "suspended") void context.resume();
    if (kind === "reveal") {
      tone(659.25, 0, 0.16);
      tone(987.77, 0.09, 0.22);
    } else {
      tone(523.25, 0, 0.22);
      tone(659.25, 0.12, 0.22);
      tone(783.99, 0.24, 0.32);
      tone(1046.5, 0.36, 0.5);
    }
  } catch {
    /* audio unavailable */
  }
}

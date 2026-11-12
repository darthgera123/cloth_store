import { useEffect, useState, type ReactNode } from "react";
import type { Timer } from "../lib/types";
import { CornerFlourish, LotusMark } from "./Mandala";

export function Panel({
  children,
  className = "",
  corners = true,
  frame = true,
}: {
  children: ReactNode;
  className?: string;
  corners?: boolean;
  frame?: boolean;
}) {
  return (
    <div className={`panel ${className}`}>
      {frame ? <span className="panel-frame" aria-hidden="true" /> : null}
      {corners
        ? (["tl", "tr", "bl", "br"] as const).map((at) => (
            <span key={at} className={`corner corner-${at}`} aria-hidden="true">
              <CornerFlourish />
            </span>
          ))
        : null}
      <div className="relative z-[1]">{children}</div>
    </div>
  );
}

export function Rule() {
  return (
    <div className="rule" aria-hidden="true">
      <span className="rule-line" />
      <LotusMark />
      <span className="rule-line" />
    </div>
  );
}

export function Countdown({ timer }: { timer: Timer }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [timer.endsAt]);

  const remaining = Math.max(0, timer.endsAt - now);
  const seconds = Math.ceil(remaining / 1000);
  const display = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  const done = remaining === 0;

  return (
    <div
      className={`flex items-baseline gap-3 border px-4 py-2 ${
        done ? "border-gold bg-lavender-pale" : "border-gold/40"
      }`}
      role="timer"
      aria-live="off"
    >
      {timer.label ? (
        <span className="text-[9px] uppercase tracking-[0.24em] text-plum-hush">{timer.label}</span>
      ) : null}
      <span className="font-serif text-[26px] leading-none tabular-nums">{display}</span>
    </div>
  );
}

/** Static, deterministic confetti: no timers, pure CSS fall. */
export function Confetti({ count = 48 }: { count?: number }) {
  const pieces = Array.from({ length: count }, (_, index) => {
    const left = (index * 37) % 100;
    const delay = ((index * 13) % 40) / 10;
    const duration = 3.2 + ((index * 7) % 22) / 10;
    const size = 5 + ((index * 3) % 4);
    return { left, delay, duration, size, rotate: (index * 47) % 90 };
  });

  return (
    <div className="confetti" aria-hidden="true">
      {pieces.map((piece) => (
        <i
          key={piece.left + "-" + piece.delay}
          style={{
            left: `${piece.left}%`,
            width: `${piece.size}px`,
            height: `${piece.size * 2}px`,
            animationDelay: `${piece.delay}s`,
            animationDuration: `${piece.duration}s`,
            transform: `rotate(${piece.rotate}deg)`,
          }}
        />
      ))}
    </div>
  );
}

export function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2">
      <div className="border border-gold/60 bg-ivory px-5 py-3 text-[12px] text-plum shadow-sm">
        {message}
      </div>
    </div>
  );
}

export function EmptyHint({ children }: { children: ReactNode }) {
  return <p className="text-[13px] leading-relaxed text-plum-soft">{children}</p>;
}

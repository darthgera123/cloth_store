import { useCallback, useEffect, useRef, useState } from "react";
import { Panel } from "../components/ui";
import { getFirebase } from "../multiplayer/client";
import { firebaseConfigured } from "../multiplayer/config";
import { friendlyFirebaseError } from "../multiplayer/errors";
import {
  claimSlot,
  readSessionMeta,
  submitGuess,
  subscribeBoard,
  subscribeOwnGuess,
  subscribeOwnTeam,
  type PartyBoard,
} from "../multiplayer/priceParty";

const EXPIRY_MS = 12 * 60 * 60 * 1000;

type Status = "loading" | "ended" | "error" | "ready";

interface Identity {
  slot: string;
  name: string;
}

const storageKey = (code: string) => `gn:price-entry:${code}`;

function readCode(): string | null {
  const hash = window.location.hash.replace(/^#/, "");
  const hashQuery = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const fromHash = new URLSearchParams(hashQuery).get("code");
  const fromSearch = new URLSearchParams(window.location.search).get("code");
  const code = (fromSearch ?? fromHash)?.trim().toUpperCase();
  return code && /^[A-Z0-9]{4}$/.test(code) ? code : null;
}

function readIdentity(code: string): Identity | null {
  try {
    const raw = sessionStorage.getItem(storageKey(code));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Identity;
    return parsed.slot && parsed.name ? parsed : null;
  } catch {
    return null;
  }
}

function money(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${currency} ${value}`;
  }
}

export function JoinApp() {
  const [code] = useState<string | null>(() => readCode());
  const [status, setStatus] = useState<Status>(() => (readCode() ? "loading" : "error"));
  const [board, setBoard] = useState<PartyBoard | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(() => {
    const initial = readCode();
    return initial ? readIdentity(initial) : null;
  });
  const [guess, setGuess] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [name, setName] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(
    readCode() ? null : "Scan the code on the TV or open the join link.",
  );
  const uidRef = useRef<string | null>(null);

  useEffect(() => {
    if (!code) return;
    if (!firebaseConfigured()) {
      setStatus("error");
      setError("Phone players are not configured for this event.");
      return;
    }

    let active = true;
    let unsubscribe = () => {};

    void (async () => {
      try {
        const firebase = await getFirebase();
        uidRef.current = firebase.uid;

        const meta = await readSessionMeta(code);
        if (!active) return;
        if (!meta || (meta.createdAt > 0 && Date.now() - meta.createdAt > EXPIRY_MS)) {
          setStatus("ended");
          return;
        }

        const saved = readIdentity(code);
        if (saved) {
          const entry = await firebase.get(`sessions/${code}/teams/${saved.slot}`);
          if (!active) return;
          if (entry && entry.uid === firebase.uid) setIdentity(saved);
          else {
            sessionStorage.removeItem(storageKey(code));
            setIdentity(null);
          }
        }

        unsubscribe = subscribeBoard(
          code,
          (next) => {
            if (!active) return;
            setBoard(next);
            setStatus((current) => (current === "ended" ? current : "ready"));
          },
          (subscribeError) => {
            if (!active) return;
            setStatus("error");
            setError(friendlyFirebaseError(subscribeError));
          },
        );
        setStatus((current) => (current === "error" ? current : "ready"));
      } catch (loadError) {
        if (!active) return;
        setStatus("error");
        setError(friendlyFirebaseError(loadError));
      }
    })();

    return () => {
      active = false;
      unsubscribe();
    };
  }, [code]);

  // If the host removes the entry, drop back to the join form.
  useEffect(() => {
    if (!code || !identity) return;
    let active = true;
    const unsubscribe = subscribeOwnTeam(
      code,
      identity.slot,
      (team) => {
        if (!active) return;
        if (!team) {
          sessionStorage.removeItem(storageKey(code));
          setIdentity(null);
          setNotice("The host removed this entry. You can join again.");
          return;
        }
        if (team.name && team.name !== identity.name) {
          const renamed = { ...identity, name: team.name };
          sessionStorage.setItem(storageKey(code), JSON.stringify(renamed));
          setIdentity(renamed);
        }
      },
      (subscribeError) => setNotice(friendlyFirebaseError(subscribeError)),
    );
    return () => {
      active = false;
      unsubscribe();
    };
  }, [code, identity]);

  useEffect(() => {
    if (!code || !identity || !board?.roundId) return;
    let active = true;
    const unsubscribe = subscribeOwnGuess(
      code,
      identity.slot,
      board.roundId,
      (value) => {
        if (active) setGuess(value);
      },
      (subscribeError) => setNotice(friendlyFirebaseError(subscribeError)),
    );
    return () => {
      active = false;
      unsubscribe();
    };
  }, [code, identity, board?.roundId]);

  const join = useCallback(async () => {
    if (!code || !board) return;
    const chosen = name.trim();
    if (!chosen) {
      setNotice("Enter a name first.");
      return;
    }
    try {
      const firebase = await getFirebase();
      const claimed = await claimSlot(code, board.mode, firebase.uid, chosen);
      if ("full" in claimed) {
        setNotice(
          board.mode === "teams"
            ? "All three team slots are taken."
            : "All six player slots are taken.",
        );
        return;
      }
      const next: Identity = { slot: claimed.slot, name: chosen };
      sessionStorage.setItem(storageKey(code), JSON.stringify(next));
      setIdentity(next);
      setNotice(null);
    } catch (joinError) {
      setNotice(friendlyFirebaseError(joinError));
    }
  }, [board, code, name]);

  const sendGuess = useCallback(async () => {
    if (!code || !identity || !board) return;
    const value = Math.round(Number(draft));
    if (!Number.isFinite(value) || value <= 0) {
      setNotice("Enter a price above zero.");
      return;
    }
    try {
      await submitGuess(code, identity.slot, board.roundId, value);
      setGuess(value);
      setNotice("Guess received. You can change it until the host locks guesses.");
    } catch (submitError) {
      setNotice(friendlyFirebaseError(submitError));
    }
  }, [board, code, draft, identity]);

  if (status === "ended") {
    return (
      <Shell>
        <p className="kicker">Game Night</p>
        <h1 className="mt-3 font-serif text-[34px] leading-tight">This session has ended</h1>
        <p className="mt-3 text-[14px] leading-relaxed text-plum-soft">
          Ask the host for a new code, or scan the QR on the TV again.
        </p>
        <button className="btn mt-7" type="button" onClick={() => window.location.reload()}>
          Try again
        </button>
      </Shell>
    );
  }

  if (!code || status === "error") {
    return (
      <Shell>
        <p className="kicker">Game Night · Team Phone</p>
        <h1 className="mt-3 font-serif text-[32px] leading-tight">Join a game</h1>
        <p className="mt-2 text-[13px] text-plum-soft">{error ?? "Enter the code on the TV."}</p>
        <form
          className="mt-6 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const input = new FormData(event.currentTarget).get("code");
            const next = String(input ?? "").trim().toUpperCase();
            if (/^[A-Z0-9]{4}$/.test(next)) window.location.search = `?code=${next}`;
            else setError("That code needs four letters or numbers.");
          }}
        >
          <input
            name="code"
            className="field text-center text-[22px] uppercase tracking-[0.3em]"
            maxLength={4}
            aria-label="Session code"
            defaultValue={code ?? ""}
          />
          <button className="btn btn-primary" type="submit">
            Continue
          </button>
        </form>
      </Shell>
    );
  }

  if (!board) {
    return (
      <Shell>
        <p className="kicker">Session {code}</p>
        <h1 className="mt-3 font-serif text-[30px] leading-tight">Waiting for the host</h1>
        <p className="mt-3 text-[13px] text-plum-soft">
          Keep this page open. It connects as soon as the round starts.
        </p>
      </Shell>
    );
  }

  if (!identity) {
    const teamsMode = board.mode === "teams";
    return (
      <Shell>
        <p className="kicker">The Price Is Right</p>
        <h1 className="mt-3 font-serif text-[30px] leading-tight">
          {teamsMode ? "Name your team" : "Enter your name"}
        </h1>
        <p className="mt-2 text-[13px] text-plum-soft">
          {teamsMode
            ? "Three teams, one phone each. You can update your guess until the host locks them."
            : "Six players, one phone each. You can update your guess until the host locks them."}
        </p>
        <form
          className="mt-6 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void join();
          }}
        >
          <input
            className="field text-[16px]"
            value={name}
            maxLength={24}
            placeholder={teamsMode ? "e.g. The Bargain Hunters" : "e.g. Priya"}
            aria-label={teamsMode ? "Team name" : "Your name"}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
          <button className="btn btn-primary" type="submit" disabled={!name.trim()}>
            Join the game
          </button>
        </form>
        {notice ? <p className="mt-4 text-[12px] text-gold-ink">{notice}</p> : null}
      </Shell>
    );
  }

  const ownScore = board.scores?.[identity.slot] ?? 0;
  const rank = board.leaderboardRevealed
    ? board.podium.find((entry) => entry.entryId === identity.slot)
    : undefined;
  const locked = board.locked || board.revealed || board.priceRevealed;

  return (
    <Shell wide>
      <div className="flex items-baseline justify-between gap-3">
        <p className="kicker">{identity.name}</p>
        <span className="text-[10px] uppercase tracking-[0.2em] text-plum-hush">Score {ownScore}</span>
      </div>

      <div className="mt-4 overflow-hidden border border-gold/30 bg-lavender-pale">
        <img
          src={board.image}
          alt={board.item}
          className="mx-auto block max-h-[190px] w-full object-contain"
        />
      </div>

      <h1 className="mt-4 font-serif text-[26px] leading-tight">{board.item}</h1>
      <p className="mt-1 text-[13px] text-plum-soft">{board.description}</p>

      {board.priceRevealed ? (
        <div className="mt-5 border border-gold bg-lavender-pale/60 p-4 text-center">
          <p className="text-[10px] uppercase tracking-[0.24em] text-gold-ink">Actual price</p>
          <p className="mt-1 font-serif text-[34px] leading-none">
            {money(board.price ?? 0, board.currency)}
          </p>
          {board.leaderboardRevealed ? (
            <p className="mt-2 text-[13px] text-plum-soft">
              {rank
                ? `Rank ${rank.rank} · +${rank.points} point${rank.points === 1 ? "" : "s"}`
                : "No points this round."}
            </p>
          ) : (
            <p className="mt-2 text-[13px] text-plum-soft">Leaderboard next — watch the TV.</p>
          )}
        </div>
      ) : null}

      {!locked ? (
        <form
          className="mt-5 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void sendGuess();
          }}
        >
          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-[0.2em] text-plum-hush">Your guess</span>
            <input
              className="num-field text-[26px]"
              type="number"
              min={1}
              inputMode="numeric"
              placeholder="0"
              value={draft}
              aria-label="Your guess"
              onChange={(event) => setDraft(event.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit">
            {guess === null ? "Submit guess" : "Update guess"}
          </button>
        </form>
      ) : (
        <p className="mt-5 border border-gold/30 px-4 py-3 text-[12px] uppercase tracking-[0.18em] text-plum-soft">
          {board.revealed || board.priceRevealed
            ? "Guesses revealed — watch the TV."
            : "Guesses are locked. Watch the TV."}
        </p>
      )}

      {guess !== null && !board.priceRevealed ? (
        <p className="mt-3 text-[12px] text-gold-ink">
          Your guess: {money(guess, board.currency)}
          {locked ? "" : " · you can still change it"}
        </p>
      ) : null}

      {notice ? <p className="mt-3 text-[12px] text-plum-soft">{notice}</p> : null}
    </Shell>
  );
}

function Shell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="relative min-h-screen bg-lavender px-4 py-6">
      <div className="mx-auto w-full" style={{ maxWidth: wide ? 460 : 420 }}>
        <Panel className="px-6 py-7">{children}</Panel>
        <p className="mt-4 text-center text-[10px] uppercase tracking-[0.24em] text-plum-hush">
          Game Night
        </p>
      </div>
    </div>
  );
}

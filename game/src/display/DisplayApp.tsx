import { useEffect, useRef, useState, type ReactNode } from "react";
import { GAME_BLURB, GAME_IDS, GAME_LABEL, type PublicState } from "../lib/types";
import { Ornaments } from "../components/Mandala";
import { Confetti, Countdown, Panel, Rule, Toast } from "../components/ui";
import { GameBoard, scoreRows } from "./boards";
import { useDisplaySession } from "../client/useDisplaySession";
import { chime, isMuted, setMuted } from "../client/sound";

export function DisplayApp() {
  const session = useDisplaySession();
  const state = session.publicState;
  const [muted, setMutedState] = useState(() => isMuted());
  const [joinCode, setJoinCode] = useState("");
  const lastPhase = useRef<string>("");

  useEffect(() => {
    if (!state || state.phase === lastPhase.current) return;
    lastPhase.current = state.phase;
    if (state.phase === "REVEAL") chime("reveal");
    if (state.phase === "GAME_RESULT") chime("win");
  }, [state]);

  const toggleMute = () => {
    const next = !muted;
    setMutedState(next);
    setMuted(next);
  };

  if (!session.code) {
    return (
      <Shell state={null} code={null} muted={muted} onToggleMute={toggleMute} connected={false}>
        <Panel className="w-full max-w-[560px] px-10 py-12 text-center">
          <p className="kicker">Audience Display</p>
          <h1 className="mt-3 font-script text-[clamp(56px,7vw,84px)] leading-none text-gold-display">
            Game Night
          </h1>
          <p className="mx-auto mt-4 max-w-[36ch] font-serif text-[18px] italic text-plum-soft">
            Enter the session code shown on the host screen.
          </p>
          <form
            className="mt-8 flex flex-col items-center gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              session.join(joinCode);
            }}
          >
            <input
              className="field w-[220px] text-center text-[24px] uppercase tracking-[0.3em]"
              value={joinCode}
              onChange={(event) => setJoinCode(event.target.value.toUpperCase())}
              maxLength={4}
              aria-label="Session code"
              autoFocus
            />
            <button className="btn btn-primary" type="submit" disabled={joinCode.length < 4}>
              Join Session
            </button>
          </form>
          <p className="mt-6 text-[10px] uppercase tracking-[0.24em] text-plum-hush">
            <a
              className="underline decoration-gold/50 underline-offset-4"
              href={`${import.meta.env.BASE_URL}host/`}
            >
              Host dashboard
            </a>
          </p>
        </Panel>
      </Shell>
    );
  }

  if (session.ended) {
    return (
      <Shell
        state={null}
        code={session.code}
        muted={muted}
        onToggleMute={toggleMute}
        connected={false}
      >
        <Panel className="w-full max-w-[620px] px-10 py-12 text-center">
          <p className="kicker">Game Night</p>
          <h2 className="mt-3 font-serif text-[clamp(34px,4vw,54px)] leading-tight">
            Session ended
          </h2>
          <p className="mx-auto mt-4 max-w-[38ch] text-[14px] leading-relaxed text-plum-soft">
            The host dashboard for session <b className="text-plum">{session.code}</b> is no longer
            connected. Rejoin once the host opens it again.
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <button className="btn btn-primary" type="button" onClick={session.retry}>
              Try again
            </button>
            <button className="btn" type="button" onClick={session.leave}>
              Change code
            </button>
          </div>
        </Panel>
      </Shell>
    );
  }

  if (!state) {
    return (
      <Shell
        state={null}
        code={session.code}
        muted={muted}
        onToggleMute={toggleMute}
        connected={session.hostOnline}
      >
        <Panel className="w-full max-w-[560px] px-10 py-12 text-center">
          <p className="kicker">Session {session.code}</p>
          <h2 className="mt-3 font-serif text-[clamp(30px,3.6vw,48px)] leading-tight">
            Waiting for the host
          </h2>
          <p className="mx-auto mt-4 max-w-[34ch] text-[13px] leading-relaxed text-plum-soft">
            Keep this window open. The display connects automatically as soon as the host starts
            the session.
          </p>
        </Panel>
      </Shell>
    );
  }

  return (
    <Shell
      state={state}
      code={session.code}
      muted={muted}
      onToggleMute={toggleMute}
      connected={session.hostOnline}
    >
      <Phase state={state} />
      {state.paused ? (
        <div className="absolute inset-0 z-30 grid place-items-center bg-[#e6d8f1]">
          <div className="text-center">
            <p className="kicker">Game Night</p>
            <p className="mt-2 font-serif text-[clamp(40px,5vw,72px)] leading-none">Paused</p>
          </div>
        </div>
      ) : null}
      <Toast message={session.error} />
    </Shell>
  );
}

function Shell({
  state,
  code,
  muted,
  onToggleMute,
  connected,
  children,
}: {
  state: PublicState | null;
  code: string | null;
  muted: boolean;
  onToggleMute: () => void;
  connected: boolean;
  children: ReactNode;
}) {
  return (
    <div className="relative min-h-screen">
      <Ornaments />
      <div className="relative z-10 flex min-h-screen flex-col">
        <header className="flex items-center justify-between px-[clamp(20px,2.4vw,40px)] py-5">
          <div className="flex items-center gap-3">
            <span className="font-script text-[26px] leading-[1.5] text-gold-ink">Game Night</span>
            {code ? (
              <span className="hidden border-l border-gold/40 pl-3 text-[10px] uppercase tracking-[0.3em] text-plum-hush sm:inline">
                Session {code}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-3">
            {state?.timer ? <Countdown timer={state.timer} /> : null}
            <button
              className="hbtn"
              type="button"
              onClick={onToggleMute}
              aria-pressed={!muted}
            >
              {muted ? "Sound off" : "Sound on"}
            </button>
            <button
              className="hbtn"
              type="button"
              onClick={() => {
                if (document.fullscreenElement) void document.exitFullscreen();
                else void document.documentElement.requestFullscreen?.();
              }}
            >
              Fullscreen
            </button>
          </div>
        </header>

        {code && !connected ? (
          <p className="border-y border-gold/30 bg-lavender-pale px-6 py-2 text-center text-[10px] uppercase tracking-[0.3em] text-plum-soft">
            Host dashboard offline — waiting for it to reconnect
          </p>
        ) : null}

        <main className="grid flex-1 place-items-center px-[clamp(16px,2.4vw,40px)] pb-[clamp(16px,2.6vh,40px)]">
          {children}
        </main>
      </div>
    </div>
  );
}

function Phase({ state }: { state: PublicState }) {
  if (state.phase === "LOBBY") return <Lobby state={state} />;
  if (state.phase === "GAME_INTRO") return <GameIntro state={state} />;
  if (state.phase === "ROUND_READY") return <RoundReady state={state} />;
  if (state.phase === "GAME_RESULT") return <GameResult state={state} />;
  if (state.phase === "ROUND_RESULT") return <RoundResult state={state} />;

  return (
    <div
      className="w-full"
      style={{ maxWidth: state.game === "family_feud" ? 1620 : 1240 }}
    >
      <Panel className="w-full">
        <div className="px-[clamp(24px,3vw,56px)] py-[clamp(22px,3vh,44px)]">
          <GameBoard state={state} />
        </div>
      </Panel>
    </div>
  );
}

function Lobby({ state }: { state: PublicState }) {
  return (
    <BasePanel>
      <h1 className="font-script text-[clamp(84px,11vw,188px)] leading-[0.92] text-gold-display">
        Game Night
      </h1>
      <div className="my-[clamp(22px,3.4vh,40px)]">
        <Rule />
      </div>
      <p className="mx-auto max-w-[36ch] text-balance font-serif text-[clamp(20px,1.85vw,30px)] italic leading-relaxed text-plum-soft">
        Two Families. One Celebration. A Little Friendly Competition.
      </p>

      <p className="mt-8 text-[10px] uppercase tracking-[0.4em] text-gold-ink">
        The Evening's Programme
      </p>
      <div className="mx-auto mt-3 grid w-full max-w-[680px] grid-cols-2 gap-2 sm:gap-3">
        {GAME_IDS.map((game, index) => (
          <div
            key={game}
            className="flex items-baseline justify-center gap-3 border border-gold/30 bg-lavender-pale/40 px-4 py-3 text-center"
          >
            <span className="font-serif text-[11px] uppercase tracking-[0.2em] text-gold-ink">
              {["I", "II", "III", "IV"][index]}
            </span>
            <span className="font-serif text-[clamp(16px,1.55vw,26px)] leading-tight text-plum">
              {GAME_LABEL[game]}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {state.participants.map((person) => (
          <span
            key={person.id}
            className="border border-gold/30 px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-plum-soft"
          >
            {person.name}
          </span>
        ))}
      </div>
      <p className="mt-8 text-[10px] uppercase tracking-[0.3em] text-plum-hush">
        Session {state.code} · Waiting for the host
      </p>
    </BasePanel>
  );
}

function GameIntro({ state }: { state: PublicState }) {
  if (!state.game) return null;
  return (
    <BasePanel>
      <p className="kicker">The Evening's Programme</p>
      <h2 className="mt-3 font-serif text-[clamp(38px,5vw,76px)] font-medium leading-none">
        {GAME_LABEL[state.game]}
      </h2>
      <p className="mx-auto mt-5 max-w-[30ch] font-serif text-[clamp(18px,1.7vw,26px)] italic text-plum-soft">
        {GAME_BLURB[state.game]}
      </p>
      <p className="mt-8 text-[10px] uppercase tracking-[0.34em] text-plum-hush">
        {state.game === "family_feud" && state.teams.length === 2
          ? `${state.teams[0]?.name} versus ${state.teams[1]?.name}`
          : `${state.participants.length} players`}
      </p>
    </BasePanel>
  );
}

function RoundReady({ state }: { state: PublicState }) {
  return (
    <BasePanel>
      <p className="kicker">{state.game ? GAME_LABEL[state.game] : "Game Night"}</p>
      <p className="mt-4 font-serif text-[clamp(28px,3vw,44px)] italic text-plum-soft">Round</p>
      <p className="font-serif text-[clamp(96px,12vw,180px)] leading-none text-gold-display">
        {state.round}
      </p>
      <p className="mt-6 text-[10px] uppercase tracking-[0.34em] text-plum-hush">Get ready</p>
    </BasePanel>
  );
}

function RoundResult({ state }: { state: PublicState }) {
  return (
    <BasePanel>
      <p className="kicker">Round {state.round} complete</p>
      <h2 className="mt-3 font-serif text-[clamp(34px,4vw,60px)] leading-none">
        {state.game ? GAME_LABEL[state.game] : "Game Night"}
      </h2>
      <ScoreList state={state} />
      <p className="mt-8 text-[10px] uppercase tracking-[0.3em] text-plum-hush">
        Next round when the host is ready
      </p>
    </BasePanel>
  );
}

function GameResult({ state }: { state: PublicState }) {
  const result = state.results.at(-1);
  const winners = result?.standings.filter((row) => row.winner).map((row) => row.label) ?? [];

  return (
    <div className="relative w-full max-w-[1040px]">
      <div className="pointer-events-none fixed inset-0 z-20">
        <Confetti />
      </div>
      <Panel className="px-[clamp(28px,4.6vw,80px)] py-[clamp(40px,6vh,72px)] text-center">
        <p className="kicker">{state.game ? GAME_LABEL[state.game] : "Game Night"} · Final</p>
        <h1 className="mt-3 font-script text-[clamp(56px,7.2vw,120px)] leading-[1.02] text-gold-display">
          Congratulations
        </h1>
        <p className="mt-3 font-serif text-[clamp(26px,3.2vw,52px)] leading-tight">
          {winners.length > 0 ? winners.join(" · ") : "A draw"}
        </p>
        {result ? (
          <ul className="mx-auto mt-8 grid w-full max-w-[520px] gap-1.5">
            {result.standings.map((row) => (
              <li
                key={row.label}
                className={`flex items-baseline justify-between border px-5 py-2.5 ${
                  row.winner ? "border-gold bg-lavender-pale" : "border-gold/20"
                }`}
              >
                <span className="text-[clamp(14px,1.3vw,20px)] uppercase tracking-[0.12em]">
                  {row.label}
                </span>
                <span className="text-[clamp(17px,1.6vw,26px)] tabular-nums text-gold-ink">
                  {row.points}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-8 text-[10px] uppercase tracking-[0.3em] text-plum-hush">
          {state.results.length} game{state.results.length === 1 ? "" : "s"} played tonight
        </p>
      </Panel>
    </div>
  );
}

function ScoreList({ state }: { state: PublicState }) {
  const rows = scoreRows(state);
  return (
    <ul className="mx-auto mt-8 grid w-full max-w-[460px] gap-1.5">
      {rows.map((row) => (
        <li
          key={row.label}
          className="flex items-baseline justify-between border border-gold/25 px-5 py-3"
        >
          <span className="text-[clamp(15px,1.5vw,24px)] uppercase tracking-[0.12em]">
            {row.label}
          </span>
          <span className="text-[clamp(20px,2vw,32px)] tabular-nums text-gold-ink">
            {row.points}
          </span>
        </li>
      ))}
    </ul>
  );
}

function BasePanel({ children }: { children: ReactNode }) {
  return (
    <Panel className="w-[min(1040px,86vw)] px-[clamp(32px,5vw,88px)] py-[clamp(44px,7vh,84px)] text-center">
      {children}
    </Panel>
  );
}

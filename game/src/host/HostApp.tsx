import { useState } from "react";
import {
  GAME_BLURB,
  GAME_IDS,
  GAME_LABEL,
  type Action,
  type GameId,
  type SessionConfig,
  type SessionState,
  defaultConfig,
} from "../lib/types";
import { Panel, Toast } from "../components/ui";
import { useHostGame, type HostGameApi } from "../client/useHostGame";
import { GamePanel, formatMoney } from "./panels";

export function HostApp() {
  const api = useHostGame();
  const session = api.hostState?.session ?? null;

  if (!api.ready && !session) {
    return <Centered>Starting host session…</Centered>;
  }

  if (!session) {
    return (
      <div className="host-shell">
        <HostBar api={api} session={null} />
        <div className="mx-auto w-full max-w-[880px] p-4">
          <SetupCard onCreate={api.createSession} />
        </div>
        <Toast message={api.error} />
      </div>
    );
  }

  const send = api.send;

  return (
    <div className="host-shell">
      <HostBar api={api} session={session} />
      <div className="mx-auto grid max-w-[1500px] gap-4 p-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(340px,1fr)]">
        <div className="grid content-start gap-4">
          {session.phase === "LOBBY" ? (
            <>
              <SelectCard session={session} send={send} />
              <SetupCard session={session} onSave={(payload) => send({ type: "configure", ...payload })} />
            </>
          ) : null}

          {session.phase === "GAME_INTRO" || session.phase === "ROUND_READY" ? (
            <ReadyCard session={session} send={send} />
          ) : null}

          {session.phase === "GAME_RESULT" ? <ResultCard session={session} send={send} /> : null}

          {["QUESTION_ACTIVE", "ANSWERING", "REVEAL", "ROUND_RESULT"].includes(session.phase) ? (
            <Panel className="p-5" corners={false}>
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2 border-b border-gold/20 pb-3">
                <h2 className="font-serif text-[24px] font-semibold">
                  {session.game ? GAME_LABEL[session.game] : "Game"}
                </h2>
                <span className="text-[10px] uppercase tracking-[0.22em] text-plum-hush">
                  Round {session.round} · {session.phase.replaceAll("_", " ").toLowerCase()}
                </span>
              </div>
              <p className="mb-4 font-serif text-[22px] leading-snug">{currentQuestionText(session, api.hostState?.questions ?? [])}</p>
              <div className="fade-in">
                <GamePanel
                  session={session}
                  questions={api.hostState?.questions ?? []}
                  send={send}
                />
              </div>
            </Panel>
          ) : null}
        </div>

        <aside className="grid content-start gap-4">
          <ScoresCard session={session} send={send} />
          <SessionCard session={session} api={api} />
        </aside>
      </div>
      <Toast message={api.error} />
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="host-shell grid min-h-screen place-items-center">
      <p className="text-[13px] uppercase tracking-[0.28em] text-plum-hush">{children}</p>
    </div>
  );
}

function currentQuestionText(session: SessionState, questions: unknown[]): string {
  if (!session || questions.length === 0) return "";
  const id =
    session.feud?.questionId ??
    session.herd?.questionId ??
    session.ml?.questionId ??
    session.pir?.questionId;
  const found = (questions as { id: string; question?: string; item?: string }[]).find(
    (question) => question.id === id,
  );
  return found?.question ?? found?.item ?? "";
}

function HostBar({
  api,
  session,
}: {
  api: HostGameApi;
  session: SessionState | null;
}) {
  const displayUrl = session
    ? new URL(`${import.meta.env.BASE_URL}display/?code=${session.code}`, window.location.origin).toString()
    : "";

  return (
    <header className="host-bar">
      <div className="flex items-baseline gap-3">
        <span className="font-script text-[30px] leading-[1.5] text-gold-ink">Game Night</span>
        <span className="hidden border-l border-gold/40 pl-3 text-[9px] uppercase tracking-[0.3em] text-plum-hush sm:inline">
          Host
        </span>
        {session ? (
          <span className="border border-gold/30 px-2 py-1 text-[11px] tracking-[0.24em] text-plum">
            {session.code}
          </span>
        ) : null}
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            api.link.relay === "online" || api.link.sameDevice ? "bg-gold" : "bg-plum-hush/40"
          }`}
          title={`Same-device link: ${api.link.sameDevice ? "ready" : "unavailable"} · Relay: ${
            api.link.relayConfigured ? api.link.relay : "not configured"
          } · Displays: ${api.link.displays}`}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {session ? (
          <>
            <a className="hbtn" href={displayUrl} target="_blank" rel="noreferrer">
              Open display
            </a>
            <button
              className="hbtn"
              type="button"
              disabled={!api.hostState?.canUndo}
              onClick={api.undo}
              title={api.hostState?.undoLabel ? `Undo: ${api.hostState.undoLabel}` : "Nothing to undo"}
            >
              Undo{api.hostState?.undoLabel ? ` · ${api.hostState.undoLabel}` : ""}
            </button>
            <button
              className="hbtn"
              type="button"
              onClick={() => api.send({ type: "set_paused", paused: !session.paused })}
            >
              {session.paused ? "Resume" : "Pause"}
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
}

/* ---------- setup ---------- */

const DEFAULT_NAMES = ["", "", "", "", "", "", "", ""];
const DEFAULT_TEAMS: [string, string] = ["Bride's Family", "Groom's Family"];

function SetupCard({
  session,
  onCreate,
  onSave,
}: {
  session?: SessionState;
  onCreate?: (input: {
    names: string[];
    teams: [string, string] | null;
    config?: Partial<SessionConfig>;
  }) => Promise<boolean>;
  onSave?: (payload: {
    participants: { name: string; team?: 0 | 1 }[];
    teams: [string, string] | null;
    config?: Partial<SessionConfig>;
  }) => void;
}) {
  const [names, setNames] = useState<string[]>(
    session ? session.participants.map((person) => person.name) : DEFAULT_NAMES,
  );
  const [teamsOn, setTeamsOn] = useState<boolean>(session ? session.teams.length === 2 : true);
  const [teamNames, setTeamNames] = useState<[string, string]>(
    session && session.teams.length === 2
      ? [session.teams[0]!.name, session.teams[1]!.name]
      : DEFAULT_TEAMS,
  );
  const [config, setConfig] = useState<SessionConfig>(session ? session.config : defaultConfig);
  const [message, setMessage] = useState<string | null>(null);

  const filled = names.map((name) => name.trim()).filter(Boolean);

  const updateConfig = <K extends keyof SessionConfig>(key: K, value: SessionConfig[K]) => {
    setConfig((current) => ({ ...current, [key]: value }));
  };

  const submit = async () => {
    if (filled.length < 2) {
      setMessage("Add at least two players.");
      return;
    }
    setMessage(null);
    const participants = filled.map((name, index) => ({
      name,
      team: (index % 2) as 0 | 1,
    }));
    const teams = teamsOn ? teamNames : null;

    if (onCreate) {
      const ok = await onCreate({
        names: filled,
        teams,
        config: { ...config },
      });
      if (!ok) setMessage("Could not create the session.");
      return;
    }
    onSave?.({
      participants: teamsOn ? participants : filled.map((name) => ({ name })),
      teams,
      config,
    });
  };

  return (
    <Panel className="p-5" corners={false}>
      <div className="mb-4 flex items-baseline justify-between gap-2 border-b border-gold/20 pb-3">
        <h2 className="font-serif text-[24px] font-semibold">
          {session ? "Players & teams" : "Set up the evening"}
        </h2>
        <span className="text-[10px] uppercase tracking-[0.22em] text-plum-hush">
          {session ? "Changes apply in the lobby" : "Step 1"}
        </span>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {names.map((name, index) => (
          <input
            key={index}
            className="field"
            placeholder={`Player ${index + 1}`}
            aria-label={`Player ${index + 1} name`}
            value={name}
            onChange={(event) => {
              const next = [...names];
              next[index] = event.target.value;
              setNames(next);
            }}
          />
        ))}
      </div>

      <label className="mt-4 flex items-center gap-2 text-[12px] text-plum-soft">
        <input
          type="checkbox"
          checked={teamsOn}
          onChange={(event) => setTeamsOn(event.target.checked)}
        />
        Two teams (needed for Family Feud)
      </label>

      {teamsOn ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <input
            className="field"
            aria-label="First team name"
            value={teamNames[0]}
            onChange={(event) => setTeamNames([event.target.value, teamNames[1]])}
          />
          <input
            className="field"
            aria-label="Second team name"
            value={teamNames[1]}
            onChange={(event) => setTeamNames([teamNames[0], event.target.value])}
          />
        </div>
      ) : null}

      {config ? (
        <details className="mt-4 border border-gold/20 p-3">
          <summary className="cursor-pointer text-[10px] uppercase tracking-[0.22em] text-plum-hush">
            Game rules
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Rule label="Strike limit">
              <select
                className="field"
                value={config.strikeLimit}
                onChange={(event) => updateConfig("strikeLimit", Number(event.target.value))}
              >
                {[2, 3, 4, 5].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Rule>
            <Rule label="Round multiplier">
              <select
                className="field"
                value={config.roundMultiplier}
                onChange={(event) => updateConfig("roundMultiplier", Number(event.target.value))}
              >
                {[1, 2, 3].map((value) => (
                  <option key={value} value={value}>
                    ×{value}
                  </option>
                ))}
              </select>
            </Rule>
            <Rule label="Herd points">
              <select
                className="field"
                value={config.herdPoints}
                onChange={(event) => updateConfig("herdPoints", Number(event.target.value))}
              >
                {[1, 2, 3, 5].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Rule>
            <Rule label="Most Likely">
              <select
                className="field"
                value={config.mlMode}
                onChange={(event) =>
                  updateConfig("mlMode", event.target.value as SessionConfig["mlMode"])
                }
              >
                <option value="casual">Casual (no points)</option>
                <option value="competitive">Competitive</option>
              </select>
            </Rule>
            <Rule label="Price mode">
              <select
                className="field"
                value={config.pirMode}
                onChange={(event) =>
                  updateConfig("pirMode", event.target.value as SessionConfig["pirMode"])
                }
              >
                <option value="individual">Individual</option>
                <option value="team">Teams</option>
              </select>
            </Rule>
            <Rule label="Price points">
              <select
                className="field"
                value={config.pirPoints}
                onChange={(event) => updateConfig("pirPoints", Number(event.target.value))}
              >
                {[1, 2, 3, 5, 10].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Rule>
            <label className="flex items-center gap-2 text-[12px] text-plum-soft">
              <input
                type="checkbox"
                checked={config.herdTieAwards}
                onChange={(event) => updateConfig("herdTieAwards", event.target.checked)}
              />
              Award tied majorities
            </label>
            <label className="flex items-center gap-2 text-[12px] text-plum-soft">
              <input
                type="checkbox"
                checked={config.pinkCowEnabled}
                onChange={(event) => updateConfig("pinkCowEnabled", event.target.checked)}
              />
              Pink Cow enabled
            </label>
            <label className="flex items-center gap-2 text-[12px] text-plum-soft">
              <input
                type="checkbox"
                checked={config.pinkCowBlocksWin}
                onChange={(event) => updateConfig("pinkCowBlocksWin", event.target.checked)}
              />
              Pink Cow blocks winning
            </label>
            <label className="flex items-center gap-2 text-[12px] text-plum-soft">
              <input
                type="checkbox"
                checked={config.shuffleQuestions}
                onChange={(event) => updateConfig("shuffleQuestions", event.target.checked)}
              />
              Shuffle question order
            </label>
            <Rule label="Price fallback">
              <select
                className="field"
                value={config.pirAllOverFallback}
                onChange={(event) =>
                  updateConfig(
                    "pirAllOverFallback",
                    event.target.value as SessionConfig["pirAllOverFallback"],
                  )
                }
              >
                <option value="closest">Closest when all over</option>
                <option value="lowest">Lowest guess when all over</option>
              </select>
            </Rule>
          </div>
        </details>
      ) : null}

      {message ? <p className="mt-3 text-[12px] text-gold-ink">{message}</p> : null}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gold/20 pt-3">
        <button className="btn btn-primary" type="button" onClick={submit}>
          {session ? "Save setup" : "Create session"}
        </button>
        <span className="text-[11px] text-plum-soft">
          {filled.length} player{filled.length === 1 ? "" : "s"}
        </span>
      </div>
    </Panel>
  );
}

function Rule({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1">
      <span className="text-[10px] uppercase tracking-[0.18em] text-plum-hush">{label}</span>
      {children}
    </label>
  );
}

/* ---------- game select ---------- */

function SelectCard({ session, send }: { session: SessionState; send: (action: Action) => void }) {
  return (
    <Panel className="p-5" corners={false}>
      <div className="mb-4 flex items-baseline justify-between gap-2 border-b border-gold/20 pb-3">
        <h2 className="font-serif text-[24px] font-semibold">Choose the next game</h2>
        <span className="text-[10px] uppercase tracking-[0.22em] text-plum-hush">
          {session.results.length} played
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {GAME_IDS.map((game: GameId) => {
          const blocked = game === "family_feud" && session.teams.length !== 2;
          return (
            <button
              key={game}
              type="button"
              className="tile"
              disabled={blocked}
              onClick={() => send({ type: "select_game", game })}
              title={blocked ? "Add two team names in setup first" : GAME_BLURB[game]}
            >
              <span className="font-serif text-[11px] uppercase tracking-[0.3em] text-gold-ink">
                {GAME_IDS.indexOf(game) + 1}
              </span>
              <span className="font-serif text-[24px] leading-tight">{GAME_LABEL[game]}</span>
              <span className="text-[11px] text-plum-soft">{GAME_BLURB[game]}</span>
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

/* ---------- ready / result ---------- */

function ReadyCard({ session, send }: { session: SessionState; send: (action: Action) => void }) {
  return (
    <Panel className="p-6" corners={false}>
      <p className="text-[10px] uppercase tracking-[0.3em] text-gold-ink">
        {session.game ? GAME_LABEL[session.game] : ""}
      </p>
      <h2 className="mt-2 font-serif text-[38px] leading-none">Round {session.round || 1}</h2>
      <p className="mt-3 text-[13px] text-plum-soft">
        The audience sees the game introduction. Start the question when the room is ready.
      </p>
      <div className="mt-5 flex flex-wrap gap-2 border-t border-gold/20 pt-4">
        <button
          className="hbtn hbtn-solid"
          type="button"
          onClick={() => send({ type: "start_round" })}
        >
          Start round {session.round || 1}
        </button>
        <button className="hbtn" type="button" onClick={() => send({ type: "skip_question" })}>
          Skip question
        </button>
        <button className="hbtn hbtn-danger" type="button" onClick={() => send({ type: "end_game" })}>
          End game
        </button>
      </div>
    </Panel>
  );
}

function ResultCard({ session, send }: { session: SessionState; send: (action: Action) => void }) {
  const result = session.results.at(-1);
  return (
    <Panel className="p-6" corners={false}>
      <p className="text-[10px] uppercase tracking-[0.3em] text-gold-ink">Final result</p>
      <h2 className="mt-2 font-serif text-[34px] leading-none">
        {session.game ? GAME_LABEL[session.game] : "Game"}
      </h2>

      <ul className="mt-4 grid gap-1.5">
        {result?.standings.map((row) => (
          <li
            key={row.label}
            className={`flex items-baseline justify-between border px-3 py-2 ${
              row.winner ? "border-gold bg-lavender-pale" : "border-gold/20"
            }`}
          >
            <span className="text-[12px] uppercase tracking-[0.14em]">{row.label}</span>
            <span className="text-[15px] tabular-nums text-gold-ink">{row.points}</span>
          </li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-gold/20 pt-4">
        <button
          className="hbtn hbtn-solid"
          type="button"
          onClick={() => send({ type: "back_to_lobby" })}
        >
          Back to game selection
        </button>
        <button className="hbtn" type="button" onClick={() => send({ type: "reset_session" })}>
          Reset everything
        </button>
      </div>
    </Panel>
  );
}

/* ---------- scores ---------- */

function ScoresCard({ session, send }: { session: SessionState; send: (action: Action) => void }) {
  const showTeams = session.game === "family_feud" && session.teams.length === 2;
  const rows = showTeams
    ? session.teams.map((team) => ({
        id: team.id,
        name: team.name,
        points: session.scores.teams[team.id] ?? 0,
        kind: "team" as const,
      }))
    : session.participants.map((person) => ({
        id: person.id,
        name: person.name,
        points: session.scores.participants[person.id] ?? 0,
        kind: "participant" as const,
      }));

  return (
    <Panel className="p-4" corners={false}>
      <div className="card-head">
        <h2 className="font-serif text-[20px] font-semibold">Scores</h2>
        <span className="text-[10px] uppercase tracking-[0.2em] text-plum-hush">
          {showTeams ? "Teams" : "Players"}
        </span>
      </div>
      <ul className="grid gap-1.5">
        {rows.map((row) => (
          <li key={row.id} className="grid grid-cols-[minmax(0,1fr)_84px] items-center gap-2">
            <span className="truncate text-[12px] uppercase tracking-[0.1em] text-plum-soft">
              {row.name}
            </span>
            <input
              className="num-field"
              type="number"
              min={0}
              aria-label={`Score for ${row.name}`}
              value={row.points}
              onChange={(event) => {
                const value = Math.max(0, Number(event.target.value) || 0);
                send({ type: "edit_score", kind: row.kind, id: row.id, value });
              }}
            />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ---------- session card ---------- */

function SessionCard({
  session,
  api,
}: {
  session: SessionState;
  api: HostGameApi;
}) {
  const displayUrl = new URL(
    `${import.meta.env.BASE_URL}display/?code=${session.code}`,
    window.location.origin,
  ).toString();

  return (
    <Panel className="p-4" corners={false}>
      <div className="card-head">
        <h2 className="font-serif text-[20px] font-semibold">Session</h2>
        <span className="text-[10px] uppercase tracking-[0.2em] text-plum-hush">
          {session.phase.replaceAll("_", " ").toLowerCase()}
        </span>
      </div>

      <div className="grid gap-2">
        <div className="flex items-center gap-2">
          <code className="field flex-1 truncate text-[11px] leading-9">{displayUrl}</code>
          <button
            className="hbtn"
            type="button"
            onClick={() => void navigator.clipboard?.writeText(displayUrl)}
          >
            Copy
          </button>
        </div>

        <div>
          <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-plum-hush">Timer</p>
          <div className="flex flex-wrap gap-2">
            {[30, 60, 120].map((seconds) => (
              <button
                key={seconds}
                className="hbtn"
                type="button"
                onClick={() =>
                  api.send({ type: "set_timer", seconds, label: `${seconds}s` })
                }
              >
                {seconds}s
              </button>
            ))}
            <button className="hbtn" type="button" onClick={() => api.send({ type: "clear_timer" })}>
              Clear
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 border-t border-gold/20 pt-3">
          <button
            className="hbtn"
            type="button"
            disabled={
              !["QUESTION_ACTIVE", "ANSWERING", "REVEAL", "ROUND_RESULT"].includes(session.phase)
            }
            onClick={() => {
              if (window.confirm("Restart this round? Points awarded this round are taken back.")) {
                api.send({ type: "restart_round" });
              }
            }}
          >
            Restart round
          </button>
          <button
            className="hbtn"
            type="button"
            disabled={session.phase === "LOBBY" || session.phase === "GAME_RESULT"}
            onClick={() => api.send({ type: "skip_question" })}
          >
            Skip question
          </button>
          <button
            className="hbtn"
            type="button"
            disabled={session.phase === "LOBBY" || session.phase === "GAME_RESULT"}
            onClick={() => api.send({ type: "end_game" })}
          >
            End game
          </button>
          <button
            className="hbtn hbtn-danger"
            type="button"
            onClick={() => {
              if (window.confirm("Reset the whole evening? Scores and results are cleared.")) {
                api.send({ type: "reset_session" });
              }
            }}
          >
            Reset all
          </button>
          <button
            className="hbtn hbtn-danger"
            type="button"
            onClick={() => {
              if (window.confirm("End this session? The display will show that it has ended.")) {
                api.endSession();
              }
            }}
          >
            End session
          </button>
        </div>

        {api.hostState?.history?.length ? (
          <div className="border-t border-gold/20 pt-2">
            <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-plum-hush">
              Last actions
            </p>
            <ol className="grid gap-1">
              {api.hostState.history.map((entry, index) => (
                <li
                  key={`${entry.at}-${index}`}
                  className="flex items-baseline justify-between text-[11px] text-plum-soft"
                >
                  <span>{entry.label}</span>
                  <span className="tabular-nums text-plum-hush">
                    {new Date(entry.at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <div className="border-t border-gold/20 pt-2">
          <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-plum-hush">
            Connection
          </p>
          <ul className="grid gap-1 text-[11px] text-plum-soft">
            <li className="flex items-center justify-between">
              <span>Same-device link</span>
              <span className="text-plum">
                {api.link.sameDevice ? "ready" : "unavailable"}
              </span>
            </li>
            <li className="flex items-center justify-between">
              <span>Cross-device relay</span>
              <span className="text-plum">
                {api.link.relayConfigured ? api.link.relay : "not configured"}
              </span>
            </li>
            <li className="flex items-center justify-between">
              <span>Displays connected</span>
              <span className="tabular-nums text-plum">{api.link.displays}</span>
            </li>
          </ul>
        </div>

        <p className="text-[11px] leading-relaxed text-plum-hush">
          Audience: open <b>/display/</b> on the television and enter code{" "}
          <b className="text-plum">{session.code}</b>. Keep this dashboard open on the laptop.
          {session.game === "price_is_right" ? " Prices are shown here only until you reveal them." : ""}
          {session.timer ? ` Timer ends at ${new Date(session.timer.endsAt).toLocaleTimeString()}.` : ""}
          {session.config.currency ? ` Currency: ${session.config.currency}.` : ""}
          {session.game === "family_feud" && session.feud
            ? ` Pot: ${formatMoney(session.feud.pot * session.config.roundMultiplier, session.config.currency)}.`
            : ""}
        </p>
      </div>
    </Panel>
  );
}

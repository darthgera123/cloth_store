/* Audience boards. Everything here reads PublicState only — hidden answers,
   prices and tallies never reach this code path. */

import { useEffect, useRef, useState } from "react";
import type { GameId, Participant, PublicState, PublicPrice, Team } from "../lib/types";
import { StrikeMark } from "../components/Mandala";
import { publicAsset } from "../lib/assets";

const labelFor = (state: PublicState, id: string | null): string => {
  if (!id) return "";
  return (
    state.participants.find((person) => person.id === id)?.name ??
    state.teams.find((team) => team.id === id)?.name ??
    ""
  );
};

function TeamScore({
  team,
  score,
  active,
  strikes,
  limit,
  align,
}: {
  team: Team;
  score: number;
  active: boolean;
  strikes: number;
  limit: number;
  align: "left" | "right";
}) {
  return (
    <div className={`flex flex-col gap-1 ${align === "right" ? "items-end text-right" : ""}`}>
      <span
        className={`text-[10px] uppercase tracking-[0.24em] transition-colors ${
          active ? "text-gold-ink" : "text-transparent"
        }`}
      >
        Guessing now
      </span>
      <span className="font-serif text-[clamp(16px,1.35vw,26px)] font-medium uppercase tracking-[0.2em] text-plum-soft">
        {team.name}
      </span>
      <span className="text-[clamp(46px,4.6vw,80px)] font-medium leading-none tabular-nums text-plum">
        {score}
      </span>
      <span className={`mt-1 flex items-center gap-2 ${active ? "" : "invisible"}`}>
        <span className="flex gap-2">
          {Array.from({ length: limit }, (_, index) => (
            <StrikeMark key={index} on={index < strikes} />
          ))}
        </span>
        <span className="text-[clamp(11px,1vw,15px)] tabular-nums text-plum-soft">
          {strikes}/{limit}
        </span>
      </span>
    </div>
  );
}


const turnTitle = (name: string): string => {
  if (/^bride/i.test(name)) return "Brides' Turn";
  if (/^groom/i.test(name)) return "Grooms' Turn";
  return `${name} — Turn`;
};

function FeudTurnCue({
  teamId,
  teamName,
  ended,
}: {
  teamId: string | null;
  teamName: string;
  ended: boolean;
}) {
  const [cue, setCue] = useState<string | null>(null);
  const previous = useRef<string | null>(null);

  useEffect(() => {
    if (!teamId || ended) return;
    if (previous.current === teamId) return;
    previous.current = teamId;
    setCue(turnTitle(teamName));
    const id = window.setTimeout(() => setCue(null), 1700);
    return () => window.clearTimeout(id);
  }, [teamId, teamName, ended]);

  if (!cue || ended) return null;
  return (
    <div
      key={cue}
      className="turn-cue pointer-events-none fixed inset-x-0 top-[16vh] z-30 flex justify-center"
      aria-live="polite"
    >
      <div className="turn-cue-card border border-gold/60 bg-lavender/95 px-[clamp(24px,3vw,48px)] py-[clamp(10px,1.6vh,20px)] text-center">
        <p className="text-[9px] uppercase tracking-[0.34em] text-gold-ink">Turn</p>
        <p className="mt-1 font-serif text-[clamp(26px,2.8vw,46px)] leading-none text-plum">{cue}</p>
      </div>
    </div>
  );
}

export function FeudBoard({ state }: { state: PublicState }) {
  const feud = state.feud;
  const question = state.question;
  if (!feud || !question) return null;

  const answers = question.answers ?? [];

  return (
    <div className="feud-board flex w-full flex-col gap-[clamp(16px,2.6vh,32px)]">
      <FeudTurnCue
        teamId={feud.ended ? null : feud.activeTeamId}
        teamName={labelFor(state, feud.activeTeamId)}
        ended={feud.ended}
      />
      <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-[clamp(16px,3vw,56px)] border-b border-gold/20 pb-[clamp(12px,1.8vh,20px)]">
        {state.teams[0] ? (
          <TeamScore
            team={state.teams[0]}
            score={state.scores.teams[state.teams[0].id] ?? 0}
            active={feud.activeTeamId === state.teams[0].id && !feud.ended}
            strikes={feud.activeTeamId === state.teams[0].id ? feud.strikes : 0}
            limit={feud.strikeLimit}
            align="left"
          />
        ) : null}

        <div className="grid justify-items-center gap-1 px-[clamp(8px,1.6vw,24px)] text-center">
          <span className="text-[10px] font-semibold uppercase tracking-[0.34em] text-gold-ink">
            Turn
          </span>
          <span
            key={feud.ended ? "done" : feud.activeTeamId}
            className="fade-in font-serif text-[clamp(24px,2.6vw,42px)] font-semibold leading-none text-plum"
          >
            {feud.ended ? "Round complete" : labelFor(state, feud.activeTeamId)}
          </span>
          <span
            className={`mt-1 flex items-baseline gap-2 border px-3 py-1 ${
              feud.strikes > 0 ? "border-gold bg-lavender-pale" : "border-gold/40"
            }`}
          >
            <span className="text-[9px] uppercase tracking-[0.26em] text-plum-hush">Strikes</span>
            <span className="font-serif text-[clamp(16px,1.7vw,28px)] leading-none tabular-nums text-gold-ink">
              {feud.strikes} / {feud.strikeLimit}
            </span>
          </span>
          <span className="text-[9px] uppercase tracking-[0.24em] text-plum-hush">
            Question {state.round}
          </span>
        </div>

        {state.teams[1] ? (
          <TeamScore
            team={state.teams[1]}
            score={state.scores.teams[state.teams[1].id] ?? 0}
            active={feud.activeTeamId === state.teams[1].id && !feud.ended}
            strikes={feud.activeTeamId === state.teams[1].id ? feud.strikes : 0}
            limit={feud.strikeLimit}
            align="right"
          />
        ) : null}
      </div>

      {feud.ended ? (
        <div className="feud-complete fade-up border border-gold/50 bg-lavender-pale px-[clamp(16px,2vw,32px)] py-[clamp(12px,1.6vh,20px)] text-center">
          <p className="text-[9px] uppercase tracking-[0.34em] text-gold-ink">Round complete</p>
          <p className="mt-1 font-serif text-[clamp(20px,2vw,32px)] leading-tight">
            Every answer is on the board
          </p>
          <ul className="mt-1 flex flex-wrap justify-center gap-x-5 gap-y-0.5 text-[clamp(10px,0.95vw,14px)] uppercase tracking-[0.14em] text-plum-soft">
            {state.teams.map((team) => (
              <li key={team.id}>
                {team.name}{" "}
                <b className="tabular-nums text-gold-ink">{feud.roundPoints[team.id] ?? 0}</b> this
                round<span className="text-plum-hush"> · </span>
                <b className="tabular-nums text-plum">{state.scores.teams[team.id] ?? 0}</b> total
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <h2 className="mx-auto max-w-[34ch] text-balance text-center font-serif text-[clamp(28px,3.1vw,54px)] font-medium leading-[1.18] text-plum">
        {question.text}
      </h2>
      {question.hindi ? (
        <p className="feud-question-hindi -mt-[clamp(6px,1.2vh,14px)] text-center font-serif text-[clamp(22px,2.4vw,40px)] italic text-plum-soft">
          {question.hindi}
        </p>
      ) : null}

      <ol className="grid grid-cols-1 gap-[clamp(8px,1.2vh,16px)] md:grid-cols-2">
        {answers.map((answer, index) => (
          <li
            key={answer.id}
            className={`answer fade-up ${answer.revealed ? "revealed" : "pending"}`}
            style={{ animationDelay: `${index * 40}ms` }}
          >
            <span className="answer-num">{index + 1}</span>
            <span className="answer-text">
              <span className="answer-english">{answer.text ?? ""}</span>
              {answer.revealed && answer.hindi ? (
                <span className="answer-hindi">{answer.hindi}</span>
              ) : null}
            </span>
            <span className="answer-pts">{answer.points ?? ""}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function HerdBoard({ state }: { state: PublicState }) {
  const question = state.question;
  const herd = state.herd;
  if (!question || !herd) return null;

  const result = herd.result;
  const cow = herd.pinkCow ? labelFor(state, herd.pinkCow) : "";

  return (
    <div className="flex w-full flex-col items-center gap-[clamp(18px,3vh,40px)]">
      <h2 className="mx-auto max-w-[32ch] text-balance text-center font-serif text-[clamp(30px,3.4vw,58px)] font-medium leading-[1.15]">
        {question.text}
      </h2>

      {!result ? (
        <div className="flex flex-col items-center gap-6">
          <p className="text-[11px] uppercase tracking-[0.42em] text-gold-ink">Answering</p>
          <p className="font-serif text-[clamp(40px,5vw,80px)] leading-none tabular-nums">
            {herd.answeredCount}
            <span className="text-plum-hush"> / {herd.totalPlayers}</span>
          </p>
          {cow ? (
            <p className="border border-gold/50 px-4 py-2 text-[10px] uppercase tracking-[0.28em] text-gold-ink">
              Pink Cow — {cow}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="flex w-full flex-col gap-3">
          {result.groups.map((group) => {
            const isWinner = result.winners.some((id) => group.participantIds.includes(id));
            return (
              <div
                key={group.key}
                className={`fade-up grid grid-cols-[auto_1fr_auto] items-center gap-5 border px-6 py-4 ${
                  isWinner
                    ? "border-gold bg-lavender-pale"
                    : "border-gold/25 bg-lavender-pale/40"
                }`}
              >
                <span className="font-serif text-[clamp(26px,2.6vw,40px)] leading-none tabular-nums text-gold-ink">
                  {group.participantIds.length}
                </span>
                <div>
                  <p className="font-serif text-[clamp(20px,1.9vw,32px)] leading-tight">
                    {group.label}
                  </p>
                  <p className="text-[clamp(11px,1.05vw,15px)] uppercase tracking-[0.16em] text-plum-hush">
                    {group.participantIds.map((id) => labelFor(state, id)).join(" · ")}
                  </p>
                </div>
                <span className="text-[10px] uppercase tracking-[0.24em] text-gold-ink">
                  {isWinner ? "Majority" : ""}
                </span>
              </div>
            );
          })}

          {result.tied && result.winners.length === 0 ? (
            <p className="text-center text-[11px] uppercase tracking-[0.3em] text-plum-hush">
              No unique majority — no points this round
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

export function MostLikelyBoard({ state }: { state: PublicState }) {
  const question = state.question;
  const ml = state.ml;
  if (!question || !ml) return null;

  const revealed = ml.revealed && ml.votes;
  const byId = new Map((ml.votes ?? []).map((row) => [row.participantId, row.votes]));

  return (
    <div className="flex w-full flex-col items-center gap-[clamp(18px,3vh,40px)]">
      <h2 className="mx-auto max-w-[30ch] text-balance text-center font-serif text-[clamp(30px,3.4vw,58px)] font-medium leading-[1.15]">
        {question.text}
      </h2>

      {!revealed ? (
        <p className="text-[11px] uppercase tracking-[0.42em] text-gold-ink">
          {ml.voteCount > 0 ? `${ml.voteCount} votes in` : "Voting"}
        </p>
      ) : null}

      <div className="grid w-full grid-cols-2 gap-3 md:grid-cols-4">
        {state.participants.map((person) => {
          const isWinner = ml.winners.includes(person.id);
          return (
            <div
              key={person.id}
              className={`flex flex-col items-center gap-2 border px-4 py-5 text-center transition-colors ${
                revealed && isWinner
                  ? "border-gold bg-lavender-pale"
                  : "border-gold/25 bg-lavender-pale/40"
              }`}
            >
              <span className="font-serif text-[clamp(18px,1.7vw,28px)] leading-tight">
                {person.name}
              </span>
              {revealed ? (
                <>
                  <span className="text-[clamp(28px,3vw,46px)] font-medium leading-none tabular-nums text-gold-ink">
                    {byId.get(person.id) ?? 0}
                  </span>
                  <span className="text-[9px] uppercase tracking-[0.24em] text-plum-hush">
                    {isWinner ? "Most likely" : "votes"}
                  </span>
                </>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PriceBoard({ state }: { state: PublicState }) {
  const question = state.question;
  const pir = state.pir;
  if (!question || !pir) return null;

  if (pir.party) {
    return <PartyPriceBoard state={state} pir={pir} party={pir.party} />;
  }

  const guessRows = (pir.guesses ?? []).map((row) => ({
    ...row,
    label: labelFor(state, row.entityId),
  }));
  const currency = question.currency ?? "INR";

  return (
    <div className="grid w-full items-center gap-[clamp(20px,3vw,56px)] md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="border border-gold/30 bg-lavender-pale p-4">
        <img
          src={publicAsset(question.image ?? "demo/placeholder.svg")}
          alt={question.text}
          className="mx-auto block max-h-[min(52vh,460px)] w-full object-contain"
        />
      </div>

      <div className="flex flex-col gap-5">
        <div>
          <h2 className="font-serif text-[clamp(28px,3vw,50px)] font-medium leading-[1.15]">
            {question.text}
          </h2>
          {question.size ? (
            <p className="mt-1 text-[clamp(12px,1.1vw,17px)] uppercase tracking-[0.18em] text-gold-ink">
              {question.size}
            </p>
          ) : null}
          <p className="mt-2 text-[clamp(14px,1.2vw,19px)] text-plum-soft">{question.description}</p>
        </div>

        {guessRows.length > 0 ? (
          <ul className="grid gap-2">
            {guessRows.map((row) => (
              <li
                key={row.entityId}
                className={`flex items-baseline justify-between border px-4 py-2 ${
                  pir.winners.includes(row.entityId)
                    ? "border-gold bg-lavender-pale"
                    : "border-gold/25"
                }`}
              >
                <span className="text-[clamp(15px,1.3vw,21px)]">{row.label}</span>
                <span className="text-[clamp(17px,1.5vw,24px)] tabular-nums text-gold-ink">
                  {row.value === null ? "—" : moneyLabel(row.value, currency)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[11px] uppercase tracking-[0.32em] text-gold-ink">
            {pir.locked ? "Guesses locked" : "Taking guesses"}
          </p>
        )}

        {pir.priceRevealed ? (
          <div className="fade-up border-t border-gold/30 pt-4">
            <p className="text-[10px] uppercase tracking-[0.3em] text-plum-hush">Actual price</p>
            <p className="font-serif text-[clamp(40px,4.4vw,72px)] leading-none text-gold-display">
              {moneyLabel(question.actualPrice ?? 0, currency)}
            </p>
            {pir.winners.length > 0 ? (
              <p className="mt-2 text-[12px] uppercase tracking-[0.24em] text-gold-ink">
                {pir.winners.map((id) => labelFor(state, id)).join(" · ")}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function PartyJoinCard({
  state,
  party,
  compact = false,
}: {
  state: PublicState;
  party: NonNullable<PublicPrice["party"]>;
  compact?: boolean;
}) {
  const [qr, setQr] = useState<string | null>(null);
  const joinUrl = `${window.location.origin}${import.meta.env.BASE_URL}join/?code=${state.code}`;

  useEffect(() => {
    let active = true;
    // QR codes are only needed while phones can join; the library stays out
    // of the default bundle.
    void import("qrcode")
      .then((module) =>
        module.toString(joinUrl, {
          type: "svg",
          margin: 1,
          width: 240,
          color: { dark: "#392747", light: "#00000000" },
        }),
      )
      .then((svg) => {
        if (active) setQr(svg);
      })
      .catch(() => setQr(null));
    return () => {
      active = false;
    };
  }, [joinUrl]);

  return (
    <div
      className={`flex items-center gap-4 border border-gold/40 bg-lavender-pale/50 p-3 ${
        compact ? "justify-center" : ""
      }`}
    >
      {qr ? (
        <div
          className="qr h-[150px] w-[150px] shrink-0"
          aria-hidden="true"
          dangerouslySetInnerHTML={{ __html: qr }}
        />
      ) : null}
      <div className="min-w-0">
        <p className="text-[9px] uppercase tracking-[0.3em] text-gold-ink">Scan to join</p>
        <p className="mt-1 font-serif text-[clamp(20px,1.8vw,30px)] leading-none">{state.code}</p>
        <p className="mt-1 text-[10px] uppercase tracking-[0.18em] text-plum-soft">
          {party.mode === "teams" ? "3 teams · one phone each" : "6 players · one phone each"}
        </p>
        <p className="mt-1 break-all text-[10px] leading-snug text-plum-hush">{joinUrl}</p>
      </div>
    </div>
  );
}

function PartyPriceBoard({
  state,
  pir,
  party,
}: {
  state: PublicState;
  pir: PublicPrice;
  party: NonNullable<PublicPrice["party"]>;
}) {
  const question = state.question!;
  const currency = question.currency ?? "INR";
  const showJoin = !party.locked && !party.priceRevealed;
  const submitted = party.teams.filter((team) => team.submitted).length;
  const podiumRank = (entryId: string) =>
    party.podium.find((entry) => entry.entryId === entryId && entry.rank <= 3);

  const guesses = [...(party.guesses ?? [])].sort((a, b) => {
    const left = party.teams.find((team) => team.id === a.teamId)?.name ?? "";
    const right = party.teams.find((team) => team.id === b.teamId)?.name ?? "";
    if (party.leaderboardRevealed) {
      const rankA = party.podium.find((entry) => entry.entryId === a.teamId)?.rank ?? 99;
      const rankB = party.podium.find((entry) => entry.entryId === b.teamId)?.rank ?? 99;
      return rankA - rankB || left.localeCompare(right);
    }
    return left.localeCompare(right);
  });
  const leaderboard = [...party.teams]
    .map((team) => ({ id: team.id, name: team.name, score: party.scores[team.id] ?? 0 }))
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));

  return (
    <div className="grid w-full items-start gap-[clamp(18px,2.6vw,48px)] md:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)]">
      <div className="flex flex-col gap-3">
        <div className="border border-gold/30 bg-lavender-pale p-3">
          <img
            src={publicAsset(question.image ?? "demo/placeholder.svg")}
            alt={question.text}
            className="mx-auto block max-h-[min(46vh,400px)] w-full object-contain"
          />
        </div>

        {showJoin ? <PartyJoinCard state={state} party={party} /> : null}
      </div>

      <div className="party-detail flex flex-col gap-4">
        <div>
          <h2 className="party-title font-serif text-[clamp(26px,2.8vw,46px)] font-medium leading-[1.15]">
            {question.text}
          </h2>
          {question.size ? (
            <p className="mt-1 text-[clamp(11px,1.05vw,16px)] uppercase tracking-[0.18em] text-gold-ink">
              {question.size}
            </p>
          ) : null}
          <p className="mt-2 text-[clamp(13px,1.15vw,18px)] text-plum-soft">{question.description}</p>
        </div>

        <div className="party-meta flex flex-wrap items-baseline gap-4 border-y border-gold/25 py-3">
          <span className="text-[10px] uppercase tracking-[0.24em] text-plum-hush">Submissions</span>
          <span className="party-meta-count font-serif text-[clamp(22px,2.2vw,34px)] leading-none tabular-nums">
            {submitted} <span className="text-plum-hush">of {party.teams.length}</span>
          </span>
          <span className="text-[10px] uppercase tracking-[0.24em] text-gold-ink">
            {party.locked ? "Locked" : "Open"}
          </span>
        </div>

        {party.leaderboardRevealed && guesses.length > 0 ? (
          <p className="text-[9px] uppercase tracking-[0.3em] text-gold-ink">Podium</p>
        ) : null}

        {guesses.length > 0 ? (
          <ul className="party-rows grid gap-1">
            {guesses.map((guess) => {
              const team = party.teams.find((entry) => entry.id === guess.teamId);
              const rank = podiumRank(guess.teamId);
              return (
                <li
                  key={guess.teamId}
                  className={`party-row flex items-baseline justify-between border px-4 py-1.5 ${
                    rank ? "border-gold bg-lavender-pale" : "border-gold/25"
                  }`}
                >
                  <span className="text-[clamp(16px,1.6vw,24px)]">
                    {rank ? `${rank.rank}. ` : ""}
                    {team?.name ?? guess.teamId}
                  </span>
                  <span className="text-[clamp(18px,1.8vw,28px)] tabular-nums text-gold-ink">
                    {moneyLabel(guess.value, currency)}
                    {rank ? ` · +${rank.points}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-[11px] uppercase tracking-[0.28em] text-plum-hush">
            {party.locked ? "Guesses locked" : "Guesses stay hidden until the reveal"}
          </p>
        )}

        {pir.priceRevealed ? (
          <div className="fade-up border-t border-gold/30 pt-3">
            <p className="text-[10px] uppercase tracking-[0.28em] text-plum-hush">Actual price</p>
            <p className="font-serif text-[clamp(34px,3.8vw,62px)] leading-none text-gold-display">
              {moneyLabel(question.actualPrice ?? 0, currency)}
            </p>
          </div>
        ) : null}

        {party.priceRevealed && !party.leaderboardRevealed ? (
          <p className="text-[11px] uppercase tracking-[0.28em] text-plum-hush">
            Leaderboard next
          </p>
        ) : null}

        {party.leaderboardRevealed && leaderboard.length > 0 ? (
          <div className="border border-gold/30 px-4 py-2.5">
            <p className="text-[9px] uppercase tracking-[0.3em] text-plum-hush">
              {party.mode === "teams" ? "Team scores" : "Player scores"}
            </p>
            <ul
              className={`mt-1.5 grid gap-x-8 gap-y-0.5 ${
                leaderboard.length > 3 ? "grid-cols-2" : "grid-cols-1"
              }`}
            >
              {leaderboard.map((team) => (
                <li key={team.id} className="flex items-baseline justify-between gap-2">
                  <span className="text-[clamp(13px,1.25vw,19px)]">{team.name}</span>
                  <span className="text-[clamp(16px,1.6vw,24px)] tabular-nums text-gold-ink">
                    {team.score}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function GameBoard({ state }: { state: PublicState }) {
  const game: GameId | null = state.game;
  if (game === "family_feud") return <FeudBoard state={state} />;
  if (game === "herd_mentality") return <HerdBoard state={state} />;
  if (game === "whos_most_likely") return <MostLikelyBoard state={state} />;
  if (game === "price_is_right") return <PriceBoard state={state} />;
  return null;
}

function moneyLabel(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${currency} ${value.toLocaleString("en-IN")}`;
  }
}

export function nameFor(state: PublicState, id: string | null): string {
  return labelFor(state, id);
}

export function scoreRows(state: PublicState): { label: string; points: number }[] {
  if (state.game === "family_feud" && state.teams.length > 0) {
    return state.teams.map((team) => ({
      label: team.name,
      points: state.scores.teams[team.id] ?? 0,
    }));
  }
  return state.participants.map((person: Participant) => ({
    label: person.name,
    points: state.scores.participants[person.id] ?? 0,
  }));
}

/* Audience boards. Everything here reads PublicState only — hidden answers,
   prices and tallies never reach this code path. */

import { useEffect, useState } from "react";
import type { GameId, Participant, PublicState, PublicPrice, Team } from "../lib/types";
import { StrikeMark } from "../components/Mandala";

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
        On the board
      </span>
      <span className="font-serif text-[clamp(16px,1.35vw,26px)] font-medium uppercase tracking-[0.2em] text-plum-soft">
        {team.name}
      </span>
      <span className="text-[clamp(46px,4.6vw,80px)] font-medium leading-none tabular-nums text-plum">
        {score}
      </span>
      <span className="mt-1 flex gap-2">
        {Array.from({ length: limit }, (_, index) => (
          <StrikeMark key={index} on={index < strikes} />
        ))}
      </span>
    </div>
  );
}

export function FeudBoard({ state }: { state: PublicState }) {
  const feud = state.feud;
  const question = state.question;
  if (!feud || !question) return null;

  const answers = question.answers ?? [];
  const outcome = feud.ended ? feud.outcome : null;
  const winnerName = feud.awardedTo ? labelFor(state, feud.awardedTo) : "";

  return (
    <div className="flex w-full flex-col gap-[clamp(16px,2.6vh,32px)]">
      <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-[clamp(16px,3vw,56px)] border-b border-gold/20 pb-[clamp(12px,1.8vh,20px)]">
        {state.teams[0] ? (
          <TeamScore
            team={state.teams[0]}
            score={state.scores.teams[state.teams[0].id] ?? 0}
            active={feud.activeTeamId === state.teams[0].id && !feud.ended}
            strikes={feud.strikes[state.teams[0].id] ?? 0}
            limit={feud.strikeLimit}
            align="left"
          />
        ) : null}

        <div className="grid justify-items-center gap-0.5 px-[clamp(10px,2vw,30px)]">
          <span className="text-[9px] uppercase tracking-[0.34em] text-plum-hush">Round pot</span>
          <span className="font-serif text-[clamp(30px,3vw,50px)] leading-none text-gold-display">
            {feud.pot}
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
            strikes={feud.strikes[state.teams[1].id] ?? 0}
            limit={feud.strikeLimit}
            align="right"
          />
        ) : null}
      </div>

      {outcome ? (
        <div className="fade-up border border-gold/50 bg-lavender-pale px-[clamp(16px,2vw,32px)] py-[clamp(12px,1.6vh,20px)] text-center">
          <p className="text-[9px] uppercase tracking-[0.34em] text-gold-ink">Round complete</p>
          <p className="mt-1 font-serif text-[clamp(20px,2vw,32px)] leading-tight">
            {outcome.winnerTeamId
              ? `${labelFor(state, outcome.winnerTeamId)} takes the pot`
              : "Tied on points — the host decides"}
          </p>
          <p className="mt-1 text-[clamp(11px,1.05vw,15px)] uppercase tracking-[0.16em] text-plum-soft">
            {state.teams
              .map((team) => `${team.name} ${outcome.credited[team.id] ?? 0}`)
              .join("  ·  ")}
            {feud.awarded && winnerName ? `  ·  ${winnerName} +${feud.pot}` : ""}
          </p>
        </div>
      ) : null}

      <h2 className="mx-auto max-w-[34ch] text-balance text-center font-serif text-[clamp(28px,3.1vw,54px)] font-medium leading-[1.18] text-plum">
        {question.text}
      </h2>

      <ol className="grid grid-cols-1 gap-[clamp(8px,1.2vh,16px)] md:grid-cols-2">
        {answers.map((answer, index) => (
          <li
            key={answer.id}
            className={`answer fade-up ${answer.revealed ? "revealed" : "pending"}`}
            style={{ animationDelay: `${index * 40}ms` }}
          >
            <span className="answer-num">{index + 1}</span>
            <span className="answer-text">{answer.text ?? ""}</span>
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
          src={question.image ?? "/demo/placeholder.svg"}
          alt={question.text}
          className="mx-auto block w-full max-w-[520px]"
        />
      </div>

      <div className="flex flex-col gap-5">
        <div>
          <h2 className="font-serif text-[clamp(28px,3vw,50px)] font-medium leading-[1.15]">
            {question.text}
          </h2>
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
  const [qr, setQr] = useState<string | null>(null);
  const showJoin = !party.locked && !party.priceRevealed;
  const joinUrl = `${window.location.origin}${import.meta.env.BASE_URL}join/?code=${state.code}`;
  const submitted = party.teams.filter((team) => team.submitted).length;

  useEffect(() => {
    if (!showJoin) {
      setQr(null);
      return;
    }
    let active = true;
    // QR codes are only needed while phones can join; the library stays out
    // of the default bundle.
    void import("qrcode")
      .then((module) =>
        module.toString(joinUrl, {
          type: "svg",
          margin: 1,
          width: 200,
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
  }, [joinUrl, showJoin]);

  const guesses = [...(party.guesses ?? [])].sort((a, b) => {
    const left = party.teams.find((team) => team.id === a.teamId)?.name ?? "";
    const right = party.teams.find((team) => team.id === b.teamId)?.name ?? "";
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
            src={question.image ?? "/demo/placeholder.svg"}
            alt={question.text}
            className="mx-auto block w-full max-w-[420px]"
          />
        </div>

        {showJoin ? (
          <div className="flex items-center gap-4 border border-gold/40 bg-lavender-pale/50 p-3">
            {qr ? (
              <div
                className="qr h-[110px] w-[110px] shrink-0"
                aria-hidden="true"
                dangerouslySetInnerHTML={{ __html: qr }}
              />
            ) : null}
            <div className="min-w-0">
              <p className="text-[9px] uppercase tracking-[0.3em] text-gold-ink">Scan to join</p>
              <p className="mt-1 font-serif text-[clamp(20px,1.8vw,30px)] leading-none">
                {state.code}
              </p>
              <p className="mt-1 break-all text-[10px] leading-snug text-plum-hush">{joinUrl}</p>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-4">
        <div>
          <h2 className="font-serif text-[clamp(26px,2.8vw,46px)] font-medium leading-[1.15]">
            {question.text}
          </h2>
          <p className="mt-2 text-[clamp(13px,1.15vw,18px)] text-plum-soft">{question.description}</p>
        </div>

        <div className="flex flex-wrap items-baseline gap-4 border-y border-gold/25 py-3">
          <span className="text-[10px] uppercase tracking-[0.24em] text-plum-hush">Submissions</span>
          <span className="font-serif text-[clamp(22px,2.2vw,34px)] leading-none tabular-nums">
            {submitted} <span className="text-plum-hush">of {party.teams.length}</span>
          </span>
          <span className="text-[10px] uppercase tracking-[0.24em] text-gold-ink">
            {party.locked ? "Locked" : "Open"}
          </span>
        </div>

        {guesses.length > 0 ? (
          <ul className="grid gap-1.5">
            {guesses.map((guess) => {
              const team = party.teams.find((entry) => entry.id === guess.teamId);
              const isWinner = party.winners.includes(guess.teamId);
              return (
                <li
                  key={guess.teamId}
                  className={`flex items-baseline justify-between border px-4 py-2 ${
                    isWinner ? "border-gold bg-lavender-pale" : "border-gold/25"
                  }`}
                >
                  <span className="text-[clamp(16px,1.6vw,24px)]">{team?.name ?? guess.teamId}</span>
                  <span className="text-[clamp(18px,1.8vw,28px)] tabular-nums text-gold-ink">
                    {moneyLabel(guess.value, currency)}
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

        {party.priceRevealed && leaderboard.length > 0 ? (
          <div className="border border-gold/30 px-4 py-3">
            <p className="text-[9px] uppercase tracking-[0.3em] text-plum-hush">Team scores</p>
            <ul className="mt-2 grid gap-1">
              {leaderboard.map((team) => (
                <li key={team.id} className="flex items-baseline justify-between">
                  <span className="text-[clamp(14px,1.4vw,22px)]">{team.name}</span>
                  <span className="text-[clamp(20px,2.1vw,32px)] tabular-nums text-gold-ink">
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

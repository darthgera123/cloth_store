/* Host game controls. Everything here is private to the host: full answer
   lists, prices, tallies and per-player data. */

import { useEffect, useRef, useState } from "react";
import { herdGroups } from "../lib/herd";
import type { PricePartyApi } from "../multiplayer/usePriceParty";
import { firebaseConfigured } from "../multiplayer/config";
import {
  GAME_LABEL,
  type Action,
  type FeudQuestion,
  type HerdQuestion,
  type MostLikelyQuestion,
  type PriceQuestion,
  type Question,
  type SessionState,
} from "../lib/types";

type Send = (action: Action) => void;

function TextField({
  value,
  onCommit,
  label,
  placeholder,
  disabled = false,
}: {
  value: string;
  onCommit: (value: string) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => setDraft(value), [value]);

  const commit = (next: string) => {
    window.clearTimeout(timer.current);
    if (next !== value) onCommit(next);
  };

  return (
    <input
      className="field"
      aria-label={label}
      placeholder={placeholder}
      disabled={disabled}
      value={draft}
      onChange={(event) => {
        const next = event.target.value;
        setDraft(next);
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => commit(next), 600);
      }}
      onBlur={() => commit(draft)}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit(draft);
      }}
    />
  );
}

function NumberField({
  value,
  onCommit,
  label,
  step = 1,
}: {
  value: number;
  onCommit: (value: number) => void;
  label: string;
  step?: number;
}) {
  const [draft, setDraft] = useState(String(value));

  useEffect(() => setDraft(String(value)), [value]);

  const commit = (raw: string) => {
    const parsed = Math.max(0, Math.round(Number(raw) || 0));
    if (parsed !== value) onCommit(parsed);
    setDraft(String(parsed));
  };

  return (
    <input
      className="num-field"
      type="number"
      inputMode="numeric"
      min={0}
      step={step}
      aria-label={label}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={(event) => commit(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit((event.target as HTMLInputElement).value);
      }}
    />
  );
}

function Footer({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2 border-t border-gold/20 pt-3">{children}</div>
  );
}

function Meta({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] uppercase tracking-[0.22em] text-plum-hush">{children}</span>
  );
}

/* ---------- Family Feud ---------- */

export function FeudPanel({
  session,
  questions,
  send,
}: {
  session: SessionState;
  questions: Question[];
  send: Send;
}) {
  const feud = session.feud;
  const question = questions.find((q) => q.id === feud?.questionId) as FeudQuestion | undefined;
  if (!feud || !question) {
    return <p className="text-[13px] text-plum-soft">No Feud round in progress.</p>;
  }

  const potValue = feud.pot * session.config.roundMultiplier;
  const open = session.phase === "QUESTION_ACTIVE" && !feud.ended;
  const teamName = (id: string | null | undefined) =>
    session.teams.find((team) => team.id === id)?.name ?? "";
  const outcome = feud.outcome;
  const limit = session.config.strikeLimit;

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <span className="hbtn pointer-events-none">Question {session.round}</span>
        <span className="hbtn pointer-events-none border-gold bg-lavender-pale">
          Round pot {potValue}
        </span>
        <span className="hbtn pointer-events-none">
          Starts: {teamName(feud.startingTeamId)}
        </span>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border border-gold/30 bg-lavender-pale/50 px-4 py-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.22em] text-plum-hush">Guessing now</p>
          <p className="font-serif text-[24px] leading-tight">
            {feud.ended ? "Round complete" : teamName(feud.activeTeamId)}
          </p>
        </div>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={!open}
          onClick={() => send({ type: "feud_strike", delta: 1 })}
        >
          Wrong guess · strike
        </button>
      </div>

      <ul className="grid gap-2">
        {question.answers.map((answer, index) => {
          const revealed = feud.revealed.includes(answer.id);
          const claimedBy = feud.credited[answer.id];
          return (
            <li key={answer.id}>
              <button
                type="button"
                disabled={revealed || !open}
                onClick={() => send({ type: "feud_reveal", answerId: answer.id })}
                className={`flex w-full items-center gap-3 border px-3 py-2.5 text-left transition-colors ${
                  revealed ? "border-gold bg-lavender-pale" : "border-gold/25 hover:bg-lavender-pale/60"
                } disabled:cursor-default`}
              >
                <span className="w-5 text-center font-serif text-[15px] text-gold-ink">
                  {index + 1}
                </span>
                <span className="flex-1 text-[15px]">{answer.text}</span>
                {revealed ? (
                  <span className="text-[9px] uppercase tracking-[0.14em] text-plum-hush">
                    {teamName(claimedBy)}
                  </span>
                ) : null}
                <span className="text-[15px] font-semibold tabular-nums text-gold-ink">
                  {answer.points}
                </span>
                <span className="w-14 text-right text-[9px] uppercase tracking-[0.16em] text-plum-hush">
                  {revealed ? "Shown" : "Hidden"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {session.teams.map((team) => {
          const strikes = feud.strikes[team.id] ?? 0;
          const isOut = strikes >= limit;
          return (
            <div
              key={team.id}
              className={`border p-3 ${isOut ? "border-gold bg-lavender-pale/60" : "border-gold/25"}`}
            >
              <div className="mb-2 flex items-center justify-between">
                <Meta>
                  {team.name} · {isOut ? "out of the round" : `${strikes}/${limit} strikes`}
                </Meta>
                <div className="flex gap-1">
                  <button
                    className="hbtn"
                    type="button"
                    aria-label={`Remove a strike from ${team.name}`}
                    disabled={strikes === 0 || !open}
                    onClick={() => send({ type: "feud_strike", delta: -1, teamId: team.id })}
                  >
                    −
                  </button>
                </div>
              </div>
              <div className="flex gap-2">
                {Array.from({ length: limit }, (_, index) => (
                  <span
                    key={index}
                    className={`grid h-8 w-8 place-items-center border ${
                      index < strikes ? "border-gold bg-lavender-pale" : "border-gold/25"
                    }`}
                  >
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      className="h-4 w-4 text-gold"
                    >
                      <path
                        d="M5 5l14 14M19 5L5 19"
                        strokeWidth="2"
                        opacity={index < strikes ? 1 : 0.25}
                      />
                    </svg>
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {feud.ended && outcome ? (
        <div className="mt-4 border border-gold bg-lavender-pale p-4">
          <Meta>
            Round over ·{" "}
            {outcome.reason === "answers_exhausted"
              ? "all answers revealed"
              : outcome.reason === "both_eliminated"
                ? "both teams out"
                : "one team left standing"}
          </Meta>
          <div className="mt-2 flex flex-wrap gap-4">
            {session.teams.map((team) => (
              <span key={team.id} className="text-[13px]">
                {team.name}:{" "}
                <b className="tabular-nums text-gold-ink">{outcome.credited[team.id] ?? 0}</b>
              </span>
            ))}
          </div>

          {feud.awarded ? (
            <p className="mt-3 text-[12px] uppercase tracking-[0.16em] text-gold-ink">
              Pot of {potValue} awarded to {teamName(feud.awardedTo)}
            </p>
          ) : outcome.tied ? (
            <div className="mt-3">
              <p className="text-[12px] text-plum-soft">
                Revealed points are level — choose who takes the pot.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {session.teams.map((team) => (
                  <button
                    key={team.id}
                    className="hbtn hbtn-solid"
                    type="button"
                    onClick={() => send({ type: "feud_award", teamId: team.id })}
                  >
                    Award {potValue} to {team.name}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <button
              className="hbtn hbtn-solid mt-3"
              type="button"
              onClick={() => send({ type: "feud_award" })}
            >
              Award pot · {potValue} to {teamName(outcome.winnerTeamId)}
            </button>
          )}
        </div>
      ) : null}

      <Footer>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase !== "REVEAL"}
          onClick={() => send({ type: "round_result" })}
        >
          Show round result
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "ROUND_RESULT" || !feud.awarded}
          onClick={() => send({ type: "next_round" })}
        >
          Next question
        </button>
        {!feud.ended ? (
          <span className="self-center text-[11px] text-plum-hush">
            The round ends when the board is clear or both teams are out.
          </span>
        ) : null}
      </Footer>
    </div>
  );
}

/* ---------- Herd Mentality ---------- */

export function HerdPanel({
  session,
  questions,
  send,
}: {
  session: SessionState;
  questions: Question[];
  send: Send;
}) {
  const herd = session.herd;
  const question = questions.find((q) => q.id === herd?.questionId) as HerdQuestion | undefined;
  if (!herd || !question) return <p className="text-[13px] text-plum-soft">No herd round in progress.</p>;

  const groups = herdGroups(herd, session.participants);
  const answered = Object.values(herd.answers).filter((answer) => answer.trim()).length;
  const editable = session.phase !== "REVEAL" && session.phase !== "ROUND_RESULT";

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <span className="hbtn pointer-events-none">{answered} of {session.participants.length} answered</span>
        <span className="hbtn pointer-events-none">{groups.length} groups</span>
        {herd.awarded ? (
          <span className="hbtn pointer-events-none border-gold bg-lavender-pale">Scored</span>
        ) : null}
      </div>

      <div className="grid gap-2">
        {session.participants.map((person) => (
          <label key={person.id} className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3">
            <span className="truncate text-[12px] uppercase tracking-[0.12em] text-plum-soft">
              {person.name}
            </span>
            <TextField
              label={`Answer for ${person.name}`}
              value={herd.answers[person.id] ?? ""}
              placeholder="Their answer"
              disabled={!editable}
              onCommit={(text) =>
                send({ type: "herd_set_answer", participantId: person.id, text })
              }
            />
          </label>
        ))}
      </div>

      <div className="mt-5">
        <Meta>Groups — merge duplicates the room agrees on</Meta>
        <ul className="mt-2 grid gap-1.5">
          {groups.map((group) => {
            const isWinner =
              groups.length > 0 && group.participantIds.length === groups[0]?.participantIds.length;
            return (
              <li
                key={group.key}
                className={`flex flex-wrap items-center gap-2 border px-3 py-2 ${
                  isWinner ? "border-gold bg-lavender-pale/60" : "border-gold/20"
                }`}
              >
                <span className="min-w-6 text-center font-serif text-[16px] text-gold-ink">
                  {group.participantIds.length}
                </span>
                <span className="flex-1 text-[14px]">{group.label}</span>
                <span className="text-[10px] uppercase tracking-[0.12em] text-plum-hush">
                  {group.participantIds
                    .map((id) => session.participants.find((p) => p.id === id)?.name ?? "")
                    .join(", ")}
                </span>
                <select
                  className="hbtn"
                  aria-label={`Merge ${group.label} into another group`}
                  value=""
                  disabled={!editable || groups.length < 2}
                  onChange={(event) => {
                    if (!event.target.value) return;
                    send({ type: "herd_merge", from: group.key, to: event.target.value });
                  }}
                >
                  <option value="">Merge into…</option>
                  {groups
                    .filter((other) => other.key !== group.key)
                    .map((other) => (
                      <option key={other.key} value={other.key}>
                        {other.label}
                      </option>
                    ))}
                </select>
                {herd.merges[group.key] || Object.values(herd.merges).includes(group.key) ? (
                  <button
                    className="hbtn"
                    type="button"
                    disabled={!editable}
                    onClick={() => send({ type: "herd_unmerge", key: group.key })}
                  >
                    Split
                  </button>
                ) : null}
              </li>
            );
          })}
          {groups.length === 0 ? <li className="text-[13px] text-plum-soft">No answers yet.</li> : null}
        </ul>
      </div>

      {session.config.pinkCowEnabled ? (
        <div className="mt-4 border border-gold/25 p-3">
          <Meta>Pink Cow {session.config.pinkCowBlocksWin ? "(blocks winning)" : ""}</Meta>
          <select
            className="field mt-2"
            aria-label="Pink Cow holder"
            value={herd.pinkCow ?? ""}
            onChange={(event) =>
              send({
                type: "herd_set_pink_cow",
                participantId: event.target.value || null,
              })
            }
          >
            <option value="">Nobody</option>
            {session.participants.map((person) => (
              <option key={person.id} value={person.id}>
                {person.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      <Footer>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase !== "QUESTION_ACTIVE"}
          onClick={() => send({ type: "begin_answering" })}
        >
          Start answering
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase === "REVEAL" || session.phase === "ROUND_RESULT"}
          onClick={() => send({ type: "reveal" })}
        >
          Reveal majority
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "REVEAL"}
          onClick={() => send({ type: "round_result" })}
        >
          Round result
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "ROUND_RESULT"}
          onClick={() => send({ type: "next_round" })}
        >
          Next question
        </button>
      </Footer>
    </div>
  );
}

/* ---------- Who's Most Likely ---------- */

export function MostLikelyPanel({
  session,
  questions,
  send,
}: {
  session: SessionState;
  questions: Question[];
  send: Send;
}) {
  const ml = session.ml;
  const question = questions.find((q) => q.id === ml?.questionId) as MostLikelyQuestion | undefined;
  if (!ml || !question) return <p className="text-[13px] text-plum-soft">No round in progress.</p>;

  const votable = session.phase !== "REVEAL" && session.phase !== "ROUND_RESULT";
  const total = Object.values(ml.votes).reduce((sum, votes) => sum + votes, 0);

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <span className="hbtn pointer-events-none">{total} votes</span>
        <span className="hbtn pointer-events-none">{session.config.mlMode} mode</span>
        {ml.revealed ? (
          <span className="hbtn pointer-events-none border-gold bg-lavender-pale">
            {ml.winners.length > 1 ? "Tie" : "Revealed"}
          </span>
        ) : null}
      </div>

      <ul className="grid gap-2">
        {session.participants.map((person) => (
          <li
            key={person.id}
            className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3"
          >
            <span className="truncate text-[12px] uppercase tracking-[0.12em] text-plum-soft">
              {person.name}
            </span>
            <div className="flex items-center gap-2">
              <button
                className="hbtn"
                type="button"
                disabled={!votable}
                aria-label={`Remove a vote for ${person.name}`}
                onClick={() =>
                  send({
                    type: "ml_set_votes",
                    participantId: person.id,
                    votes: Math.max(0, (ml.votes[person.id] ?? 0) - 1),
                  })
                }
              >
                −
              </button>
              <div className="w-[72px]">
                <NumberField
                  label={`Votes for ${person.name}`}
                  value={ml.votes[person.id] ?? 0}
                  onCommit={(votes) =>
                    send({ type: "ml_set_votes", participantId: person.id, votes })
                  }
                />
              </div>
              <button
                className="hbtn"
                type="button"
                disabled={!votable}
                aria-label={`Add a vote for ${person.name}`}
                onClick={() =>
                  send({
                    type: "ml_set_votes",
                    participantId: person.id,
                    votes: Math.min(8, (ml.votes[person.id] ?? 0) + 1),
                  })
                }
              >
                +
              </button>
            </div>
          </li>
        ))}
      </ul>

      <Footer>
        <button
          className="hbtn"
          type="button"
          disabled={!votable}
          onClick={() => send({ type: "ml_clear_votes" })}
        >
          Clear votes
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase !== "QUESTION_ACTIVE"}
          onClick={() => send({ type: "begin_answering" })}
        >
          Start voting
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={!votable}
          onClick={() => send({ type: "reveal" })}
        >
          Reveal result
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "REVEAL"}
          onClick={() => send({ type: "round_result" })}
        >
          Round result
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "ROUND_RESULT"}
          onClick={() => send({ type: "next_round" })}
        >
          Next question
        </button>
      </Footer>
    </div>
  );
}

/* ---------- The Price Is Right ---------- */

export function PricePanel({
  session,
  questions,
  send,
  party,
}: {
  session: SessionState;
  questions: Question[];
  send: Send;
  party: PricePartyApi;
}) {
  const pir = session.pir;
  const question = questions.find((q) => q.id === pir?.questionId) as PriceQuestion | undefined;
  if (!pir || !question) return <p className="text-[13px] text-plum-soft">No price round in progress.</p>;

  if (pir.party) {
    return <PartyPricePanel session={session} question={question} send={send} party={party} />;
  }

  const phonesAvailable = firebaseConfigured();
  const phoneModeOff = session.config.pirPhoneMode === "off";

  const entities = session.participants.map((person) => ({
    id: person.id,
    name: person.name,
  }));

  const open = session.phase === "QUESTION_ACTIVE" && !pir.locked;

  return (
    <div>
      {phonesAvailable && phoneModeOff ? (
        <p className="mb-3 border border-gold/40 bg-lavender-pale px-3 py-2 text-[12px] text-plum-soft">
          Phone players are off — every guess is typed here. Set <b>Phone players</b> to 3 teams or
          6 players in setup before starting the game to let guests join from their phones.
        </p>
      ) : null}
      <div className="mb-3 flex flex-wrap gap-2">
        <span className="hbtn pointer-events-none">Actual {formatMoney(question.actualPrice, question.currency)}</span>
        <span className="hbtn pointer-events-none">Host entry</span>
        {pir.locked ? <span className="hbtn pointer-events-none border-gold">Locked</span> : null}
      </div>

      <div className="mb-3 flex gap-3 border border-gold/25 p-3">
        <img
          src={question.image}
          alt=""
          className="h-20 w-24 border border-gold/20 bg-lavender-pale object-cover"
        />
        <div>
          <p className="font-serif text-[19px]">{question.item}</p>
          <p className="text-[12px] text-plum-soft">{question.description}</p>
        </div>
      </div>

      <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {entities.map((entity) => (
          <li key={entity.id} className="grid grid-cols-[110px_140px] items-center gap-3">
            <span className="truncate text-[12px] uppercase tracking-[0.12em] text-plum-soft">
              {entity.name}
            </span>
            <NumberField
              label={`Guess for ${entity.name}`}
              value={pir.guesses[entity.id] ?? 0}
              step={100}
              onCommit={(value) => {
                if (!open) return;
                send({ type: "pir_set_guess", entityId: entity.id, value });
              }}
            />
          </li>
        ))}
      </ul>

      {pir.winners.length > 0 ? (
        <p className="mt-3 border border-gold bg-lavender-pale px-3 py-2 text-[12px] uppercase tracking-[0.16em] text-gold-ink">
          Winner:{" "}
          {pir.winners
            .map((id) => entities.find((entity) => entity.id === id)?.name ?? id)
            .join(", ")}
        </p>
      ) : null}

      <Footer>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "QUESTION_ACTIVE"}
          onClick={() => send({ type: "pir_lock" })}
        >
          {pir.locked ? "Unlock guesses" : "Lock guesses"}
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase !== "QUESTION_ACTIVE"}
          onClick={() => send({ type: "reveal" })}
        >
          Reveal guesses
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase !== "REVEAL" || pir.priceRevealed}
          onClick={() => send({ type: "pir_reveal_price" })}
        >
          Reveal price
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "REVEAL"}
          onClick={() => send({ type: "round_result" })}
        >
          Round result
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "ROUND_RESULT"}
          onClick={() => send({ type: "next_round" })}
        >
          Next item
        </button>
      </Footer>
    </div>
  );
}

function PartyPricePanel({
  session,
  question,
  send,
  party,
}: {
  session: SessionState;
  question: PriceQuestion;
  send: Send;
  party: PricePartyApi;
}) {
  const [override, setOverride] = useState<string[]>([]);
  const state = session.pir?.party;
  if (!state) return null;

  const teams = Object.entries(state.teams);
  const submitted = teams.filter(([id]) => id in state.guesses).length;
  const open = session.phase === "QUESTION_ACTIVE" && !state.locked;
  const canRevealPrice = session.phase === "REVEAL" && !state.priceRevealed;
  const canRevealLeaderboard =
    session.phase === "REVEAL" && state.priceRevealed && !state.leaderboardRevealed;

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <span className="hbtn pointer-events-none">
          {state.mode === "teams" ? "3 teams" : "6 players"} · {teams.length}/{state.capacity}
        </span>
        <span className="hbtn pointer-events-none">
          {submitted} of {teams.length} submitted
        </span>
        <span className="hbtn pointer-events-none border-gold">
          {state.locked ? "Submissions locked" : "Submissions open"}
        </span>
        <span className="hbtn pointer-events-none">
          Actual {formatMoney(question.actualPrice, question.currency)}
        </span>
      </div>

      {party.error ? (
        <p className="mb-3 border border-gold/60 bg-lavender-pale px-3 py-2 text-[12px] text-plum">
          {party.error}
        </p>
      ) : null}

      {teams.length === 0 ? (
        <p className="mb-3 border border-gold/30 bg-lavender-pale/60 px-3 py-2 text-[12px] text-plum-soft">
          Waiting for phones. Share code <b className="text-plum">{session.code}</b> — teams open the
          join link from the TV.
        </p>
      ) : null}

      <ul className="grid gap-2">
        {teams.map(([teamId, team]) => {
          const guess = state.guesses[teamId];
          const score = state.scores[teamId] ?? 0;
          return (
            <li
              key={teamId}
              className="grid items-center gap-2 border border-gold/25 p-2 sm:grid-cols-[minmax(0,1fr)_90px_100px_auto]"
            >
              <input
                className="field"
                aria-label={`Team name for ${team.name}`}
                defaultValue={team.name}
                onBlur={(event) => {
                  const name = event.target.value.trim();
                  if (name && name !== team.name) party.rename(teamId, name);
                }}
              />
              <span className="text-[11px] uppercase tracking-[0.14em] text-plum-hush">
                {guess === undefined ? "waiting" : "submitted"}
              </span>
              <input
                key={`${teamId}-${question.id}`}
                className="num-field"
                type="number"
                min={0}
                aria-label={`Guess for ${team.name}`}
                defaultValue={guess ?? ""}
                placeholder="guess"
                onBlur={(event) => {
                  const value = Number(event.target.value);
                  if (!open || event.target.value === "" || Number.isNaN(value)) return;
                  party.setManualGuess(teamId, Math.max(0, Math.round(value)));
                }}
              />
              <div className="flex items-center gap-2">
                <span className="w-10 text-right text-[15px] tabular-nums text-gold-ink">{score}</span>
                <button
                  className="hbtn hbtn-danger"
                  type="button"
                  aria-label={`Remove ${team.name}`}
                  onClick={() => party.removeTeam(teamId)}
                >
                  Remove
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {state.priceRevealed ? (
        <div className="mt-3 border border-gold bg-lavender-pale p-3">
          <p className="text-[10px] uppercase tracking-[0.2em] text-gold-ink">Price revealed</p>
          <p className="mt-1 font-serif text-[24px]">
            {formatMoney(question.actualPrice, question.currency)}
          </p>

          {state.leaderboardRevealed ? (
            <div className="mt-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-gold-ink">Podium</p>
              <ol className="mt-1 grid gap-1">
                {state.podium.slice(0, 3).map((entry) => (
                  <li key={entry.entryId} className="flex items-baseline justify-between gap-2">
                    <span className="text-[13px]">
                      {entry.rank}. {state.teams[entry.entryId]?.name ?? entry.entryId}
                    </span>
                    <span className="text-[12px] tabular-nums text-plum-soft">
                      {formatMoney(entry.distance, session.config.currency)} away · +{entry.points}
                    </span>
                  </li>
                ))}
              </ol>

              {state.awarded ? (
                <button
                  className="hbtn mt-2"
                  type="button"
                  onClick={() => send({ type: "pir_undo_award" })}
                >
                  Undo award
                </button>
              ) : (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {[0, 1, 2].map((position) => (
                    <select
                      key={position}
                      className="field w-[150px]"
                      aria-label={`Podium position ${position + 1}`}
                      value={override[position] ?? ""}
                      onChange={(event) => {
                        const next = [...override];
                        next[position] = event.target.value;
                        setOverride(next);
                      }}
                    >
                      <option value="">{position + 1}st/nd/rd…</option>
                      {teams.map(([id, team]) => (
                        <option key={id} value={id}>
                          {team.name}
                        </option>
                      ))}
                    </select>
                  ))}
                  <button
                    className="hbtn"
                    type="button"
                    disabled={override.filter(Boolean).length === 0}
                    onClick={() =>
                      send({ type: "pir_override", teamIds: override.filter(Boolean) })
                    }
                  >
                    Apply override
                  </button>
                  <button
                    className="hbtn hbtn-solid"
                    type="button"
                    onClick={() => send({ type: "pir_award" })}
                  >
                    Award points
                  </button>
                </div>
              )}
            </div>
          ) : (
            <p className="text-[12px] text-plum-soft">
              Price first. Reveal the leaderboard when the room is ready.
            </p>
          )}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2 border-t border-gold/20 pt-3">
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "QUESTION_ACTIVE"}
          onClick={() => send({ type: "pir_lock" })}
        >
          {state.locked ? "Reopen submissions" : "Lock submissions"}
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={session.phase !== "QUESTION_ACTIVE"}
          onClick={() => send({ type: "reveal" })}
        >
          Reveal guesses
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={!canRevealPrice}
          onClick={() => send({ type: "pir_reveal_price" })}
        >
          Reveal price
        </button>
        <button
          className="hbtn hbtn-solid"
          type="button"
          disabled={!canRevealLeaderboard}
          onClick={() => send({ type: "pir_leaderboard" })}
        >
          Reveal leaderboard
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "REVEAL"}
          onClick={() => send({ type: "round_result" })}
        >
          Round result
        </button>
        <button
          className="hbtn"
          type="button"
          disabled={session.phase !== "ROUND_RESULT"}
          onClick={() => send({ type: "next_round" })}
        >
          Next item
        </button>
      </div>
    </div>
  );
}

export function GamePanel({
  session,
  questions,
  send,
  party,
}: {
  session: SessionState;
  questions: Question[];
  send: Send;
  party: PricePartyApi;
}) {
  if (session.game === "family_feud") return <FeudPanel session={session} questions={questions} send={send} />;
  if (session.game === "herd_mentality") return <HerdPanel session={session} questions={questions} send={send} />;
  if (session.game === "whos_most_likely") return <MostLikelyPanel session={session} questions={questions} send={send} />;
  if (session.game === "price_is_right") {
    return <PricePanel session={session} questions={questions} send={send} party={party} />;
  }
  return null;
}

export function gameTitle(session: SessionState): string {
  return session.game ? GAME_LABEL[session.game] : "Game Night";
}

export function formatMoney(value: number, currency: string): string {
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

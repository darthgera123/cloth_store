/* Security-rule checks against the Firebase emulator suite.
   Skipped automatically when the emulators are not running:
     bun run emulators   (in another terminal)
     bun test tests/multiplayer-rules.test.ts
*/

import { test } from "bun:test";
import { expect } from "bun:test";

const AUTH = "http://127.0.0.1:9099";
const RTDB = "http://127.0.0.1:9000";
const NS = "demo-game-night-default-rtdb";

async function emulatorUp(): Promise<boolean> {
  try {
    const res = await fetch(`${RTDB}/.json?ns=${NS}`);
    return res.status < 500;
  } catch {
    return false;
  }
}

const up = await emulatorUp();
const code = `T${Date.now().toString(36).slice(-3).toUpperCase()}`.slice(0, 4);

async function signUp(): Promise<{ uid: string; token: string }> {
  const res = await fetch(`${AUTH}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ returnSecureToken: true }),
  });
  const data = (await res.json()) as { localId: string; idToken: string };
  return { uid: data.localId, token: data.idToken };
}

async function rtdb(
  token: string | null,
  path: string,
  init: { method: string; body?: unknown } = { method: "GET" },
): Promise<Response> {
  const query = [`ns=${NS}`, token ? `auth=${encodeURIComponent(token)}` : ""]
    .filter(Boolean)
    .join("&");
  return fetch(`${RTDB}/${path}.json?${query}`, {
    method: init.method,
    headers: init.body === undefined ? undefined : { "content-type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
}

test.skipIf(!up)("rules keep guesses private and the board host-only", async () => {
  const host = await signUp();
  const teamA = await signUp();
  const teamB = await signUp();

  expect(
    (await rtdb(host.token, `sessions/${code}/meta`, {
      method: "PUT",
      body: { hostUid: host.uid, createdAt: Date.now() },
    })).status,
  ).toBe(200);

  expect(
    (await rtdb(host.token, `sessions/${code}/board`, {
      method: "PUT",
      body: { roundId: "round1", locked: false, priceRevealed: false, price: null, scores: {} },
    })).status,
  ).toBe(200);

  // Teams bind themselves to their own auth uid.
  expect(
    (await rtdb(teamA.token, `sessions/${code}/teams/a`, {
      method: "PUT",
      body: { name: "Alpha", uid: teamA.uid, joinedAt: Date.now() },
    })).status,
  ).toBe(200);
  expect(
    (await rtdb(teamB.token, `sessions/${code}/teams/b`, {
      method: "PUT",
      body: { name: "Bravo", uid: teamB.uid, joinedAt: Date.now() },
    })).status,
  ).toBe(200);

  // A team cannot claim someone else's identity.
  expect(
    (await rtdb(teamB.token, `sessions/${code}/teams/a`, {
      method: "PATCH",
      body: { uid: teamB.uid },
    })).status,
  ).toBe(401);

  // Own guess while submissions are open.
  expect(
    (await rtdb(teamA.token, `sessions/${code}/guesses/a/round1`, {
      method: "PUT",
      body: 1200,
    })).status,
  ).toBe(200);

  // Another team cannot read or overwrite it.
  expect((await rtdb(teamB.token, `sessions/${code}/guesses/a/round1`)).status).toBe(401);
  expect(
    (await rtdb(teamB.token, `sessions/${code}/guesses/a/round1`, {
      method: "PUT",
      body: 5,
    })).status,
  ).toBe(401);

  // The host reads every guess.
  const hostView = await rtdb(host.token, `sessions/${code}/guesses`);
  expect(hostView.status).toBe(200);
  expect(await hostView.json()).toEqual({ a: { round1: 1200 } });

  // Only the host writes the board or scores.
  expect(
    (await rtdb(teamA.token, `sessions/${code}/board`, {
      method: "PATCH",
      body: { scores: { a: 99 } },
    })).status,
  ).toBe(401);

  // A stale round is rejected even while open.
  expect(
    (await rtdb(teamA.token, `sessions/${code}/guesses/a/round0`, {
      method: "PUT",
      body: 50,
    })).status,
  ).toBe(401);

  // Locking stops further writes.
  expect(
    (await rtdb(host.token, `sessions/${code}/board`, {
      method: "PATCH",
      body: { locked: true },
    })).status,
  ).toBe(200);
  expect(
    (await rtdb(teamA.token, `sessions/${code}/guesses/a/round1`, {
      method: "PUT",
      body: 1300,
    })).status,
  ).toBe(401);

  // Unauthenticated clients get nothing.
  expect((await rtdb(null, `sessions/${code}/board`)).status).toBe(401);

  // The host can remove the whole session; afterwards joins fail.
  expect((await rtdb(host.token, `sessions/${code}`, { method: "DELETE" })).status).toBe(200);
  const gone = await rtdb(host.token, `sessions/${code}/meta`);
  expect(gone.status).toBe(200);
  expect(await gone.json()).toBeNull();
});

if (!up) {
  console.warn("Firebase emulators are not running; multiplayer rule checks skipped.");
}

/* Game Night — host dashboard logic.
   Everything the host touches writes to the shared store, so the audience
   display follows immediately in a second tab or window. */

import { createStore } from "./store.js";

const data = await fetch(new URL("../data/games.json", import.meta.url)).then((res) => {
  if (!res.ok) throw new Error(`games.json: ${res.status}`);
  return res.json();
});

const store = createStore(data);

const el = {
  question: document.querySelector("[data-question]"),
  answers: document.querySelector("[data-answers]"),
  roundLabel: document.querySelector("[data-round-label]"),
  teams: document.querySelector("[data-teams]"),
  screens: [...document.querySelectorAll("[data-screen-set]")],
};

const strikeIcon =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#mark-strike" /></svg>';

/* ---------- team controls (built once) ---------- */

function buildTeamControls() {
  el.teams.replaceChildren(
    ...data.teams.map((name, index) => {
      const box = document.createElement("div");
      box.className = "teamctl";
      box.dataset.team = String(index);
      box.innerHTML = `
        <div class="teamctl__head">
          <span class="teamctl__name"></span>
          <span class="badge">On the board</span>
        </div>
        <div class="teamctl__score">
          <button class="step" type="button" data-step="-5" aria-label="Subtract five points">−</button>
          <input type="number" min="0" step="1" inputmode="numeric" aria-label="Score" />
          <button class="step" type="button" data-step="5" aria-label="Add five points">+</button>
        </div>
        <div class="teamctl__strikes">
          <button class="strike-btn" type="button" data-strike="0" aria-label="One strike">${strikeIcon}</button>
          <button class="strike-btn" type="button" data-strike="1" aria-label="Two strikes">${strikeIcon}</button>
          <button class="strike-btn" type="button" data-strike="2" aria-label="Three strikes">${strikeIcon}</button>
          <span class="teamctl__label">Strikes</span>
        </div>
        <button class="hbtn teamctl__make" type="button" data-make-active>Set as active team</button>
      `;
      box.querySelector(".teamctl__name").textContent = name;
      return box;
    }),
  );
}

buildTeamControls();

/* ---------- render ---------- */

function renderAnswers(state) {
  const question = data.feud.questions[state.feud.q];
  const key = String(state.feud.q);

  if (el.answers.dataset.q !== key) {
    el.answers.dataset.q = key;
    el.answers.replaceChildren(
      ...question.answers.map((answer, index) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "abtn";
        btn.dataset.index = String(index);
        btn.innerHTML = '<span class="abtn__idx"></span><span class="abtn__text"></span><span class="abtn__pts"></span><span class="abtn__state"></span>';
        btn.querySelector(".abtn__idx").textContent = String(index + 1);
        btn.querySelector(".abtn__text").textContent = answer.text;
        btn.querySelector(".abtn__pts").textContent = String(answer.points);
        return btn;
      }),
    );
  }

  const revealed = state.feud.revealed[state.feud.q];
  [...el.answers.children].forEach((btn, index) => {
    btn.classList.toggle("is-on", Boolean(revealed[index]));
    btn.setAttribute("aria-pressed", String(Boolean(revealed[index])));
  });
}

function renderTeams(state) {
  [...el.teams.children].forEach((box, index) => {
    const team = state.feud.teams[index];
    box.classList.toggle("is-active", state.feud.active === index);

    const input = box.querySelector("input");
    if (document.activeElement !== input) input.value = String(team.score);

    [...box.querySelectorAll("[data-strike]")].forEach((btn, slot) => {
      btn.classList.toggle("is-on", slot < team.strikes);
      btn.setAttribute("aria-pressed", String(slot < team.strikes));
    });
  });
}

function render(state) {
  el.question.textContent = data.feud.questions[state.feud.q].question;
  el.roundLabel.textContent = `Question ${state.feud.q + 1} of ${data.feud.questions.length}`;
  renderAnswers(state);
  renderTeams(state);
  for (const btn of el.screens) {
    btn.classList.toggle("is-on", btn.dataset.screenSet === state.screen);
  }
}

/* ---------- actions ---------- */

const clampScore = (value) => Math.max(0, Math.round(Number(value) || 0));

function patchQuestion(state, fn) {
  const row = state.feud.revealed[state.feud.q];
  fn(row);
}

const actions = {
  "prev-q": () => store.update((s) => { s.feud.q = Math.max(0, s.feud.q - 1); }),
  "next-q": () => store.update((s) => { s.feud.q = Math.min(data.feud.questions.length - 1, s.feud.q + 1); }),
  "reveal-all": () => store.update((s) => patchQuestion(s, (row) => row.fill(true))),
  "hide-all": () => store.update((s) => patchQuestion(s, (row) => row.fill(false))),
  "reset-q": () =>
    store.update((s) => {
      patchQuestion(s, (row) => row.fill(false));
      for (const team of s.feud.teams) team.strikes = 0;
    }),
  "reset-game": () => {
    if (window.confirm("Reset scores, strikes and all reveals?")) store.reset();
  },
};

document.addEventListener("click", (event) => {
  const screenBtn = event.target.closest("[data-screen-set]");
  if (screenBtn) {
    store.update((s) => { s.screen = screenBtn.dataset.screenSet; });
    return;
  }

  const action = event.target.closest("[data-action]");
  if (action && actions[action.dataset.action]) {
    actions[action.dataset.action]();
    return;
  }

  const answer = event.target.closest(".abtn");
  if (answer) {
    const index = Number(answer.dataset.index);
    store.update((s) => {
      patchQuestion(s, (row) => { row[index] = !row[index]; });
    });
    return;
  }

  const teamBox = event.target.closest(".teamctl");
  if (!teamBox) return;
  const teamIndex = Number(teamBox.dataset.team);

  const step = event.target.closest("[data-step]");
  if (step) {
    const delta = Number(step.dataset.step);
    store.update((s) => {
      s.feud.teams[teamIndex].score = clampScore(s.feud.teams[teamIndex].score + delta);
    });
    return;
  }

  const strike = event.target.closest("[data-strike]");
  if (strike) {
    const slot = Number(strike.dataset.strike);
    store.update((s) => {
      const team = s.feud.teams[teamIndex];
      team.strikes = team.strikes === slot + 1 ? slot : slot + 1;
    });
    return;
  }

  if (event.target.closest("[data-make-active]")) {
    store.update((s) => { s.feud.active = teamIndex; });
  }
});

document.addEventListener("change", (event) => {
  const input = event.target.closest(".teamctl input");
  if (!input) return;
  const teamIndex = Number(input.closest(".teamctl").dataset.team);
  const value = clampScore(input.value);
  input.value = String(value);
  store.update((s) => { s.feud.teams[teamIndex].score = value; });
});

/* ---------- keyboard ---------- */

document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, textarea, select")) return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;

  const key = event.key.toLowerCase();
  if (key === "r") {
    event.preventDefault();
    actions["reveal-all"]();
  } else if (key === "h") {
    event.preventDefault();
    actions["hide-all"]();
  } else if (key === "n") {
    event.preventDefault();
    actions["next-q"]();
  } else if (key === "1" || key === "2") {
    event.preventDefault();
    const teamIndex = Number(key) - 1;
    store.update((s) => { s.feud.active = teamIndex; });
  } else if (key === "s") {
    event.preventDefault();
    store.update((s) => {
      const team = s.feud.teams[s.feud.active];
      team.strikes = (team.strikes + 1) % 4;
    });
  }
});

store.subscribe(render);

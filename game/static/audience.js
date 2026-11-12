/* Game Night — audience display.
   Read-mostly view of the shared state: welcome, game selection, and the
   Family Feud board. The host page drives it; clicks here work too so the
   site can be operated from the projector machine alone. */

import { mountMandala } from "./mandala.js";
import { createStore } from "./store.js";

const strikeIcon =
  '<svg class="strike" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#mark-strike" /></svg>';

const data = await fetch(new URL("../data/games.json", import.meta.url)).then((res) => {
  if (!res.ok) throw new Error(`games.json: ${res.status}`);
  return res.json();
});

for (const el of document.querySelectorAll("[data-mandala]")) {
  mountMandala(el, { rotation: Number(el.dataset.rotation) || 0 });
}

document.querySelector("[data-subtitle]").textContent = data.meta.subtitle;

const store = createStore(data);

const el = {
  screens: [...document.querySelectorAll("[data-screen]")],
  teams: [...document.querySelectorAll("[data-team]")],
  question: document.querySelector("[data-question]"),
  answers: document.querySelector("[data-answers]"),
  round: document.querySelector("[data-round]"),
  total: document.querySelector("[data-total]"),
};

document.querySelector("[data-total]").textContent = `of ${data.feud.questions.length}`;

for (const team of el.teams) {
  team.querySelector("[data-strikes]").innerHTML = strikeIcon.repeat(3);
}

document.addEventListener("click", (event) => {
  const start = event.target.closest("[data-action='open-games']");
  if (start) {
    store.update((s) => {
      s.screen = "games";
    });
    return;
  }

  const tile = event.target.closest("[data-game]");
  if (tile) {
    store.update((s) => {
      s.screen = "feud";
    });
  }
});

function renderAnswers(state) {
  const question = data.feud.questions[state.feud.q];
  const key = String(state.feud.q);

  if (el.answers.dataset.q !== key) {
    el.answers.dataset.q = key;
    el.answers.replaceChildren(
      ...question.answers.map((answer, index) => {
        const li = document.createElement("li");
        li.className = "answer";
        li.dataset.index = String(index);

        const num = document.createElement("span");
        num.className = "answer__num";
        num.textContent = String(index + 1);

        const text = document.createElement("span");
        text.className = "answer__text";
        text.textContent = answer.text;

        const pts = document.createElement("span");
        pts.className = "answer__pts";
        pts.textContent = String(answer.points);

        li.append(num, text, pts);
        return li;
      }),
    );
  }

  const revealed = state.feud.revealed[state.feud.q];
  [...el.answers.children].forEach((li, index) => {
    li.classList.toggle("is-revealed", Boolean(revealed[index]));
  });
}

function renderTeams(state) {
  state.feud.teams.forEach((team, index) => {
    const card = el.teams[index];
    card.classList.toggle("is-active", state.feud.active === index);
    card.querySelector("[data-name]").textContent = team.name;

    const score = card.querySelector("[data-score]");
    const next = String(team.score);
    if (score.textContent !== next) {
      score.textContent = next;
      score.classList.remove("is-bump");
      void score.offsetWidth; // restart the transition
      score.classList.add("is-bump");
    }

    [...card.querySelectorAll("[data-strikes] .strike")].forEach((slot, slotIndex) => {
      slot.classList.toggle("is-on", slotIndex < team.strikes);
    });
  });
}

function render(state) {
  for (const screen of el.screens) {
    screen.classList.toggle("is-active", screen.dataset.screen === state.screen);
  }

  el.question.textContent = data.feud.questions[state.feud.q].question;
  el.round.textContent = String(state.feud.q + 1);
  renderAnswers(state);
  renderTeams(state);
}

store.subscribe(render);

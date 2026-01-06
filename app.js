const els = {
  questionTitle: document.getElementById("question-title"),
  questionText: document.getElementById("question-text"),
  options: document.getElementById("options"),
  feedback: document.getElementById("feedback"),
  score: document.getElementById("score"),
  position: document.getElementById("position"),
  progress: document.getElementById("progress-bar"),
  next: document.getElementById("next"),
  prev: document.getElementById("prev"),
  restartAll: document.getElementById("restart-all"),
  restartWrong: document.getElementById("restart-wrong"),
};

const state = {
  allQuestions: [],
  deck: [],
  currentIndex: 0,
  answers: new Map(), // id -> {selected, correct}
  pendingSelections: new Map(), // id -> Set<optionIndex> (multi-correct questions)
};

function getTopicConfig() {
  const params = new URLSearchParams(window.location.search);
  const topic = (params.get("topic") || "szamelm").toLowerCase();
  const map = {
    szamelm: {
      file: "questions.json",
      label: "Számelm",
    },
    telekom: {
      file: "questions-telekom.json",
      label: "Telekom",
    },
  };
  return map[topic] || map.szamelm;
}

const escapeHtml = (text = "") =>
  text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const formatMathLike = (text = "") => {
  // Normalizálás: set-különbség jelölésekhez a duplán maradt backslash-eket egyszeresre cseréljük.
  const normalized = text.replace(/\\\\/g, "∖");
  const escaped = escapeHtml(normalized);

  let formatted = escaped;
  formatted = formatted.replace(/\\overline\{([^}]+)\}/g, '<span class="overline">$1</span>');
  formatted = formatted.replace(/([\p{L}\p{N}])_\{([^}]+)\}/gu, "$1<sub>$2</sub>");
  // Általánosabb alsó index, ha az aláírás nem betű/szám (pl. ≤_{p})
  formatted = formatted.replace(/([^\s])_\{([^}]+)\}/g, "$1<sub>$2</sub>");
  formatted = formatted.replace(/([\p{L}\p{N}])_([\p{L}\p{N}]+)/gu, "$1<sub>$2</sub>");
  formatted = formatted.replace(/([\p{L}\p{N}\)\]])\^\{([^}]+)\}/gu, "$1<sup>$2</sup>");
  formatted = formatted.replace(/([\p{L}\p{N}\)\]])\^(\d+)/gu, "$1<sup>$2</sup>");
  formatted = formatted.replace(/\n/g, "<br>");

  return formatted;
};

const setFormattedHtml = (el, text = "") => {
  el.innerHTML = formatMathLike(text);
};

const shuffle = (arr) => {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
};

async function init() {
  try {
    const cfg = getTopicConfig();
    const topicLabel = document.getElementById("topic-label");
    if (topicLabel) topicLabel.textContent = `Kvíz gyakorlás · ${cfg.label}`;

    const res = await fetch(cfg.file);
    if (!res.ok) throw new Error(`Nem sikerült betölteni a kérdéseket (${res.status})`);
    state.allQuestions = await res.json();
    startSession(state.allQuestions);
  } catch (err) {
    els.questionTitle.textContent = "Hoppá, hiba történt";
    els.questionText.textContent = err.message;
    els.options.innerHTML = "";
    els.next.disabled = true;
    els.prev.disabled = true;
  }
}

function startSession(list) {
  state.deck = shuffle(list);
  state.currentIndex = 0;
  state.answers = new Map();
  state.pendingSelections = new Map();
  renderQuestion();
  updateStats();
}

function currentQuestion() {
  return state.deck[state.currentIndex];
}

function correctIndexes(q) {
  return q.options
    .map((opt, idx) => (opt.correct ? idx : null))
    .filter((v) => v !== null);
}

function isMultiCorrect(q) {
  return correctIndexes(q).length > 1;
}

function setNextButtonLabel() {
  const q = currentQuestion();
  const answer = state.answers.get(q?.id);
  if (q && isMultiCorrect(q) && !answer) {
    els.next.textContent = "Ellenőrzés";
  } else {
    els.next.textContent = "Következő";
  }
}

function renderQuestion() {
  if (!state.deck.length) {
    els.questionTitle.textContent = "Nincs kérdés";
    setFormattedHtml(els.questionText, "Adj hozzá kérdéseket a questions.json fájlba.");
    els.options.innerHTML = "";
    els.feedback.innerHTML = "";
    els.next.disabled = true;
    els.prev.disabled = true;
    updateStats();
    return;
  }

  const q = currentQuestion();
  const answer = state.answers.get(q.id);
  const multi = isMultiCorrect(q);
  const pending = state.pendingSelections.get(q.id) || new Set();

  els.questionTitle.textContent = `Kérdés ${state.currentIndex + 1}`;
  setFormattedHtml(els.questionText, q.question);
  els.options.innerHTML = "";

  q.options.forEach((opt, idx) => {
    const btn = document.createElement("button");
    btn.className = "option";
    btn.innerHTML = formatMathLike(opt.text || "—");
    btn.type = "button";
    btn.disabled = !!answer;
    btn.addEventListener("click", () => {
      if (multi) {
        togglePending(idx);
      } else {
        handleAnswer(idx);
      }
    });

    if (answer) {
      if (opt.correct) btn.classList.add("correct");
      const selectedList = Array.isArray(answer.selected) ? answer.selected : [answer.selected];
      if (selectedList.includes(idx)) btn.classList.add("chosen");
      if (selectedList.includes(idx) && !opt.correct) btn.classList.add("wrong");
    } else if (multi && pending.has(idx)) {
      btn.classList.add("chosen");
    }
    els.options.appendChild(btn);
  });

  els.prev.disabled = state.currentIndex === 0;
  els.next.disabled = multi ? false : !answer;
  setFormattedHtml(els.feedback, answer ? feedbackMessage(q, answer.selected) : "");
  setNextButtonLabel();
  updateStats();
}

function togglePending(idx) {
  const q = currentQuestion();
  if (!q) return;
  if (state.answers.has(q.id)) return;
  const set = state.pendingSelections.get(q.id) || new Set();
  if (set.has(idx)) set.delete(idx);
  else set.add(idx);
  state.pendingSelections.set(q.id, set);

  // Update visual selection immediately.
  const buttons = Array.from(els.options.querySelectorAll("button"));
  buttons.forEach((btn, i) => {
    btn.classList.toggle("chosen", set.has(i));
  });
}

function handleAnswer(idx) {
  const q = currentQuestion();
  if (state.answers.has(q.id)) return;

  const picked = q.options[idx];
  const isCorrect = Boolean(picked.correct);
  state.answers.set(q.id, { selected: idx, correct: isCorrect });

  if (isCorrect === false) {
    // keep track so the "hibásak" kör is elérhető
    state.answers.get(q.id).wrong = true;
  }

  lockOptions(q, idx);
  setFormattedHtml(els.feedback, feedbackMessage(q, idx));
  els.next.disabled = false;
  updateStats();
}

function handleAnswerMulti() {
  const q = currentQuestion();
  if (!q) return;
  if (state.answers.has(q.id)) return;

  const selectedSet = state.pendingSelections.get(q.id) || new Set();
  const selected = Array.from(selectedSet.values()).sort((a, b) => a - b);
  const correct = correctIndexes(q);

  const isCorrect =
    selected.length === correct.length && selected.every((v, i) => v === correct[i]);
  state.answers.set(q.id, { selected, correct: isCorrect, wrong: !isCorrect, multi: true });
  lockOptionsMulti(q, selected);
  setFormattedHtml(els.feedback, feedbackMessage(q, selected));
  setNextButtonLabel();
  updateStats();
}

function lockOptions(q, selectedIdx) {
  const buttons = Array.from(els.options.querySelectorAll("button"));
  buttons.forEach((btn, idx) => {
    btn.disabled = true;
    const opt = q.options[idx];
    if (opt.correct) btn.classList.add("correct");
    if (idx === selectedIdx) btn.classList.add("chosen");
    if (idx === selectedIdx && !opt.correct) btn.classList.add("wrong");
  });
}

function lockOptionsMulti(q, selectedIdxs) {
  const selected = new Set(selectedIdxs);
  const buttons = Array.from(els.options.querySelectorAll("button"));
  buttons.forEach((btn, idx) => {
    btn.disabled = true;
    const opt = q.options[idx];
    if (opt.correct) btn.classList.add("correct");
    if (selected.has(idx)) btn.classList.add("chosen");
    if (selected.has(idx) && !opt.correct) btn.classList.add("wrong");
  });
}

function feedbackText(q, selectedIdx) {
  const selectedIdxs = Array.isArray(selectedIdx) ? selectedIdx : [selectedIdx];
  const selectedSet = new Set(selectedIdxs);
  const correctIdxs = correctIndexes(q);
  const correctTexts = q.options.filter((o) => o.correct).map((o) => o.text);

  const isCorrect =
    selectedIdxs.length === correctIdxs.length && correctIdxs.every((i) => selectedSet.has(i));

  if (isCorrect) return "Helyes válasz!";
  return `Helyes megoldás: ${correctTexts.join(" | ")}`;
}

function feedbackMessage(q, selectedIdx) {
  const base = feedbackText(q, selectedIdx);
  const explanation = typeof q.explanation === "string" ? q.explanation.trim() : "";
  if (!explanation) return base;
  return `${base}\n\nMagyarázat: ${explanation}`;
}

function updateStats() {
  const total = state.deck.length || 1;
  const answered = state.answers.size;
  const correct = Array.from(state.answers.values()).filter((a) => a.correct).length;
  els.score.textContent = `${correct} / ${total}`;
  els.position.textContent = `${state.currentIndex + 1} / ${total}`;
  els.progress.style.width = `${Math.min((answered / total) * 100, 100)}%`;
}

function goNext() {
  const q = currentQuestion();
  const multi = q ? isMultiCorrect(q) : false;
  const answered = q ? state.answers.has(q.id) : false;

  if (q && multi && !answered) {
    handleAnswerMulti();
    return;
  }

  if (state.currentIndex < state.deck.length - 1) {
    state.currentIndex += 1;
    renderQuestion();
  } else {
    setFormattedHtml(
      els.feedback,
      "Végigértél ezen a körön. Újrakezdés gombokkal választhatsz új paklit."
    );
  }
}

function goPrev() {
  if (state.currentIndex > 0) {
    state.currentIndex -= 1;
    renderQuestion();
  }
}

function restartAll() {
  startSession(state.allQuestions);
}

function restartWrong() {
  if (!state.answers.size) {
    setFormattedHtml(
      els.feedback,
      "Előbb válaszolj néhány kérdésre, hogy legyen hibás lista."
    );
    return;
  }
  const wrongIds = Array.from(state.answers.entries())
    .filter(([, ans]) => !ans.correct)
    .map(([id]) => id);
  if (!wrongIds.length) {
    setFormattedHtml(
      els.feedback,
      "Nincs hibás válasz ebből a körből, menj végig az összesen."
    );
    return;
  }
  const subset = state.allQuestions.filter((q) => wrongIds.includes(q.id));
  startSession(subset);
}

els.next.addEventListener("click", goNext);
els.prev.addEventListener("click", goPrev);
els.restartAll.addEventListener("click", restartAll);
els.restartWrong.addEventListener("click", restartWrong);

init();

const els = {
  questionTitle: document.getElementById("question-title"),
  questionText: document.getElementById("question-text"),
  quizTag: document.getElementById("quiz-tag"),
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
    const res = await fetch("questions.json");
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
  renderQuestion();
  updateStats();
}

function currentQuestion() {
  return state.deck[state.currentIndex];
}

function renderQuestion() {
  if (!state.deck.length) {
    els.questionTitle.textContent = "Nincs kérdés";
    els.questionText.textContent = "Adj hozzá kérdéseket a questions.json fájlba.";
    els.options.innerHTML = "";
    els.feedback.textContent = "";
    els.next.disabled = true;
    els.prev.disabled = true;
    updateStats();
    return;
  }

  const q = currentQuestion();
  const answer = state.answers.get(q.id);

  els.quizTag.textContent = q.quiz || "kvíz";
  els.questionTitle.textContent = `Kérdés ${state.currentIndex + 1}`;
  els.questionText.textContent = q.question;
  els.options.innerHTML = "";

  q.options.forEach((opt, idx) => {
    const btn = document.createElement("button");
    btn.className = "option";
    btn.textContent = opt.text || "—";
    btn.type = "button";
    btn.disabled = !!answer;
    btn.addEventListener("click", () => handleAnswer(idx));

    if (answer) {
      if (opt.correct) btn.classList.add("correct");
      if (answer.selected === idx) btn.classList.add("chosen");
      if (answer.selected === idx && !opt.correct) btn.classList.add("wrong");
    }
    els.options.appendChild(btn);
  });

  els.prev.disabled = state.currentIndex === 0;
  els.next.disabled = !answer;
  els.feedback.textContent = answer ? feedbackText(q, answer.selected) : "";
  updateStats();
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
  els.feedback.textContent = feedbackText(q, idx);
  els.next.disabled = false;
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

function feedbackText(q, selectedIdx) {
  const picked = q.options[selectedIdx];
  const correctTexts = q.options.filter((o) => o.correct).map((o) => o.text);
  if (picked?.correct) {
    return "Helyes válasz!";
  }
  return `Helyes megoldás: ${correctTexts.join(" | ")}`;
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
  if (state.currentIndex < state.deck.length - 1) {
    state.currentIndex += 1;
    renderQuestion();
  } else {
    els.feedback.textContent = "Végigértél ezen a körön. Újrakezdés gombokkal választhatsz új paklit.";
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
    els.feedback.textContent = "Előbb válaszolj néhány kérdésre, hogy legyen hibás lista.";
    return;
  }
  const wrongIds = Array.from(state.answers.entries())
    .filter(([, ans]) => !ans.correct)
    .map(([id]) => id);
  if (!wrongIds.length) {
    els.feedback.textContent = "Nincs hibás válasz ebből a körből, menj végig az összesen.";
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

const $ = (s) => document.querySelector(s);
let current = null;

async function api(path, opts = {}) {
  if (opts.json) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(opts.json);
  }
  const r = await fetch("/api" + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Error " + r.status);
  return data;
}
const fail = (e) => alert(e.message);

async function loadCourses() {
  const courses = await api("/courses");
  const ul = $("#courses");
  ul.innerHTML = "";
  for (const c of courses) {
    const li = document.createElement("li");
    li.className = current && current.id === c.id ? "active" : "";
    const name = document.createElement("span");
    name.textContent = c.name;
    const del = document.createElement("span");
    del.textContent = "✕";
    del.title = "Eliminar curso";
    del.onclick = async (e) => {
      e.stopPropagation();
      if (confirm(`¿Eliminar "${c.name}" con todo su material?`)) {
        await api("/courses/" + c.id, { method: "DELETE" });
        if (current && current.id === c.id) current = null;
        show();
        loadCourses();
      }
    };
    li.append(name, del);
    li.onclick = () => { current = c; show(); loadCourses(); };
    ul.append(li);
  }
}

function show() {
  $("#empty").hidden = !!current;
  $("#course-view").hidden = !current;
  if (!current) return;
  $("#course-title").textContent = current.name;
  loadMessages(); loadMaterials(); loadTasks();
  $("#quiz-out").textContent = "";
}

function addMsg(role, text, sources) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.textContent = text;
  if (sources && sources.length) {
    const s = document.createElement("small");
    s.textContent = "Fuentes: " + sources.map((x) => `[${x.n}] ${x.filename} p.${x.page}`).join(" · ");
    d.append(s);
  }
  $("#messages").append(d);
  $("#messages").scrollTop = 1e9;
  return d;
}

async function loadMessages() {
  $("#messages").innerHTML = "";
  for (const m of await api(`/courses/${current.id}/messages`)) addMsg(m.role, m.content);
}

async function sendChat(text) {
  addMsg("user", text);
  const wait = addMsg("assistant", "Pensando…");
  try {
    const r = await api(`/courses/${current.id}/chat`, { method: "POST", json: { message: text } });
    wait.remove();
    addMsg("assistant", r.answer, r.sources);
  } catch (e) { wait.textContent = "⚠ " + e.message; }
}

async function loadMaterials() {
  const ul = $("#materials");
  ul.innerHTML = "";
  for (const m of await api(`/courses/${current.id}/materials`)) {
    const li = document.createElement("li");
    li.className = "row";
    li.innerHTML = '<span class="t"></span><button class="link">Quitar</button>';
    li.querySelector(".t").textContent = "📄 " + m.filename;
    li.querySelector("button").onclick = async () => {
      await api("/materials/" + m.id, { method: "DELETE" });
      loadMaterials();
    };
    ul.append(li);
  }
}

async function loadTasks() {
  const ul = $("#tasks");
  ul.innerHTML = "";
  for (const t of await api(`/courses/${current.id}/tasks`)) {
    const li = document.createElement("li");
    li.className = t.done ? "done" : "";
    li.innerHTML = `<div class="row"><input type="checkbox"><span class="t"></span><small></small>
      <button class="plan-btn">Plan con IA</button><button class="link del">Borrar</button></div><div class="plan"></div>`;
    li.querySelector("input").checked = !!t.done;
    li.querySelector(".t").textContent = t.title;
    li.querySelector("small").textContent = t.due ? "📅 " + t.due : "";
    li.querySelector(".plan").textContent = t.plan || "";
    li.querySelector("input").onchange = async (e) => {
      await api("/tasks/" + t.id, { method: "PATCH", json: { done: e.target.checked } });
      loadTasks();
    };
    li.querySelector(".del").onclick = async () => { await api("/tasks/" + t.id, { method: "DELETE" }); loadTasks(); };
    li.querySelector(".plan-btn").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "Generando…";
      try { await api(`/tasks/${t.id}/plan`, { method: "POST" }); } catch (err) { fail(err); }
      loadTasks();
    };
    ul.append(li);
  }
}

// Eventos
document.querySelectorAll("nav button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("nav button").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== "tab-" + b.dataset.tab));
}));

$("#course-form").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    current = await api("/courses", { method: "POST", json: { name: f.get("name"), profile: f.get("profile") } });
    e.target.reset(); show(); loadCourses();
  } catch (err) { fail(err); }
};

$("#chat-form").onsubmit = (e) => {
  e.preventDefault();
  const ta = e.target.message;
  const text = ta.value.trim();
  if (!text) return;
  ta.value = "";
  sendChat(text);
};
$("#chat-form textarea").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); }
};
$("#clear-chat").onclick = async () => {
  if (confirm("¿Borrar la conversación?")) { await api(`/courses/${current.id}/messages`, { method: "DELETE" }); loadMessages(); }
};

$("#upload-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const btn = e.target.querySelector("button");
  btn.disabled = true; btn.textContent = "Subiendo…";
  try { await api(`/courses/${current.id}/materials`, { method: "POST", body: fd }); e.target.reset(); loadMaterials(); }
  catch (err) { fail(err); }
  btn.disabled = false; btn.textContent = "Subir";
};

$("#task-form").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  await api(`/courses/${current.id}/tasks`, {
    method: "POST",
    json: { title: f.get("title"), due: f.get("due") || null, description: f.get("description") },
  });
  e.target.reset(); loadTasks();
};

$("#quiz-form").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("#quiz-out").textContent = "Generando…";
  try {
    const r = await api(`/courses/${current.id}/quiz`, { method: "POST", json: { topic: f.get("topic"), n: +f.get("n") } });
    $("#quiz-out").textContent = r.quiz;
  } catch (err) { $("#quiz-out").textContent = "⚠ " + err.message; }
};

(async () => {
  const sel = $("#profile-select");
  for (const p of await api("/profiles")) sel.add(new Option(p.name, p.id));
  loadCourses();
})();

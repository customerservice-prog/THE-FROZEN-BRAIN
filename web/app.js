const $ = (id) => document.getElementById(id);

let currentConversation = "default";
let activeProject = "";

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setText(id, value) {
  $(id).textContent = value ?? "";
}

function attachSources(article, sources = []) {
  if (!sources.length || article.querySelector(".sources")) return;
  const refs = document.createElement("div");
  refs.className = "sources";
  for (const source of sources) {
    const chip = document.createElement("span");
    chip.textContent = `${source.source}#${source.chunk_index}`;
    chip.title = `SHA-256 ${source.sha256}`;
    refs.append(chip);
  }
  article.append(refs);
}

function addMessage(role, text, sources = []) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role === "user" ? "You" : "ColdVault";
  const p = document.createElement("p");
  p.textContent = text;
  article.append(label, p);
  attachSources(article, sources);
  $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
  return {article, p};
}

function renderHistory(history) {
  $("messages").replaceChildren();
  if (!history.length) {
    addMessage("assistant", "This conversation is empty. The durable ColdVault state is still available.");
    return;
  }
  for (const item of history) addMessage(item.role, item.content);
}

async function loadHistory() {
  const history = await api(`/api/history?conversation_id=${encodeURIComponent(currentConversation)}`);
  renderHistory(history);
}

async function loadConversations() {
  await api(`/api/history?conversation_id=${encodeURIComponent(currentConversation)}`);
  const conversations = await api("/api/conversations");
  const list = $("conversationList");
  list.replaceChildren();
  for (const item of conversations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-item" + (item.id === currentConversation ? " active" : "");
    const title = document.createElement("strong");
    title.textContent = item.title;
    const time = document.createElement("span");
    time.textContent = new Date(item.updated_at).toLocaleString();
    button.append(title, time);
    button.addEventListener("click", async () => {
      currentConversation = item.id;
      setText("conversationTitle", item.title);
      await loadConversations();
      await loadHistory();
    });
    list.append(button);
  }
  const active = conversations.find((x) => x.id === currentConversation);
  setText("conversationTitle", active?.title || "ColdVault");
}

function renderTools(tools) {
  const list = $("toolList");
  list.replaceChildren();
  for (const tool of tools) {
    const row = document.createElement("div");
    row.className = "tool-row";
    const name = document.createElement("span");
    name.textContent = tool.name;
    const status = document.createElement("span");
    status.className = `tool-state ${tool.enabled ? "enabled" : "disabled"}`;
    status.textContent = tool.enabled ? tool.permission : "locked";
    row.append(name, status);
    list.append(row);
  }
}

async function loadReminders() {
  const reminders = await api("/api/reminders");
  setText("reminderCount", String(reminders.length));
  const list = $("reminderList");
  list.replaceChildren();
  if (!reminders.length) {
    const empty = document.createElement("p");
    empty.className = "micro";
    empty.textContent = "No pending future commitments.";
    list.append(empty);
    return;
  }
  const now = Date.now();
  for (const reminder of reminders) {
    const row = document.createElement("div");
    row.className = "task";
    const left = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = reminder.content;
    const due = document.createElement("span");
    const dueDate = new Date(reminder.due_at);
    due.textContent = `${dueDate.getTime() <= now ? "DUE · " : ""}${dueDate.toLocaleString()}`;
    left.append(title, due);
    const done = document.createElement("button");
    done.type = "button";
    done.className = "secondary";
    done.textContent = "Done";
    done.addEventListener("click", async () => {
      await api("/api/reminder-status", {
        method: "POST",
        body: JSON.stringify({id: reminder.id, status: "done"}),
      });
      await loadReminders();
    });
    row.append(left, done);
    list.append(row);
  }
}

async function loadTasks(project) {
  activeProject = project || "";
  const list = $("taskList");
  list.replaceChildren();
  if (!activeProject) {
    setText("taskCount", "0");
    const empty = document.createElement("p");
    empty.className = "micro";
    empty.textContent = "Set an active project to create a work queue.";
    list.append(empty);
    return;
  }
  const tasks = await api(`/api/tasks?project=${encodeURIComponent(activeProject)}`);
  setText("taskCount", String(tasks.length));
  if (!tasks.length) {
    const empty = document.createElement("p");
    empty.className = "micro";
    empty.textContent = "No tasks yet.";
    list.append(empty);
  }
  for (const task of tasks) {
    const row = document.createElement("div");
    row.className = "task";
    const left = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = task.title;
    const detail = document.createElement("span");
    detail.textContent = task.details || task.status;
    left.append(title, detail);
    const select = document.createElement("select");
    for (const state of ["todo", "doing", "blocked", "done", "cancelled"]) {
      const option = document.createElement("option");
      option.value = state;
      option.textContent = state;
      option.selected = state === task.status;
      select.append(option);
    }
    select.addEventListener("change", async () => {
      await api("/api/task-status", {method: "POST", body: JSON.stringify({task_id: task.id, status: select.value})});
      await loadTasks(activeProject);
    });
    row.append(left, select);
    list.append(row);
  }
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const state = s.cognitive_state || {};
    setText("project", state.active_project || "No active project");
    setText("objective", state.objective || "No objective saved");
    setText("nextAction", state.next_action || "No next action saved");
    setText("home", s.home || "—");
    $("stateProject").value = state.active_project || "";
    $("stateObjective").value = state.objective || "";
    $("stateNext").value = state.next_action || "";
    const provider = s.provider || {};
    setText("modelBadge", provider.ok ? `MODEL ONLINE · ${s.selected_profile}` : "MODEL OFFLINE");
    $("modelBadge").className = `badge ${provider.ok ? "ok" : "bad"}`;
    const db = s.database || {};
    setText("dbBadge", db.ok ? "STATE VERIFIED" : "DB WARNING");
    $("dbBadge").className = `badge ${db.ok ? "ok" : "bad"}`;
    renderTools(s.tools || []);
    if ((state.active_project || "") !== activeProject) await loadTasks(state.active_project || "");
  } catch (err) {
    setText("modelBadge", "CORE ERROR");
    $("modelBadge").className = "badge bad";
  }
}

async function streamChat(message) {
  const target = addMessage("assistant", "");
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({message, conversation_id: currentConversation}),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const error = await response.json();
      detail = error.error || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  if (!response.body) throw new Error("Streaming response body unavailable");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalEvent = null;

  const processLine = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "meta") {
      setText("routeBadge", `${String(event.route).toUpperCase()} · ${event.profile} · STREAMING`);
    } else if (event.type === "delta") {
      target.p.textContent += event.text || "";
      $("messages").scrollTop = $("messages").scrollHeight;
    } else if (event.type === "error") {
      target.p.textContent = event.text || "Local model stream failed.";
    } else if (event.type === "done") {
      finalEvent = event;
      if (!target.p.textContent) target.p.textContent = event.answer || "";
      attachSources(target.article, event.sources || []);
      setText("routeBadge", `${String(event.route).toUpperCase()} · ${event.profile}`);
    }
  };

  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      processLine(line);
    }
    if (done) break;
  }
  buffer += decoder.decode();
  if (buffer.trim()) processLine(buffer);
  if (!finalEvent) throw new Error("Local model stream ended without a completion event");
  return finalEvent;
}

async function sendMessage(deep = false) {
  const input = $("message");
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  $("send").disabled = true;
  $("deepThink").disabled = true;
  if (deep) setText("routeBadge", "DEEP THINK RUNNING");
  try {
    let result;
    if (deep) {
      result = await api("/api/think", {
        method: "POST",
        body: JSON.stringify({message: text, conversation_id: currentConversation, attempts: 2}),
      });
      addMessage("assistant", result.answer, result.sources || []);
      setText("routeBadge", `DEEP THINK · ${result.attempts?.length || 0} SOLVERS · ${result.synthesis_profile || "local"}`);
    } else {
      result = await streamChat(text);
    }
    await loadConversations();
  } catch (err) {
    addMessage("assistant", `Local core error: ${err.message}`);
  } finally {
    $("send").disabled = false;
    $("deepThink").disabled = false;
    input.focus();
  }
}

$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendMessage(false);
});

$("deepThink").addEventListener("click", async () => {
  await sendMessage(true);
});

$("newConversation").addEventListener("click", async () => {
  const result = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({title: "New conversation"}),
  });
  currentConversation = result.conversation_id;
  await loadConversations();
  await loadHistory();
  $("message").focus();
});

$("checkpoint").addEventListener("click", async () => {
  $("checkpoint").disabled = true;
  try {
    const result = await api("/api/checkpoint", {method: "POST", body: JSON.stringify({reason: "ui-manual"})});
    setText("checkpointResult", `Saved #${result.id} · ${result.checksum.slice(0, 12)}…`);
  } catch (err) {
    setText("checkpointResult", err.message);
  } finally {
    $("checkpoint").disabled = false;
  }
});

$("stateForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/state", {method: "POST", body: JSON.stringify({
      active_project: $("stateProject").value.trim() || null,
      objective: $("stateObjective").value.trim() || null,
      next_action: $("stateNext").value.trim() || null,
    })});
    setText("stateResult", "Persistent state saved.");
    await refreshStatus();
  } catch (err) {
    setText("stateResult", err.message);
  }
});

$("reminderForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = $("reminderText").value.trim();
  const dueValue = $("reminderDue").value;
  if (!content || !dueValue) {
    setText("reminderResult", "Add both the future commitment and a due time.");
    return;
  }
  const due = new Date(dueValue);
  if (Number.isNaN(due.getTime())) {
    setText("reminderResult", "That due time is invalid.");
    return;
  }
  try {
    await api("/api/reminders", {
      method: "POST",
      body: JSON.stringify({content, due_at: due.toISOString(), source: "ui"}),
    });
    $("reminderText").value = "";
    $("reminderDue").value = "";
    setText("reminderResult", "Future memory saved locally.");
    await loadReminders();
  } catch (err) {
    setText("reminderResult", err.message);
  }
});

$("taskForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("taskTitle").value.trim();
  if (!activeProject) {
    setText("taskResult", "Set an active project first.");
    return;
  }
  if (!title) return;
  try {
    await api("/api/tasks", {method: "POST", body: JSON.stringify({project: activeProject, title})});
    $("taskTitle").value = "";
    setText("taskResult", "");
    await loadTasks(activeProject);
  } catch (err) {
    setText("taskResult", err.message);
  }
});

async function boot() {
  await refreshStatus();
  await loadConversations();
  await loadHistory();
  await loadReminders();
}

boot().catch((err) => {
  addMessage("assistant", `Startup error: ${err.message}`);
});

setInterval(async () => {
  await refreshStatus();
  await loadReminders();
}, 30000);

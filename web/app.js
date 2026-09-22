const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function addMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role === "user" ? "You" : "ColdVault";
  const p = document.createElement("p");
  p.textContent = text;
  article.append(label, p);
  $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const state = s.cognitive_state || {};
    $("project").textContent = state.active_project || "No active project";
    $("objective").textContent = state.objective || "No objective saved";
    $("nextAction").textContent = state.next_action || "No next action saved";
    $("home").textContent = s.home || "—";
    $("stateProject").value = state.active_project || "";
    $("stateObjective").value = state.objective || "";
    $("stateNext").value = state.next_action || "";
    const provider = s.provider || {};
    $("modelBadge").textContent = provider.ok ? `MODEL ONLINE · ${s.model}` : "MODEL OFFLINE";
    $("modelBadge").className = `badge ${provider.ok ? "ok" : "bad"}`;
  } catch (err) {
    $("modelBadge").textContent = "CORE ERROR";
    $("modelBadge").className = "badge bad";
  }
}

$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("message");
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  $("send").disabled = true;
  try {
    const result = await api("/api/chat", {method: "POST", body: JSON.stringify({message: text})});
    addMessage("assistant", result.answer);
  } catch (err) {
    addMessage("assistant", `Local core error: ${err.message}`);
  } finally {
    $("send").disabled = false;
    input.focus();
  }
});

$("checkpoint").addEventListener("click", async () => {
  $("checkpoint").disabled = true;
  try {
    const result = await api("/api/checkpoint", {method: "POST", body: JSON.stringify({reason: "ui-manual"})});
    $("checkpointResult").textContent = `Saved checkpoint ${result.id} · ${result.checksum.slice(0, 12)}…`;
  } catch (err) {
    $("checkpointResult").textContent = err.message;
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
    $("stateResult").textContent = "Persistent state saved.";
    await refreshStatus();
  } catch (err) {
    $("stateResult").textContent = err.message;
  }
});

refreshStatus();
setInterval(refreshStatus, 15000);

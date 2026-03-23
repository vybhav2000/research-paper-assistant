const state = {
  papers: [],
  activePaper: null,
  selectedChunkIds: new Set(),
  activeCitations: new Set(),
};

const els = {
  importForm: document.getElementById("import-form"),
  importStatus: document.getElementById("import-status"),
  paperQuery: document.getElementById("paper-query"),
  paperList: document.getElementById("paper-list"),
  paperCount: document.getElementById("paper-count"),
  heroPanel: document.getElementById("hero-panel"),
  paperMeta: document.getElementById("paper-meta"),
  workspaceGrid: document.getElementById("workspace-grid"),
  pdfFrame: document.getElementById("pdf-frame"),
  sourceLink: document.getElementById("source-link"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatMode: document.getElementById("chat-mode"),
  chatEngine: document.getElementById("chat-engine"),
  clearChat: document.getElementById("clear-chat"),
  highlightList: document.getElementById("highlight-list"),
  clearFocus: document.getElementById("clear-focus"),
  agentPanel: document.getElementById("agent-panel"),
  agentSteps: document.getElementById("agent-steps"),
  messageTemplate: document.getElementById("message-template"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed." }));
    throw new Error(error.detail || "Request failed.");
  }
  return response.json();
}

function renderLibrary() {
  els.paperCount.textContent = `${state.papers.length} paper${state.papers.length === 1 ? "" : "s"}`;
  if (!state.papers.length) {
    els.paperList.innerHTML = `<div class="empty-state">No papers yet.</div>`;
    return;
  }
  els.paperList.innerHTML = state.papers.map((paper) => `
    <article class="paper-item ${state.activePaper?.id === paper.id ? "active" : ""}" data-paper-id="${paper.id}">
      <div class="paper-title">${paper.title}</div>
      <div class="muted">${paper.authors.slice(0, 3).join(", ")}</div>
      <div class="muted mono">${paper.chunk_count} chunks</div>
    </article>
  `).join("");
  els.paperList.querySelectorAll("[data-paper-id]").forEach((node) => {
    node.addEventListener("click", () => loadPaper(node.dataset.paperId));
  });
}

function updateSelectionUi() {
  const count = state.selectedChunkIds.size;
  const scope = count ? "Highlight focus" : "Whole paper";
  const engine = els.chatEngine.value === "agentic" ? "Agentic" : "Standard";
  els.chatMode.textContent = `${scope} | ${engine}`;
}

function renderAgentSteps(steps = []) {
  if (!steps.length) {
    els.agentPanel.classList.add("hidden");
    els.agentSteps.innerHTML = "";
    return;
  }
  els.agentPanel.classList.remove("hidden");
  els.agentSteps.innerHTML = steps.map((step) => `<div class="agent-step">${step}</div>`).join("");
}

function renderMessages() {
  const messages = state.activePaper?.messages || [];
  if (!messages.length) {
    els.chatMessages.innerHTML = `<div class="empty-state">Ask a question about the paper, or click a saved highlight to use it as chat focus.</div>`;
    return;
  }
  els.chatMessages.innerHTML = "";
  for (const message of messages) {
    const fragment = els.messageTemplate.content.cloneNode(true);
    const root = fragment.querySelector(".message");
    root.classList.add(message.role);
    fragment.querySelector(".message-role").textContent = message.role === "assistant" ? "Assistant" : "You";
    fragment.querySelector(".message-content").textContent = message.content;
    const citations = message.citations?.length ? `Cites ${message.citations.length} chunk${message.citations.length === 1 ? "" : "s"}` : (message.selection_text ? "Selection-aware" : "");
    fragment.querySelector(".message-meta").textContent = citations;
    els.chatMessages.appendChild(fragment);
  }
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

function renderHighlights() {
  const highlights = state.activePaper?.highlights || [];
  if (!highlights.length) {
    els.highlightList.innerHTML = `<div class="empty-state">No saved highlights yet.</div>`;
    return;
  }
  els.highlightList.innerHTML = highlights.map((item) => `
    <article class="highlight-item">
      <div class="highlight-label">${item.label}</div>
      <div class="highlight-meta">${item.chunk_ids.length} chunk${item.chunk_ids.length === 1 ? "" : "s"} | ${new Date(item.created_at).toLocaleString()}</div>
      <p class="highlight-quote">${item.quote}</p>
      <button class="ghost-btn" type="button" data-highlight-id="${item.id}">Use in chat</button>
    </article>
  `).join("");
  els.highlightList.querySelectorAll("[data-highlight-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const target = highlights.find((item) => item.id === node.dataset.highlightId);
      if (!target) return;
      state.selectedChunkIds = new Set(target.chunk_ids);
      updateSelectionUi();
      els.chatInput.focus();
    });
  });
}

function renderPaperMeta() {
  if (!state.activePaper) return;
  els.paperMeta.innerHTML = `
    <p class="eyebrow">Active paper</p>
    <h2>${state.activePaper.title}</h2>
    <p class="muted">${state.activePaper.authors.join(", ")}</p>
  `;
}

function showWorkspace() {
  els.heroPanel.classList.add("hidden");
  els.paperMeta.classList.remove("hidden");
  els.workspaceGrid.classList.remove("hidden");
}

async function refreshLibrary(activePaperId = state.activePaper?.id) {
  state.papers = await request("/api/papers");
  renderLibrary();
  if (activePaperId) {
    await loadPaper(activePaperId);
  }
}

async function loadPaper(paperId) {
  state.activePaper = await request(`/api/papers/${paperId}`);
  state.selectedChunkIds = new Set();
  state.activeCitations = new Set();
  renderAgentSteps([]);
  renderLibrary();
  renderPaperMeta();
  els.pdfFrame.src = `${state.activePaper.pdf_url}#toolbar=1&navpanes=0&view=FitH`;
  els.sourceLink.href = state.activePaper.source_url;
  renderMessages();
  renderHighlights();
  updateSelectionUi();
  showWorkspace();
}

function appendTemporaryMessage(role, content) {
  if (!state.activePaper) return;
  state.activePaper.messages.push({ role, content, citations: [], selection_text: "" });
  renderMessages();
}

els.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = els.paperQuery.value.trim();
  if (!query) return;
  const button = els.importForm.querySelector("button");
  button.disabled = true;
  els.importStatus.textContent = "Fetching the paper, downloading the PDF, and building retrieval memory...";
  try {
    const paper = await request("/api/papers/import", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    els.paperQuery.value = "";
    els.importStatus.textContent = "Paper ready.";
    await refreshLibrary(paper.id);
  } catch (error) {
    els.importStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activePaper) return;
  const message = els.chatInput.value.trim();
  if (!message) return;
  const selectedChunkIds = Array.from(state.selectedChunkIds);
  const selectionText = state.activePaper.chunks
    .filter((chunk) => state.selectedChunkIds.has(chunk.id))
    .map((chunk) => chunk.content)
    .join("\n\n");
  appendTemporaryMessage("user", message);
  els.chatInput.value = "";
  try {
    const result = await request(`/api/papers/${state.activePaper.id}/chat`, {
      method: "POST",
      body: JSON.stringify({
        message,
        selected_chunk_ids: selectedChunkIds,
        selection_text: selectionText,
        mode: els.chatEngine.value,
      }),
    });
    const paper = await request(`/api/papers/${state.activePaper.id}`);
    state.activePaper.messages = paper.messages;
    state.activePaper.highlights = paper.highlights;
    state.activePaper.chunks = paper.chunks;
    state.activeCitations = new Set(result.citations);
    renderAgentSteps(result.agent_steps || []);
    renderMessages();
    updateSelectionUi();
  } catch (error) {
    renderAgentSteps([]);
    appendTemporaryMessage("assistant", `Error: ${error.message}`);
  }
});

els.clearFocus.addEventListener("click", () => {
  state.selectedChunkIds = new Set();
  state.activeCitations = new Set();
  updateSelectionUi();
});

els.chatEngine.addEventListener("change", () => {
  updateSelectionUi();
  if (els.chatEngine.value !== "agentic") {
    renderAgentSteps([]);
  }
});

els.clearChat.addEventListener("click", async () => {
  if (!state.activePaper) return;
  try {
    await request(`/api/papers/${state.activePaper.id}/chat`, { method: "DELETE" });
    state.activePaper.messages = [];
    renderAgentSteps([]);
    renderMessages();
  } catch (error) {
    window.alert(error.message || "Failed to clear chat history.");
  }
});

refreshLibrary().catch((error) => {
  els.importStatus.textContent = error.message;
});

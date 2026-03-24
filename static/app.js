const state = {
  papers: [],
  activePaper: null,
  selectedChunkIds: new Set(),
  activeCitations: new Set(),
  pendingChatBubble: null,
};

const els = {
  appShell: document.querySelector(".app-shell"),
  importForm: document.getElementById("import-form"),
  importStatus: document.getElementById("import-status"),
  paperQuery: document.getElementById("paper-query"),
  paperList: document.getElementById("paper-list"),
  paperCount: document.getElementById("paper-count"),
  clearLibrary: document.getElementById("clear-library"),
  toggleSidebar: document.getElementById("toggle-sidebar"),
  heroPanel: document.getElementById("hero-panel"),
  paperMeta: document.getElementById("paper-meta"),
  workspaceGrid: document.getElementById("workspace-grid"),
  pdfFrame: document.getElementById("pdf-frame"),
  sourceLink: document.getElementById("source-link"),
  summaryStatus: document.getElementById("summary-status"),
  createSummary: document.getElementById("create-summary"),
  paperSummary: document.getElementById("paper-summary"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatMode: document.getElementById("chat-mode"),
  clearChat: document.getElementById("clear-chat"),
  highlightList: document.getElementById("highlight-list"),
  clearFocus: document.getElementById("clear-focus"),
  messageTemplate: document.getElementById("message-template"),
  resizers: Array.from(document.querySelectorAll(".pane-resizer")),
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

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function applyInlineMarkdown(value) {
  return value
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}

function renderMarkdown(markdown = "") {
  const lines = escapeHtml(markdown).split("\n");
  const html = [];
  let inList = false;
  let inCodeBlock = false;
  let codeBuffer = [];

  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };

  const closeCodeBlock = () => {
    if (inCodeBlock) {
      html.push(`<pre><code>${codeBuffer.join("\n")}</code></pre>`);
      inCodeBlock = false;
      codeBuffer = [];
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      closeList();
      if (inCodeBlock) {
        closeCodeBlock();
      } else {
        inCodeBlock = true;
      }
      continue;
    }
    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }
    if (!line.trim()) {
      closeList();
      html.push("");
      continue;
    }
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      closeList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${applyInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }
    const listMatch = line.match(/^[-*]\s+(.*)$/);
    if (listMatch) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${applyInlineMarkdown(listMatch[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${applyInlineMarkdown(line)}</p>`);
  }

  closeList();
  closeCodeBlock();
  return html.join("");
}

function renderMath(container) {
  if (!container || typeof window.renderMathInElement !== "function") return;
  window.renderMathInElement(container, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\(", right: "\\)", display: false },
      { left: "\\[", right: "\\]", display: true },
    ],
    throwOnError: false,
  });
}

function setImportStatus(message, tone = "") {
  els.importStatus.className = ["muted", tone].filter(Boolean).join(" ");
  els.importStatus.innerHTML = message;
}

function renderLibrary() {
  els.paperCount.textContent = `${state.papers.length} paper${state.papers.length === 1 ? "" : "s"}`;
  els.clearLibrary.disabled = !state.papers.length;
  if (!state.papers.length) {
    els.paperList.innerHTML = `<div class="empty-state">No papers yet. Import an arXiv paper to build a workspace.</div>`;
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
  els.chatMode.textContent = `${scope} | Focused chat`;
}

function renderSummary(summaryMarkdown = "", status = "Ready", options = {}) {
  els.summaryStatus.textContent = status;
  if (!summaryMarkdown) {
    els.paperSummary.innerHTML = `<div class="empty-state">No summary yet. Create one only when you need it.</div>`;
    return;
  }
  if (options.html) {
    els.paperSummary.innerHTML = summaryMarkdown;
    return;
  }
  els.paperSummary.innerHTML = renderMarkdown(summaryMarkdown);
  renderMath(els.paperSummary);
}

function createThinkingMessage(label) {
  return {
    role: "assistant",
    content: `
      <div class="thinking-block">
        <span class="thinking-label">${escapeHtml(label)}</span>
        <span class="thinking-dots"><span></span><span></span><span></span></span>
      </div>
    `,
    citations: [],
    selection_text: "",
    html: true,
    pending: true,
  };
}

function renderMessages() {
  const messages = state.activePaper?.messages || [];
  if (!messages.length) {
    els.chatMessages.innerHTML = `<div class="empty-state">Ask a follow-up about the summary or click a saved highlight to focus the assistant on a specific part of the paper.</div>`;
    return;
  }
  els.chatMessages.innerHTML = "";
  for (const message of messages) {
    const fragment = els.messageTemplate.content.cloneNode(true);
    const root = fragment.querySelector(".message");
    root.classList.add(message.role);
    if (message.pending) root.classList.add("pending");
    fragment.querySelector(".message-role").textContent = message.role === "assistant" ? "Assistant" : "You";
    const contentNode = fragment.querySelector(".message-content");
    if (message.html) {
      contentNode.innerHTML = message.content;
    } else {
      contentNode.innerHTML = renderMarkdown(message.content);
      renderMath(contentNode);
    }
    const citations = message.citations?.length
      ? `Cites ${message.citations.length} chunk${message.citations.length === 1 ? "" : "s"}`
      : (message.selection_text ? "Selection-aware" : "");
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

function showHeroState() {
  els.heroPanel.classList.remove("hidden");
  els.paperMeta.classList.add("hidden");
  els.workspaceGrid.classList.add("hidden");
}

function clearPendingChatBubble() {
  if (!state.pendingChatBubble || !state.activePaper) return;
  const index = state.activePaper.messages.indexOf(state.pendingChatBubble);
  if (index >= 0) {
    state.activePaper.messages.splice(index, 1);
  }
  state.pendingChatBubble = null;
}

function pushPendingChatBubble(label) {
  if (!state.activePaper) return;
  clearPendingChatBubble();
  const bubble = createThinkingMessage(label);
  state.pendingChatBubble = bubble;
  state.activePaper.messages.push(bubble);
  renderMessages();
}

function resetWorkspaceState() {
  state.papers = [];
  state.activePaper = null;
  state.selectedChunkIds = new Set();
  state.activeCitations = new Set();
  state.pendingChatBubble = null;
  els.paperMeta.innerHTML = "";
  els.pdfFrame.src = "";
  els.sourceLink.href = "#";
  renderSummary("", "Not created");
  renderMessages();
  renderHighlights();
  updateSelectionUi();
  renderLibrary();
  showHeroState();
}

async function refreshLibrary(activePaperId = state.activePaper?.id) {
  state.papers = await request("/api/papers");
  renderLibrary();
  if (activePaperId) {
    await loadPaper(activePaperId);
    return;
  }
  if (!state.papers.length) {
    resetWorkspaceState();
  }
}

async function loadPaper(paperId) {
  state.activePaper = await request(`/api/papers/${paperId}`);
  state.selectedChunkIds = new Set();
  state.activeCitations = new Set();
  state.pendingChatBubble = null;
  renderSummary("", "Checking");
  renderLibrary();
  renderPaperMeta();
  els.pdfFrame.src = `${state.activePaper.pdf_url}#toolbar=1&navpanes=0&view=FitH`;
  els.sourceLink.href = state.activePaper.source_url;
  renderMessages();
  renderHighlights();
  updateSelectionUi();
  showWorkspace();
  try {
    const summary = await request(`/api/papers/${paperId}/summary`);
    if (summary.summary_exists && summary.summary_markdown) {
      renderSummary(summary.summary_markdown, "Ready");
    } else {
      renderSummary("", "Not created");
    }
  } catch (error) {
    renderSummary(`## Summary unavailable\n\n${error.message}`, "Error");
  }
}

function appendTemporaryMessage(role, content) {
  if (!state.activePaper) return;
  state.activePaper.messages.push({ role, content, citations: [], selection_text: "" });
  renderMessages();
}

function initResizablePanes() {
  const config = {
    "app-shell": {
      property: "--sidebar-width",
      axis: "x",
      min: 260,
      max: 520,
    },
    "workspace-grid": {
      property: "--viewer-width",
      axis: "x",
      min: 38,
      max: 78,
      unit: "%",
    },
  };

  els.resizers.forEach((resizer) => {
    const target = config[resizer.dataset.resizeTarget];
    if (!target) return;
    resizer.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      resizer.setPointerCapture(event.pointerId);
      document.body.classList.add("is-resizing");
      const onMove = (moveEvent) => {
        if (target.unit === "%") {
          const rect = els.workspaceGrid.getBoundingClientRect();
          const percent = ((moveEvent.clientX - rect.left) / rect.width) * 100;
          const clamped = Math.min(target.max, Math.max(target.min, percent));
          document.documentElement.style.setProperty(target.property, `${clamped}%`);
          return;
        }
        const clamped = Math.min(target.max, Math.max(target.min, moveEvent.clientX - els.appShell.getBoundingClientRect().left));
        document.documentElement.style.setProperty(target.property, `${clamped}px`);
      };
      const onUp = () => {
        document.body.classList.remove("is-resizing");
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp, { once: true });
    });
  });
}

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  els.toggleSidebar.textContent = collapsed ? "▸" : "◂";
  els.toggleSidebar.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
}

els.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = els.paperQuery.value.trim();
  if (!query) return;
  const button = els.importForm.querySelector("button");
  button.disabled = true;
  setImportStatus(
    `<span class="status-inline"><span class="search-spinner"></span><span>Searching arXiv, fetching the PDF, and building the workspace...</span></span>`,
    "status-live"
  );
  try {
    const paper = await request("/api/papers/import", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    els.paperQuery.value = "";
    setImportStatus("Paper ready.");
    await refreshLibrary(paper.id);
  } catch (error) {
    setImportStatus(error.message);
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
  pushPendingChatBubble("Thinking");
  els.chatInput.value = "";
  try {
    const result = await request(`/api/papers/${state.activePaper.id}/chat`, {
      method: "POST",
      body: JSON.stringify({
        message,
        selected_chunk_ids: selectedChunkIds,
        selection_text: selectionText,
      }),
    });
    const paper = await request(`/api/papers/${state.activePaper.id}`);
    state.activePaper.messages = paper.messages;
    state.activePaper.highlights = paper.highlights;
    state.activePaper.chunks = paper.chunks;
    state.activeCitations = new Set(result.citations);
    state.pendingChatBubble = null;
    renderMessages();
    updateSelectionUi();
  } catch (error) {
    clearPendingChatBubble();
    renderMessages();
    appendTemporaryMessage("assistant", `Error: ${error.message}`);
  }
});

els.clearFocus.addEventListener("click", () => {
  state.selectedChunkIds = new Set();
  state.activeCitations = new Set();
  updateSelectionUi();
});

els.clearLibrary.addEventListener("click", async () => {
  if (!state.papers.length) return;
  const confirmed = window.confirm("Clear the full library, including imported PDFs, summaries, chat history, and highlights?");
  if (!confirmed) return;
  els.clearLibrary.disabled = true;
  try {
    await request("/api/papers", { method: "DELETE" });
    setImportStatus("Library cleared.");
    resetWorkspaceState();
  } catch (error) {
    setImportStatus(error.message || "Failed to clear library.");
    renderLibrary();
  }
});

els.createSummary.addEventListener("click", async () => {
  if (!state.activePaper) return;
  els.createSummary.disabled = true;
  renderSummary(
    `
    <div class="thinking-block">
      <span class="thinking-label">Creating summary</span>
      <span class="thinking-dots"><span></span><span></span><span></span></span>
    </div>
    `,
    "Creating",
    { html: true }
  );
  try {
    const summary = await request(`/api/papers/${state.activePaper.id}/summary`, {
      method: "POST",
    });
    renderSummary(summary.summary_markdown, "Ready");
  } catch (error) {
    renderSummary(`## Summary unavailable\n\n${error.message}`, "Error");
  } finally {
    els.createSummary.disabled = false;
  }
});

els.clearChat.addEventListener("click", async () => {
  if (!state.activePaper) return;
  try {
    await request(`/api/papers/${state.activePaper.id}/chat`, { method: "DELETE" });
    state.activePaper.messages = [];
    state.pendingChatBubble = null;
    renderMessages();
  } catch (error) {
    window.alert(error.message || "Failed to clear chat history.");
  }
});

els.toggleSidebar.addEventListener("click", () => {
  setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
});

initResizablePanes();
setSidebarCollapsed(false);

refreshLibrary().catch((error) => {
  setImportStatus(error.message);
});

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ROOT_ID = "filexa2comfyui-root";
const POSITION_KEY = "filexa2comfyui-position";
const ICON_URL = new URL("./filexa.webp", import.meta.url).toString();
const SNAPSHOT_TARGETS = [
  { id: "t2i", label: "Text to Image", short: "T2I", group: "Image" },
  { id: "i2i", label: "Image to Image", short: "I2I", group: "Image" },
  { id: "t2v", label: "Text to Video", short: "T2V", group: "Video" },
  { id: "i2v", label: "Image to Video", short: "I2V", group: "Video" },
];

function installStylesheet() {
  if (document.getElementById("filexa2comfyui-css")) {
    return;
  }
  const link = document.createElement("link");
  link.id = "filexa2comfyui-css";
  link.rel = "stylesheet";
  link.href = new URL("./filexa2comfyui.css", import.meta.url).toString();
  document.head.append(link);
}

async function request(path, options = {}) {
  const fetcher = api?.fetchApi ? api.fetchApi.bind(api) : fetch;
  const response = await fetcher(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function looksLikeApiWorkflow(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return Object.values(value).some((node) => {
    return node && typeof node === "object" && node.inputs && node.class_type;
  });
}

async function currentWorkflows() {
  let promptData = {};
  if (typeof app.graphToPrompt === "function") {
    promptData = await app.graphToPrompt();
  }
  const candidates = [
    promptData.output,
    promptData.prompt,
    promptData.api_workflow,
    promptData.workflow,
  ];
  const apiWorkflow = candidates.find(looksLikeApiWorkflow);
  const uiWorkflow = !looksLikeApiWorkflow(promptData.workflow) && promptData.workflow
    ? promptData.workflow
    : app.graph?.serialize
      ? app.graph.serialize()
      : {};
  if (!apiWorkflow) {
    throw new Error("Could not read the current API workflow from ComfyUI.");
  }
  return { api_workflow: apiWorkflow, ui_workflow: uiWorkflow };
}

function createElement(tag, attrs = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") {
      element.className = value;
    } else if (key === "text") {
      element.textContent = value;
    } else if (key === "html") {
      element.innerHTML = value;
    } else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2), value);
    } else if (value !== undefined && value !== null) {
      element.setAttribute(key, value);
    }
  }
  for (const child of children) {
    element.append(child);
  }
  return element;
}

function snapshotText(snapshot) {
  if (!snapshot?.saved) {
    return "Workflow not captured";
  }
  const saved = snapshot.saved_at_utc ? new Date(snapshot.saved_at_utc).toLocaleString() : "-";
  const prompt = snapshot.prompt_binding
    ? `${snapshot.prompt_binding.node_id}.${snapshot.prompt_binding.input}`
    : "-";
  const image = snapshot.image_binding
    ? `${snapshot.image_binding.node_id}.${snapshot.image_binding.input}`
    : "text only";
  return [
    `Saved: ${saved}`,
    `Nodes: ${snapshot.node_count || 0}`,
    `Prompt: ${prompt}`,
    `Image input: ${image}`,
    `Model: ${snapshot.model_hint || "-"}`,
    ...(snapshot.issues?.length ? [`Issue: ${snapshot.issues.join(" ")}`] : []),
  ].join("\n");
}

function snapshotDotClass(snapshot) {
  if (!snapshot?.saved) {
    return "empty";
  }
  return snapshot.valid ? "ready" : "invalid";
}

function statusText(state) {
  const lines = [
    `Version: ${state.version || "-"}`,
    `Status: ${state.status || "-"}`,
    `Last event: ${state.last_event || "-"}`,
    `Token saved: ${state.token_saved ? "yes" : "no"}`,
    `ComfyUI URL: ${state.comfyui_url || "-"}`,
    `Polls: ${state.poll_count || 0}`,
  ];
  if (state.active_job_id) {
    lines.push(`Active job: ${state.active_job_id}`);
    lines.push(`Kind: ${state.active_kind || "-"}`);
    lines.push(`ComfyUI prompt: ${state.active_prompt_id || "-"}`);
    lines.push(`Elapsed: ${state.elapsed || "-"}`);
    lines.push(`Stage: ${state.live_status || "-"}${state.live_progress !== null && state.live_progress !== undefined ? ` (${state.live_progress}%)` : ""}`);
    lines.push(`Prompt: ${state.active_prompt_preview || "-"}`);
  }
  if (state.last_duration_seconds) {
    lines.push(`Last duration: ${state.last_duration_seconds.toFixed(1)}s`);
  }
  if (state.network_notice) {
    lines.push(state.network_notice);
  }
  if (state.last_error) {
    lines.push(`Last error: ${state.last_error}`);
  }
  return lines.join("\n");
}

function createSnapshotGroup(groupName, targets, capture, summaries, dots) {
  return createElement("div", { class: "filexa2comfyui-snapshot-group" }, [
    createElement("strong", { text: `${groupName} workflows` }),
    createElement("div", { class: "filexa2comfyui-snapshot-row" }, targets.map((target) => {
      return createElement("div", { class: "filexa2comfyui-snapshot" }, [
        createElement("div", { class: "filexa2comfyui-snapshot-title" }, [
          dots[target.id],
          createElement("span", { text: `${target.label} (${target.short})` }),
        ]),
        createElement("button", {
          text: "Capture Current Workflow",
          onclick: async () => {
            try {
              await capture(target.id);
            } catch (error) {
              alert(error.message || error);
            }
          },
        }),
        summaries[target.id],
      ]);
    })),
  ]);
}

function loadSavedPosition(root) {
  try {
    const raw = window.localStorage.getItem(POSITION_KEY);
    if (!raw) {
      return;
    }
    const position = JSON.parse(raw);
    const left = Number(position.left);
    const top = Number(position.top);
    if (!Number.isFinite(left) || !Number.isFinite(top)) {
      return;
    }
    root.style.left = `${Math.max(0, Math.min(window.innerWidth - 80, left))}px`;
    root.style.top = `${Math.max(0, Math.min(window.innerHeight - 40, top))}px`;
    root.style.right = "auto";
    root.style.bottom = "auto";
  } catch (_error) {
    window.localStorage.removeItem(POSITION_KEY);
  }
}

function savePosition(root) {
  const rect = root.getBoundingClientRect();
  window.localStorage.setItem(
    POSITION_KEY,
    JSON.stringify({ left: Math.round(rect.left), top: Math.round(rect.top) }),
  );
}

function installDrag(root, handle) {
  let dragging = null;
  handle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = root.getBoundingClientRect();
    root.style.left = `${rect.left}px`;
    root.style.top = `${rect.top}px`;
    root.style.right = "auto";
    root.style.bottom = "auto";
    dragging = {
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    handle.setPointerCapture(event.pointerId);
    root.classList.add("filexa2comfyui-dragging");
  });
  handle.addEventListener("pointermove", (event) => {
    if (!dragging || event.pointerId !== dragging.pointerId) {
      return;
    }
    event.preventDefault();
    const rect = root.getBoundingClientRect();
    const maxLeft = Math.max(0, window.innerWidth - rect.width);
    const maxTop = Math.max(0, window.innerHeight - 38);
    root.style.left = `${Math.max(0, Math.min(maxLeft, event.clientX - dragging.offsetX))}px`;
    root.style.top = `${Math.max(0, Math.min(maxTop, event.clientY - dragging.offsetY))}px`;
  });
  const finish = (event) => {
    if (!dragging || event.pointerId !== dragging.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    handle.releasePointerCapture(event.pointerId);
    dragging = null;
    root.classList.remove("filexa2comfyui-dragging");
    savePosition(root);
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
}

function renderReferencePreviews(container, previews) {
  container.innerHTML = "";
  const visiblePreviews = Array.isArray(previews) ? previews.filter((item) => item?.data_url) : [];
  if (!visiblePreviews.length) {
    container.classList.add("filexa2comfyui-hidden");
    return;
  }
  container.classList.remove("filexa2comfyui-hidden");
  container.append(createElement("h3", { text: "Filexa reference" }));
  const grid = createElement("div", { class: "filexa2comfyui-reference-grid" });
  for (const preview of visiblePreviews) {
    const label = preview.label || "reference";
    grid.append(
      createElement("figure", { class: "filexa2comfyui-reference-card" }, [
        createElement("img", { src: preview.data_url, alt: label }),
        createElement("figcaption", { text: label }),
      ]),
    );
  }
  container.append(grid);
}

function keepPanelInViewport(panel) {
  panel.style.left = "";
  panel.style.right = "0";
  window.requestAnimationFrame(() => {
    const rect = panel.getBoundingClientRect();
    if (rect.left < 8) {
      panel.style.left = "0";
      panel.style.right = "auto";
      return;
    }
    if (rect.right > window.innerWidth - 8) {
      panel.style.left = "auto";
      panel.style.right = "0";
    }
  });
}

function buildPanel() {
  const root = createElement("div", { id: ROOT_ID });
  loadSavedPosition(root);
  const dragHandle = createElement("span", {
    class: "filexa2comfyui-drag-handle",
    text: "::",
    title: "Drag Filexa panel",
  });
  const toggle = createElement("button", {
    class: "filexa2comfyui-button",
    title: "Open Filexa2ComfyUI",
  }, [
    dragHandle,
    createElement("img", { class: "filexa2comfyui-icon", src: ICON_URL, alt: "" }),
    createElement("span", { text: "Filexa" }),
  ]);
  const panel = createElement("div", { class: "filexa2comfyui-panel filexa2comfyui-hidden" });
  installDrag(root, dragHandle);

  const dot = createElement("span", { class: "filexa2comfyui-dot" });
  const statusLabel = createElement("span", { text: "CONFIGURE" });
  const closeButton = createElement("button", { text: "Close", onclick: () => panel.classList.add("filexa2comfyui-hidden") });

  const apiUrl = createElement("input", { type: "url", placeholder: "https://your-filexa-api.example" });
  const token = createElement("input", { type: "password", placeholder: "flx_comfyui_..." });
  const comfyUrl = createElement("input", { type: "url", placeholder: window.location.origin, value: window.location.origin });
  const enabled = createElement("input", { type: "checkbox" });
  enabled.checked = true;
  const compress = createElement("input", { type: "checkbox" });
  compress.checked = true;
  const localOnly = createElement("input", { type: "checkbox" });

  const snapshotSummaries = Object.fromEntries(
    SNAPSHOT_TARGETS.map((target) => [target.id, createElement("div", { class: "filexa2comfyui-muted" })]),
  );
  const snapshotDots = Object.fromEntries(
    SNAPSHOT_TARGETS.map((target) => [target.id, createElement("span", { class: "filexa2comfyui-snapshot-dot empty" })]),
  );
  const statusBox = createElement("div", { class: "filexa2comfyui-status" });
  const referencePreviewBox = createElement("section", {
    class: "filexa2comfyui-grid filexa2comfyui-reference-preview filexa2comfyui-hidden",
  });
  const diagnostics = createElement("ul", { class: "filexa2comfyui-diagnostics" });

  async function refresh() {
    const state = await request("/filexa2comfyui/status");
    apiUrl.value = state.api_url || apiUrl.value || "";
    comfyUrl.value = state.comfyui_url || comfyUrl.value || window.location.origin;
    enabled.checked = !!state.enabled;
    compress.checked = !!state.compress_images_before_upload;
    localOnly.checked = !!state.keep_result_on_pc_only;
    const cleanStatus = state.active_job_id ? "running" : (state.status || "configure");
    dot.className = `filexa2comfyui-dot ${cleanStatus}`;
    statusLabel.textContent = cleanStatus.toUpperCase();
    for (const target of SNAPSHOT_TARGETS) {
      const snapshot = state.snapshots?.[target.id];
      snapshotSummaries[target.id].textContent = snapshotText(snapshot);
      snapshotDots[target.id].className = `filexa2comfyui-snapshot-dot ${snapshotDotClass(snapshot)}`;
    }
    statusBox.textContent = statusText(state);
    renderReferencePreviews(referencePreviewBox, state.reference_previews);
    diagnostics.innerHTML = "";
    for (const item of state.diagnostics || []) {
      diagnostics.append(createElement("li", { text: item }));
    }
    return state;
  }

  async function saveConfig(connect) {
    const state = await request("/filexa2comfyui/config", {
      method: "POST",
      body: JSON.stringify({
        api_url: apiUrl.value,
        token: token.value,
        comfyui_url: comfyUrl.value || window.location.origin,
        enabled: connect,
        compress_images_before_upload: compress.checked,
        keep_result_on_pc_only: localOnly.checked,
      }),
    });
    token.value = "";
    await refresh();
    return state;
  }

  async function capture(target) {
    const workflows = await currentWorkflows();
    await request("/filexa2comfyui/capture", {
      method: "POST",
      body: JSON.stringify({
        target,
        ...workflows,
      }),
    });
    await refresh();
  }

  const connectButton = createElement("button", {
    class: "primary",
    text: "Connect / Save",
    onclick: async () => {
      try {
        await saveConfig(true);
      } catch (error) {
        alert(error.message || error);
      }
    },
  });
  const disconnectButton = createElement("button", {
    class: "danger",
    text: "Disconnect",
    onclick: async () => {
      try {
        await request("/filexa2comfyui/disconnect", { method: "POST", body: "{}" });
        await refresh();
      } catch (error) {
        alert(error.message || error);
      }
    },
  });
  const cancelButton = createElement("button", {
    text: "Cancel active task",
    onclick: async () => {
      try {
        await request("/filexa2comfyui/cancel", { method: "POST", body: "{}" });
        await refresh();
      } catch (error) {
        alert(error.message || error);
      }
    },
  });

  panel.append(
    createElement("header", {}, [
      createElement("div", {}, [
        createElement("h2", { text: "Filexa2ComfyUI" }),
        createElement("div", { class: "filexa2comfyui-pill" }, [dot, statusLabel]),
      ]),
      closeButton,
    ]),
    createElement("section", { class: "filexa2comfyui-grid" }, [
      createElement("h3", { text: "Connection" }),
      createElement("div", { class: "filexa2comfyui-field" }, [
        createElement("label", { text: "Filexa server URL" }),
        apiUrl,
      ]),
      createElement("div", { class: "filexa2comfyui-field" }, [
        createElement("label", { text: "Connection token" }),
        token,
      ]),
      createElement("div", { class: "filexa2comfyui-field" }, [
        createElement("label", { text: "ComfyUI URL" }),
        comfyUrl,
      ]),
      createElement("label", { class: "filexa2comfyui-row" }, [enabled, document.createTextNode("Enable connector")]),
      createElement("label", { class: "filexa2comfyui-row" }, [compress, document.createTextNode("JPEG fallback before upload")]),
      createElement("label", { class: "filexa2comfyui-row" }, [localOnly, document.createTextNode("Keep result on this PC only")]),
      createElement("div", { class: "filexa2comfyui-row" }, [connectButton, disconnectButton, cancelButton]),
    ]),
    createElement("section", { class: "filexa2comfyui-grid" }, [
      createElement("h3", { text: "Snapshots" }),
      createElement("div", { class: "filexa2comfyui-hint" }, [
        document.createTextNode("Capture the exact workflow for each route. If a route is red, add the missing prompt or image input and capture it again."),
      ]),
      createSnapshotGroup("Image", SNAPSHOT_TARGETS.filter((target) => target.group === "Image"), capture, snapshotSummaries, snapshotDots),
      createSnapshotGroup("Video", SNAPSHOT_TARGETS.filter((target) => target.group === "Video"), capture, snapshotSummaries, snapshotDots),
    ]),
    createElement("section", { class: "filexa2comfyui-grid" }, [
      createElement("h3", { text: "Status" }),
      statusBox,
      createElement("button", {
        text: "Refresh status",
        onclick: async () => {
          try {
            await refresh();
          } catch (error) {
            alert(error.message || error);
          }
        },
      }),
    ]),
    referencePreviewBox,
    createElement("section", { class: "filexa2comfyui-grid" }, [
      createElement("h3", { text: "Diagnostics" }),
      diagnostics,
    ]),
  );

  toggle.addEventListener("click", async () => {
    panel.classList.toggle("filexa2comfyui-hidden");
    if (!panel.classList.contains("filexa2comfyui-hidden")) {
      keepPanelInViewport(panel);
      try {
        await refresh();
      } catch (error) {
        statusBox.textContent = error.message || String(error);
      }
    }
  });

  root.append(toggle, panel);
  document.body.append(root);
  refresh().catch(() => {});
  window.setInterval(() => {
    if (!panel.classList.contains("filexa2comfyui-hidden")) {
      refresh().catch(() => {});
    }
  }, 3000);
}

app.registerExtension({
  name: "Filexa.Filexa2ComfyUI",
  async setup() {
    if (document.getElementById(ROOT_ID)) {
      return;
    }
    installStylesheet();
    buildPanel();
  },
});

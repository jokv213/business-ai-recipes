(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);

  const elements = {
    appStatus: $("#app-status"),
    configStatus: $("#config-status"),
    appVersion: $("#app-version"),
    demoButton: $("#demo-button"),
    videoFile: $("#video-file"),
    subtitleFile: $("#subtitle-file"),
    sourceVideo: $("#source-video"),
    videoEmpty: $("#video-empty"),
    subtitleOverlay: $("#subtitle-overlay"),
    sourceName: $("#source-name"),
    sourceDetails: $("#source-details"),
    playbackTime: $("#playback-time"),
    sourceDuration: $("#source-duration"),
    selectedOnly: $("#selected-only"),
    playbackNote: $("#playback-note"),
    transcriptSearch: $("#transcript-search"),
    transcriptList: $("#transcript-list"),
    transcriptEmpty: $("#transcript-empty"),
    cueCount: $("#cue-count"),
    selectionUndo: $("#selection-undo"),
    selectionReset: $("#selection-reset"),
    selectionAll: $("#selection-all"),
    selectionNone: $("#selection-none"),
    timelineTrack: $("#timeline-track"),
    timelinePlayhead: $("#timeline-playhead"),
    timelineEmpty: $("#timeline-empty"),
    timelineSourceDuration: $("#timeline-source-duration"),
    timelineRangeNote: $("#timeline-range-note"),
    selectedDuration: $("#selected-duration"),
    selectedCueCount: $("#selected-cue-count"),
    sourceDurationCard: $("#source-duration-card"),
    retainedDurationCard: $("#retained-duration-card"),
    paddingRange: $("#padding-range"),
    paddingValue: $("#padding-value"),
    goalInput: $("#goal-input"),
    keywordsButton: $("#keywords-button"),
    jevButton: $("#jev-button"),
    jevConsentRow: $("#jev-consent-row"),
    jevConsent: $("#jev-consent"),
    suggestionMode: $("#suggestion-mode"),
    suggestionStatus: $("#suggestion-status"),
    suggestionDetail: $("#suggestion-detail"),
    exportButton: $("#export-button"),
    exportStatus: $("#export-status"),
    outputPanel: $("#output-panel"),
    outputVideo: $("#output-video"),
    outputMeta: $("#output-meta"),
    downloadLinks: $("#download-links"),
  };

  const state = {
    config: {
      ffmpeg: false,
      jev_available: false,
      jev_scope: "demo",
      max_upload_mb: 512,
      version: "0.1.0",
    },
    project: null,
    cues: [],
    selection: new Set(),
    selectionHistory: [],
    padding: 0.12,
    transcriptFilter: "",
    selectedOnly: false,
    exporting: false,
    uploading: false,
    playbackJumping: false,
    pendingSeek: null,
    operation: {
      token: 0,
      kind: "",
      projectId: null,
    },
  };

  function finiteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function formatTime(value, precision = 1) {
    const seconds = Math.max(0, finiteNumber(value));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    const renderedSeconds = remainder.toFixed(precision).padStart(precision === 0 ? 2 : 4, "0");
    if (hours > 0) {
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${renderedSeconds}`;
    }
    return `${String(minutes).padStart(2, "0")}:${renderedSeconds}`;
  }

  function formatBytes(value) {
    const bytes = Math.max(0, finiteNumber(value));
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  }

  function sameOriginUrl(value) {
    if (typeof value !== "string" || value.trim() === "") return "";
    try {
      const url = new URL(value, window.location.origin);
      if (url.origin !== window.location.origin) return "";
      return url.href;
    } catch {
      return "";
    }
  }

  function setStatus(message, kind = "") {
    elements.appStatus.textContent = message;
    elements.appStatus.classList.toggle("is-error", kind === "error");
    elements.appStatus.classList.toggle("is-busy", kind === "busy");
  }

  function setSuggestionStatus(message, kind = "") {
    elements.suggestionStatus.textContent = message;
    elements.suggestionStatus.classList.toggle("is-error", kind === "error");
  }

  function setExportStatus(message, kind = "") {
    elements.exportStatus.textContent = message;
    elements.exportStatus.classList.toggle("is-error", kind === "error");
    elements.exportStatus.classList.toggle("is-busy", kind === "busy");
  }

  async function request(path, options = {}) {
    const requestOptions = {
      method: options.method || "GET",
      headers: { ...(options.headers || {}) },
    };
    if (options.json !== undefined) {
      requestOptions.headers["Content-Type"] = "application/json";
      requestOptions.body = JSON.stringify(options.json);
    } else if (options.body !== undefined) {
      requestOptions.body = options.body;
    }

    const response = await fetch(path, requestOptions);
    const contentType = response.headers.get("content-type") || "";
    let payload = null;
    if (contentType.includes("application/json")) {
      payload = await response.json();
    } else {
      const text = await response.text();
      payload = text ? { error: text } : null;
    }
    if (!response.ok) {
      const message = payload && typeof payload.error === "string" ? payload.error : `Request failed (${response.status})`;
      throw new Error(message);
    }
    return payload;
  }

  function normaliseCue(cue, index) {
    const start = finiteNumber(cue && cue.start, NaN);
    const end = finiteNumber(cue && cue.end, NaN);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
    return {
      id: String((cue && cue.id) || `cue-${String(index + 1).padStart(4, "0")}`),
      start,
      end,
      text: String((cue && cue.text) || ""),
    };
  }

  function normaliseProject(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const cues = Array.isArray(source.cues) ? source.cues.map(normaliseCue).filter(Boolean) : [];
    return {
      ...source,
      id: String(source.id || ""),
      name: String(source.name || "Untitled source"),
      video_url: sameOriginUrl(source.video_url),
      duration: Math.max(0, finiteNumber(source.duration)),
      width: Math.max(0, finiteNumber(source.width)),
      height: Math.max(0, finiteNumber(source.height)),
      has_audio: Boolean(source.has_audio),
      is_demo: Boolean(source.is_demo),
      suggested_goal: String(source.suggested_goal || ""),
      cues,
    };
  }

  function sourceDuration() {
    const videoDuration = finiteNumber(elements.sourceVideo.duration);
    if (videoDuration > 0) return videoDuration;
    return state.project ? state.project.duration : 0;
  }

  function sortedSelectedCues() {
    return state.cues
      .filter((cue) => state.selection.has(cue.id))
      .slice()
      .sort((left, right) => left.start - right.start || left.end - right.end);
  }

  function selectedIntervals() {
    const duration = sourceDuration();
    const padding = Math.min(1, Math.max(0, state.padding));
    const intervals = [];
    for (const cue of sortedSelectedCues()) {
      const start = Math.max(0, cue.start - padding);
      const end = Math.min(duration > 0 ? duration : cue.end + padding, cue.end + padding);
      if (end <= start) continue;
      const previous = intervals[intervals.length - 1];
      if (previous && start <= previous.end + 0.001) {
        previous.end = Math.max(previous.end, end);
      } else {
        intervals.push({ start, end });
      }
    }
    return intervals;
  }

  function retainedDuration() {
    return selectedIntervals().reduce((total, interval) => total + (interval.end - interval.start), 0);
  }

  function setButtonBusy(button, busy) {
    if (!button) return;
    if (busy) {
      button.disabled = true;
      button.classList.add("is-loading");
      button.setAttribute("aria-busy", "true");
    } else {
      button.classList.remove("is-loading");
      button.removeAttribute("aria-busy");
    }
  }

  function beginOperation(kind, projectId = null) {
    if (state.operation.kind) return null;
    state.operation = {
      token: state.operation.token + 1,
      kind,
      projectId,
    };
    updateOperationUi();
    return { ...state.operation };
  }

  function operationStillCurrent(operation) {
    if (!operation) return false;
    return state.operation.token === operation.token
      && state.operation.kind === operation.kind
      && (!operation.projectId || (state.project && state.project.id === operation.projectId));
  }

  function finishOperation(operation) {
    if (!operation || state.operation.token !== operation.token) return false;
    state.operation = {
      token: operation.token,
      kind: "",
      projectId: null,
    };
    updateActionButtons();
    return true;
  }

  function releaseOperationButton(operation, button) {
    if (operation && state.operation.token === operation.token) setButtonBusy(button, false);
    finishOperation(operation);
  }

  function updateOperationUi() {
    const busy = Boolean(state.operation.kind);
    document.body.classList.toggle("operation-busy", busy);
    const main = document.querySelector("main");
    if (main) main.setAttribute("aria-busy", String(busy));
    const controls = [
      elements.demoButton,
      elements.videoFile,
      elements.subtitleFile,
      elements.transcriptSearch,
      elements.selectionUndo,
      elements.selectionReset,
      elements.selectionAll,
      elements.selectionNone,
      elements.selectedOnly,
      elements.paddingRange,
      elements.goalInput,
      elements.keywordsButton,
      elements.jevButton,
      elements.jevConsent,
      elements.exportButton,
    ];
    for (const control of controls) {
      if (busy && control) control.disabled = true;
    }
    document.querySelectorAll("#transcript-list input, #transcript-list button, #timeline-track .timeline-segment").forEach((control) => {
      control.disabled = busy;
    });
    document.querySelectorAll(".file-button").forEach((label) => {
      label.classList.toggle("is-disabled", busy);
    });
  }

  function projectLoaded() {
    return Boolean(state.project && state.project.id);
  }

  function isRecordedDemoGoal() {
    if (!state.project || !state.project.is_demo) return false;
    const suggested = state.project.suggested_goal.trim();
    const entered = elements.goalInput.value.trim();
    return suggested !== "" && entered === suggested;
  }

  function updateConfigStatus() {
    const media = state.config.ffmpeg ? "FFmpeg ready" : "FFmpeg unavailable";
    let jev = "Jev unavailable";
    if (state.config.jev_available) {
      jev = state.config.jev_scope === "all" ? "Jev opt-in" : "Recorded Jev";
    }
    elements.configStatus.textContent = `${media} · ${jev}`;
    elements.appVersion.textContent = String(state.config.version || "0.1.0");
  }

  function updateJevControls() {
    const hasCues = state.cues.length > 0;
    const available = Boolean(state.config.jev_available && projectLoaded() && hasCues && state.cues.length <= 30);
    const allScope = state.config.jev_scope === "all";
    const recordedAllowed = available && isRecordedDemoGoal();
    const consented = Boolean(elements.jevConsent.checked);
    const liveAllowed = available && allScope && consented;

    elements.jevConsentRow.hidden = !allScope || !state.config.jev_available;
    elements.jevConsent.disabled = !available;
    if (!allScope) elements.jevConsent.checked = false;

    elements.jevButton.disabled = !(recordedAllowed || liveAllowed);
    const tag = elements.jevButton.querySelector(".demo-tag");
    if (tag) tag.textContent = allScope ? "opt-in" : "demo only";

    if (!available) {
      if (!projectLoaded()) {
        elements.suggestionDetail.textContent = "Load the sample to try recorded guidance, or import subtitles for keyword selection.";
      } else if (!state.config.jev_available) {
        elements.suggestionDetail.textContent = "Jev guidance is unavailable in this workspace. Keyword matching still works.";
      } else if (!hasCues) {
        elements.suggestionDetail.textContent = "Add subtitles before asking for a suggestion.";
      } else if (state.cues.length > 30) {
        elements.suggestionDetail.textContent = "Jev suggestions support up to 30 cues per request. Use keyword selection for longer transcripts.";
      } else {
        elements.suggestionDetail.textContent = "Jev guidance needs a valid project and transcript.";
      }
    } else if (!recordedAllowed && !liveAllowed && state.project && state.project.is_demo && !allScope) {
      elements.suggestionDetail.textContent = "Use the suggested demo goal for the recorded Jev guidance. Imported material stays keyword-only here.";
    } else if (!recordedAllowed && !liveAllowed && allScope) {
      elements.suggestionDetail.textContent = "Check consent to send subtitle text to TypeSafe. Video stays local.";
    }
  }

  function updateKeywordControls() {
    elements.keywordsButton.disabled = !(projectLoaded() && state.cues.length > 0 && elements.goalInput.value.trim() !== "");
  }

  function updateActionButtons() {
    const hasProject = projectLoaded();
    const hasCues = state.cues.length > 0;
    elements.demoButton.disabled = false;
    elements.videoFile.disabled = false;
    elements.subtitleFile.disabled = !hasProject;
    elements.transcriptSearch.disabled = !hasCues;
    elements.selectedOnly.disabled = !hasProject;
    elements.paddingRange.disabled = !hasCues;
    elements.goalInput.disabled = !hasProject;
    elements.selectionUndo.disabled = state.selectionHistory.length === 0;
    elements.selectionReset.disabled = !hasCues || state.selection.size === 0;
    elements.selectionAll.disabled = !hasCues;
    elements.selectionNone.disabled = !hasCues || state.selection.size === 0;
    elements.exportButton.disabled = !(hasProject && state.selection.size > 0 && state.config.ffmpeg && !state.exporting);
    if (!state.exporting) {
      if (!state.config.ffmpeg) {
        setExportStatus("FFmpeg is unavailable for export.");
      } else if (!hasProject || !hasCues) {
        setExportStatus("Select a source and subtitles before exporting.");
      } else if (state.selection.size === 0) {
        setExportStatus("Select at least one cue to export.");
      } else if (!elements.outputPanel.hidden) {
        setExportStatus("Ready for another export.");
      } else {
        setExportStatus("Ready to export the selected moments.");
      }
    }
    updateJevControls();
    updateKeywordControls();
    updateOperationUi();
  }

  function renderProjectMeta() {
    const project = state.project;
    if (!project) {
      elements.sourceName.textContent = "No source loaded";
      elements.sourceDetails.textContent = "—";
      elements.sourceDuration.textContent = formatTime(0);
      elements.sourceDurationCard.textContent = formatTime(0);
      return;
    }
    elements.sourceName.textContent = project.name;
    const dimensions = project.width > 0 && project.height > 0 ? `${project.width}×${project.height}` : "dimensions pending";
    const audio = project.has_audio ? "audio" : "silent source";
    elements.sourceDetails.textContent = `${dimensions} · ${audio} · ${state.cues.length} subtitle cues`;
    const duration = sourceDuration();
    elements.sourceDuration.textContent = formatTime(duration);
    elements.sourceDurationCard.textContent = formatTime(duration);
  }

  function renderTranscript() {
    const search = state.transcriptFilter.trim().toLocaleLowerCase();
    const visibleCues = state.cues.filter((cue) => !search || cue.text.toLocaleLowerCase().includes(search));
    elements.transcriptList.replaceChildren();
    elements.cueCount.textContent = search && visibleCues.length !== state.cues.length
      ? `${visibleCues.length}/${state.cues.length} cues`
      : `${state.cues.length} cues`;
    elements.transcriptEmpty.hidden = visibleCues.length > 0;
    elements.transcriptEmpty.textContent = state.cues.length === 0
      ? "Load subtitles to see the transcript."
      : "No cues match this search.";

    for (const [index, cue] of visibleCues.entries()) {
      const row = document.createElement("article");
      row.className = "cue-row";
      row.setAttribute("role", "listitem");
      row.classList.toggle("is-selected", state.selection.has(cue.id));

      const checkLabel = document.createElement("label");
      checkLabel.className = "cue-check-label";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selection.has(cue.id);
      checkbox.id = `cue-check-${index}`;
      checkbox.setAttribute("aria-label", `Keep cue at ${formatTime(cue.start)}`);
      checkbox.addEventListener("change", () => changeSelection(cue.id, checkbox.checked, "Selection updated."));
      const checkMark = document.createElement("span");
      checkMark.className = "checkbox-mark";
      checkMark.setAttribute("aria-hidden", "true");
      checkLabel.append(checkbox, checkMark);

      const copy = document.createElement("div");
      copy.className = "cue-copy";
      const cueTime = document.createElement("span");
      cueTime.className = "cue-time";
      cueTime.textContent = `${formatTime(cue.start)} — ${formatTime(cue.end)}`;
      const cueText = document.createElement("span");
      cueText.className = "cue-text";
      cueText.textContent = cue.text;
      copy.append(cueTime, cueText);

      const seekButton = document.createElement("button");
      seekButton.type = "button";
      seekButton.className = "cue-seek";
      seekButton.textContent = "Seek";
      seekButton.setAttribute("aria-label", `Seek to ${formatTime(cue.start)}`);
      seekButton.addEventListener("click", () => seekTo(cue.start, true));

      row.append(checkLabel, copy, seekButton);
      elements.transcriptList.append(row);
    }
  }

  function renderTimeline() {
    const duration = sourceDuration();
    const oldPlayhead = elements.timelinePlayhead;
    elements.timelineTrack.replaceChildren(oldPlayhead);
    const hasTimeline = state.cues.length > 0 && duration > 0;
    elements.timelineEmpty.hidden = hasTimeline;
    elements.timelineSourceDuration.textContent = formatTime(duration, 0);
    elements.timelineRangeNote.textContent = duration > 0 ? `Source range ${formatTime(duration)}` : "Source range —";

    if (hasTimeline) {
      for (const cue of state.cues) {
        const segment = document.createElement("button");
        segment.type = "button";
        segment.className = "timeline-segment";
        segment.classList.toggle("is-selected", state.selection.has(cue.id));
        segment.classList.toggle("is-muted", !state.selection.has(cue.id));
        const left = Math.max(0, Math.min(100, (cue.start / duration) * 100));
        const width = Math.max(0.35, Math.min(100 - left, ((cue.end - cue.start) / duration) * 100));
        segment.style.left = `${left}%`;
        segment.style.width = `${width}%`;
        segment.setAttribute("aria-label", `${state.selection.has(cue.id) ? "Selected" : "Available"} cue ${formatTime(cue.start)} to ${formatTime(cue.end)}: ${cue.text}`);
        segment.title = `${formatTime(cue.start)} — ${formatTime(cue.end)}`;
        segment.addEventListener("click", () => seekTo(cue.start, true));
        elements.timelineTrack.append(segment);
      }
    }
    updatePlayhead();
  }

  function updatePlayhead() {
    const duration = sourceDuration();
    const current = finiteNumber(elements.sourceVideo.currentTime);
    elements.timelinePlayhead.style.left = duration > 0 ? `${Math.max(0, Math.min(100, (current / duration) * 100))}%` : "0%";
  }

  function renderOverlay() {
    const current = finiteNumber(elements.sourceVideo.currentTime);
    const active = state.cues.filter((cue) => current >= cue.start && current <= cue.end);
    const text = active.map((cue) => cue.text).filter(Boolean).join("\n");
    elements.subtitleOverlay.textContent = text;
    elements.subtitleOverlay.hidden = text === "" || !state.project;
  }

  function renderDurations() {
    const source = sourceDuration();
    const retained = retainedDuration();
    elements.selectedDuration.textContent = formatTime(retained);
    elements.selectedCueCount.textContent = String(state.selection.size);
    elements.retainedDurationCard.textContent = formatTime(retained);
    elements.sourceDuration.textContent = formatTime(source);
    elements.sourceDurationCard.textContent = formatTime(source);
    elements.paddingValue.textContent = `±${state.padding.toFixed(2)}s`;
    elements.playbackNote.textContent = state.selectedOnly
      ? (state.selection.size > 0 ? "Skipping omitted intervals" : "Select cues to play")
      : "Full source playback";
  }

  function renderWorkspace() {
    renderProjectMeta();
    renderTranscript();
    renderTimeline();
    renderDurations();
    renderOverlay();
    updateActionButtons();
  }

  function selectionArray() {
    return state.cues.filter((cue) => state.selection.has(cue.id)).map((cue) => cue.id);
  }

  function selectionsEqual(left, right) {
    if (left.size !== right.size) return false;
    for (const item of left) if (!right.has(item)) return false;
    return true;
  }

  function changeSelection(id, shouldKeep, message = "Selection updated.") {
    const next = new Set(state.selection);
    if (shouldKeep) next.add(id);
    else next.delete(id);
    if (selectionsEqual(next, state.selection)) return;
    invalidateOutput();
    state.selectionHistory.push(new Set(state.selection));
    if (state.selectionHistory.length > 40) state.selectionHistory.shift();
    state.selection = next;
    renderWorkspace();
    setStatus(message);
  }

  function setSelection(next, message) {
    const nextSet = new Set(next);
    if (selectionsEqual(nextSet, state.selection)) return;
    invalidateOutput();
    state.selectionHistory.push(new Set(state.selection));
    if (state.selectionHistory.length > 40) state.selectionHistory.shift();
    state.selection = nextSet;
    renderWorkspace();
    setStatus(message);
  }

  function undoSelection() {
    const previous = state.selectionHistory.pop();
    if (!previous) return;
    invalidateOutput();
    state.selection = previous;
    renderWorkspace();
    setStatus("Previous selection restored.");
  }

  function clearOutput() {
    elements.outputPanel.hidden = true;
    elements.outputVideo.pause();
    elements.outputVideo.removeAttribute("src");
    elements.outputVideo.load();
    elements.outputMeta.textContent = "";
    elements.downloadLinks.replaceChildren();
  }

  function invalidateOutput() {
    if (!elements.outputPanel.hidden) clearOutput();
  }

  function setProject(raw) {
    state.project = normaliseProject(raw);
    document.body.classList.add("project-loaded");
    state.pendingSeek = null;
    state.cues = state.project.cues;
    state.selection = new Set(state.cues.map((cue) => cue.id));
    state.selectionHistory = [];
    state.transcriptFilter = "";
    elements.transcriptSearch.value = "";
    elements.jevConsent.checked = false;
    if (state.project.is_demo && state.project.suggested_goal) {
      elements.goalInput.value = state.project.suggested_goal;
    } else {
      elements.goalInput.value = "";
    }
    if (state.project.video_url) {
      elements.sourceVideo.hidden = false;
      elements.videoEmpty.hidden = true;
      elements.sourceVideo.src = state.project.video_url;
      elements.sourceVideo.load();
    } else {
      elements.sourceVideo.hidden = true;
      elements.videoEmpty.hidden = false;
    }
    clearOutput();
    renderWorkspace();
  }

  async function loadConfig() {
    try {
      const config = await request("/api/config");
      state.config = {
        ...state.config,
        ...(config || {}),
        jev_scope: config && config.jev_scope === "all" ? "all" : "demo",
      };
      updateConfigStatus();
      updateActionButtons();
    } catch (error) {
      elements.configStatus.textContent = "Media tools unavailable";
      setStatus(`Could not read workspace config: ${error.message}`, "error");
      updateActionButtons();
    }
  }

  async function loadDemo() {
    const operation = beginOperation("demo");
    if (!operation) return;
    setButtonBusy(elements.demoButton, true);
    setStatus("Loading the sample video and transcript…", "busy");
    try {
      const project = await request("/api/demo", { method: "POST", json: {} });
      if (!operationStillCurrent(operation)) return;
      setProject(project);
      setStatus("Sample loaded. Select cues or try the suggested goal.");
    } catch (error) {
      if (!operationStillCurrent(operation)) return;
      setStatus(`Sample could not load: ${error.message}`, "error");
    } finally {
      releaseOperationButton(operation, elements.demoButton);
    }
  }

  function safeUploadFilename(name) {
    const match = String(name || "").match(/\.(mp4|mov|webm|mkv)$/i);
    return `cutroom-source.${match ? match[1].toLowerCase() : "mp4"}`;
  }

  async function importVideo(file) {
    if (!file) return;
    const maxBytes = finiteNumber(state.config.max_upload_mb, 512) * 1024 * 1024;
    if (file.size > maxBytes) {
      setStatus(`This file is larger than ${state.config.max_upload_mb} MB.`, "error");
      return;
    }
    const operation = beginOperation("video-import");
    if (!operation) {
      elements.videoFile.value = "";
      return;
    }
    state.uploading = true;
    setButtonBusy(elements.demoButton, true);
    setStatus("Uploading the source video…", "busy");
    try {
      const project = await request("/api/upload", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Filename": safeUploadFilename(file.name),
        },
        body: file,
      });
      if (!operationStillCurrent(operation)) return;
      setProject(project);
      setStatus("Video imported. Add an SRT or VTT file to start selecting cues.");
    } catch (error) {
      if (!operationStillCurrent(operation)) return;
      setStatus(`Video import failed: ${error.message}`, "error");
    } finally {
      state.uploading = false;
      elements.videoFile.value = "";
      releaseOperationButton(operation, elements.demoButton);
    }
  }

  async function importSubtitles(file) {
    if (!file) return;
    if (!projectLoaded()) {
      setStatus("Import a video before adding subtitles.", "error");
      elements.subtitleFile.value = "";
      return;
    }
    const projectId = state.project.id;
    const operation = beginOperation("subtitle-import", projectId);
    if (!operation) {
      elements.subtitleFile.value = "";
      return;
    }
    setButtonBusy(elements.demoButton, true);
    setStatus("Reading the subtitle file…", "busy");
    try {
      const text = await file.text();
      if (text.trim() === "") throw new Error("The subtitle file is empty.");
      const project = await request(`/api/project/${encodeURIComponent(projectId)}/subtitles`, {
        method: "POST",
        json: { text },
      });
      if (!operationStillCurrent(operation)) return;
      setProject(project);
      setStatus(`${state.cues.length} subtitle cues loaded. Edit the selection below.`);
    } catch (error) {
      if (!operationStillCurrent(operation)) return;
      setStatus(`Subtitle import failed: ${error.message}`, "error");
    } finally {
      elements.subtitleFile.value = "";
      releaseOperationButton(operation, elements.demoButton);
    }
  }

  function seekTo(seconds, play = false) {
    if (!projectLoaded()) return;
    const projectId = state.project.id;
    if (elements.sourceVideo.readyState < 1) {
      state.pendingSeek = { projectId, seconds, play };
      if (play) {
        elements.sourceVideo.play().catch(() => {
          setStatus("Playback needs a click in the video controls.");
        });
      }
      setStatus("Preparing the source preview…", "busy");
      return;
    }
    const duration = sourceDuration();
    elements.sourceVideo.currentTime = Math.max(0, Math.min(duration || seconds, seconds));
    if (play) {
      elements.sourceVideo.play().catch(() => {
        setStatus("Playback needs a click in the video controls.");
      });
    }
    renderDurations();
    updatePlayhead();
    renderOverlay();
  }

  function enforceSelectedPlayback() {
    if (!state.selectedOnly || state.playbackJumping || elements.sourceVideo.paused || state.selection.size === 0) return;
    const intervals = selectedIntervals();
    if (intervals.length === 0) {
      elements.sourceVideo.pause();
      return;
    }
    const current = finiteNumber(elements.sourceVideo.currentTime);
    const epsilon = 0.04;
    const insideIndex = intervals.findIndex((interval) => current >= interval.start - epsilon && current < interval.end - epsilon);
    if (insideIndex >= 0) return;
    const next = intervals.find((interval) => current < interval.start);
    if (next) {
      state.playbackJumping = true;
      elements.sourceVideo.currentTime = next.start;
      window.setTimeout(() => {
        state.playbackJumping = false;
      }, 80);
      return;
    }
    if (current >= intervals[intervals.length - 1].end - epsilon) {
      elements.sourceVideo.pause();
      elements.sourceVideo.currentTime = intervals[intervals.length - 1].end;
    } else {
      state.playbackJumping = true;
      elements.sourceVideo.currentTime = intervals[0].start;
      window.setTimeout(() => {
        state.playbackJumping = false;
      }, 80);
    }
  }

  async function requestSuggestion(mode) {
    if (state.operation.kind || !projectLoaded() || state.cues.length === 0) return;
    const projectId = state.project.id;
    const goal = elements.goalInput.value.trim();
    if (goal === "") {
      setSuggestionStatus("Add a goal first.", "error");
      return;
    }
    const recorded = mode === "jev" && isRecordedDemoGoal();
    const live = mode === "jev" && !recorded;
    if (live && (state.config.jev_scope !== "all" || !elements.jevConsent.checked)) {
      setSuggestionStatus("Consent is required for this Jev suggestion.", "error");
      updateJevControls();
      return;
    }
    const operation = beginOperation("suggest", projectId);
    if (!operation) return;

    setSuggestionStatus(mode === "keywords" ? "Selecting…" : "Preparing suggestion…");
    setStatus(mode === "keywords" ? "Selecting transcript cues…" : "Preparing the suggestion…", "busy");
    if (mode === "keywords") setButtonBusy(elements.keywordsButton, true);
    else setButtonBusy(elements.jevButton, true);
    try {
      const body = { goal, mode };
      if (live) body.consent = true;
      const result = await request(`/api/project/${encodeURIComponent(projectId)}/suggest`, {
        method: "POST",
        json: body,
      });
      if (!operationStillCurrent(operation)) return;
      const selected = Array.isArray(result && result.selected_ids) ? result.selected_ids.map(String) : [];
      setSelection(selected.filter((id) => state.cues.some((cue) => cue.id === id)), mode === "keywords" ? "Keyword selection applied." : "Suggestion applied. You can edit every cue.");
      const responseMode = String((result && result.mode) || mode);
      const note = String((result && result.note) || "");
      const recordedResult = responseMode === "recorded" || /recorded/i.test(note);
      elements.suggestionMode.textContent = recordedResult
        ? "Recorded demo guidance"
        : responseMode === "keywords" ? "Keyword match" : "Jev selection";
      const measurement = result && result.measurement && typeof result.measurement === "object" ? result.measurement : null;
      let detail = note || `${selected.length} cue${selected.length === 1 ? "" : "s"} suggested.`;
      if (measurement && Number.isFinite(Number(measurement.call_ms))) {
        detail += ` · ${Number(measurement.call_ms).toFixed(0)} ms`;
      }
      elements.suggestionDetail.textContent = detail;
      setSuggestionStatus(`${selected.length} cue${selected.length === 1 ? "" : "s"} selected.`);
      setStatus(mode === "keywords" ? "Keyword selection applied." : "Suggestion applied. You can edit every cue.");
    } catch (error) {
      if (!operationStillCurrent(operation)) return;
      setSuggestionStatus(error.message, "error");
      setStatus(`Suggestion failed: ${error.message}`, "error");
    } finally {
      releaseOperationButton(operation, mode === "keywords" ? elements.keywordsButton : elements.jevButton);
    }
  }

  function createDownloadLink(label, url, key) {
    const safeUrl = sameOriginUrl(url);
    if (!safeUrl) return null;
    const link = document.createElement("a");
    link.className = "download-link";
    link.href = safeUrl;
    link.download = "";
    link.textContent = label;
    link.setAttribute("aria-label", `Download ${label}`);
    link.dataset.fileKey = key;
    const arrow = document.createElement("span");
    arrow.className = "download-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "↓";
    link.append(arrow);
    return link;
  }

  function showExport(result) {
    const urls = result && result.urls && typeof result.urls === "object" ? result.urls : {};
    const videoUrl = sameOriginUrl(urls.video);
    if (!videoUrl) throw new Error("Export completed without a video download URL.");
    elements.outputVideo.src = videoUrl;
    elements.outputVideo.load();
    const requestedDuration = finiteNumber(result.requested_duration, result.duration);
    elements.outputMeta.textContent = `${formatTime(result.duration)} output · ${formatTime(requestedDuration)} requested · ${result.has_audio ? "audio included" : "silent source"}`;
    elements.downloadLinks.replaceChildren();
    const files = [
      ["Download MP4", urls.video, "video"],
      ["Download SRT", urls.srt, "srt"],
      ["Download VTT", urls.vtt, "vtt"],
      ["Download timeline JSON", urls.timeline, "timeline"],
      ["Download Cutroom bundle", urls.bundle, "bundle"],
    ];
    for (const [label, url, key] of files) {
      const link = createDownloadLink(label, url, key);
      if (link) elements.downloadLinks.append(link);
    }
    elements.outputPanel.hidden = false;
  }

  async function exportCut() {
    if (state.operation.kind || !projectLoaded() || state.selection.size === 0 || state.exporting) return;
    const projectId = state.project.id;
    const selectedIds = selectionArray();
    const padding = state.padding;
    const operation = beginOperation("export", projectId);
    if (!operation) return;
    state.exporting = true;
    elements.exportButton.setAttribute("aria-busy", "true");
    elements.exportButton.disabled = true;
    setExportStatus("Rendering your selected moments…", "busy");
    setStatus("Rendering the cut. This can take a moment…", "busy");
    let finalExportStatus = "";
    try {
      const result = await request(`/api/project/${encodeURIComponent(projectId)}/export`, {
        method: "POST",
        json: { selected_ids: selectedIds, padding },
      });
      if (!operationStillCurrent(operation)) return;
      showExport(result);
      finalExportStatus = "Export complete. Preview or download the files below.";
      setStatus("Your cut is ready.");
    } catch (error) {
      if (!operationStillCurrent(operation)) return;
      finalExportStatus = `Export failed: ${error.message}`;
      setExportStatus(finalExportStatus, "error");
      setStatus(`Export failed: ${error.message}`, "error");
    } finally {
      state.exporting = false;
      elements.exportButton.removeAttribute("aria-busy");
      finishOperation(operation);
      if (finalExportStatus) setExportStatus(finalExportStatus, finalExportStatus.startsWith("Export failed:") ? "error" : "");
    }
  }

  function bindEvents() {
    elements.demoButton.addEventListener("click", loadDemo);
    elements.videoFile.addEventListener("change", (event) => importVideo(event.target.files && event.target.files[0]));
    elements.subtitleFile.addEventListener("change", (event) => importSubtitles(event.target.files && event.target.files[0]));
    elements.transcriptSearch.addEventListener("input", (event) => {
      state.transcriptFilter = event.target.value;
      renderTranscript();
    });
    elements.selectionUndo.addEventListener("click", undoSelection);
    elements.selectionReset.addEventListener("click", () => setSelection([], "Selection cleared. Choose a cue to build a new cut."));
    elements.selectionAll.addEventListener("click", () => setSelection(state.cues.map((cue) => cue.id), "All cues selected."));
    elements.selectionNone.addEventListener("click", () => setSelection([], "All cues cleared."));
    elements.paddingRange.addEventListener("input", (event) => {
      state.padding = Math.min(1, Math.max(0, finiteNumber(event.target.value, 0.12)));
      const hadOutput = !elements.outputPanel.hidden;
      invalidateOutput();
      renderDurations();
      renderTimeline();
      setExportStatus(hadOutput ? "Padding changed. Export again to refresh the preview." : "Ready to export the selected moments.");
    });
    elements.goalInput.addEventListener("input", () => {
      updateJevControls();
      updateKeywordControls();
    });
    elements.keywordsButton.addEventListener("click", () => requestSuggestion("keywords"));
    elements.jevButton.addEventListener("click", () => requestSuggestion("jev"));
    elements.jevConsent.addEventListener("change", updateJevControls);
    elements.selectedOnly.addEventListener("change", (event) => {
      state.selectedOnly = event.target.checked;
      renderDurations();
      if (state.selectedOnly) {
        if (state.selection.size === 0) {
          elements.sourceVideo.pause();
          setStatus("Select at least one cue before selected-only playback.");
        } else {
          enforceSelectedPlayback();
        }
      }
    });
    elements.exportButton.addEventListener("click", exportCut);
    elements.sourceVideo.addEventListener("loadedmetadata", () => {
      const pending = state.pendingSeek;
      if (pending && state.project && pending.projectId === state.project.id) {
        state.pendingSeek = null;
        seekTo(pending.seconds, pending.play);
      } else if (pending) {
        state.pendingSeek = null;
      }
      renderProjectMeta();
      renderTimeline();
      renderDurations();
    });
    elements.sourceVideo.addEventListener("durationchange", () => {
      renderProjectMeta();
      renderTimeline();
      renderDurations();
    });
    elements.sourceVideo.addEventListener("timeupdate", () => {
      elements.playbackTime.textContent = formatTime(elements.sourceVideo.currentTime);
      renderOverlay();
      updatePlayhead();
      enforceSelectedPlayback();
    });
    elements.sourceVideo.addEventListener("play", () => {
      if (state.selectedOnly && state.selection.size === 0) {
        elements.sourceVideo.pause();
        setStatus("Select at least one cue before selected-only playback.");
      } else {
        enforceSelectedPlayback();
      }
    });
    elements.sourceVideo.addEventListener("error", () => {
      if (state.project) setStatus("The source video could not be previewed.", "error");
    });
  }

  async function init() {
    bindEvents();
    elements.sourceVideo.hidden = true;
    elements.outputPanel.hidden = true;
    renderWorkspace();
    await loadConfig();
  }

  init();
})();

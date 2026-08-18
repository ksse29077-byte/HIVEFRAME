"use strict";

const LOCAL_BACKEND = "minimax_h3_comfyui_local";
const MAX_REFERENCE_BYTES = 10 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const STATUS_LABELS = {
  queued: "준비 중", running: "영상 생성 중", succeeded: "완료",
  failed: "생성 실패", cancelled: "취소됨",
};
const ERROR_MESSAGES = {
  runtime_unavailable: "Local AI 실행 환경을 확인해주세요.",
  comfyui_unavailable: "Local AI 실행 환경을 확인해주세요.",
  comfyui_start_failed: "Local AI 실행 환경을 확인해주세요.",
  comfyui_start_timeout: "Local AI 실행 환경을 확인해주세요.",
  artifact_pending: "필요한 모델 파일을 확인해주세요.",
  model_source_not_configured: "필요한 모델 파일을 확인해주세요.",
  model_files_missing: "필요한 모델 파일을 확인해주세요.",
  comfyui_dependency_required: "필요한 모델 파일을 확인해주세요.",
  out_of_memory: "GPU 메모리가 부족합니다.",
  artifact_save_failed: "결과 파일을 저장하지 못했습니다.",
  timeout: "생성 시간이 제한을 초과했습니다.",
  runtime_busy: "현재 다른 영상 생성 작업이 실행 중입니다. 작업이 완료된 후 다시 시도해주세요.",
};

const state = { config: null, job: null, mode: "text_to_video", file: null, pollTimer: null, elapsedTimer: null, startedAt: null };
const byId = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || "요청을 처리하지 못했습니다.");
  return payload;
}

function formatElapsed(seconds) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  return `${minutes}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
}

function updateElapsed() {
  if (!state.startedAt || !state.job || !["queued", "running"].includes(state.job.status)) return;
  byId("elapsedTime").textContent = `${STATUS_LABELS[state.job.status]} · ${formatElapsed((Date.now() - state.startedAt) / 1000)} 경과`;
}

function readinessItem(id, item) {
  const element = byId(id);
  element.textContent = item?.label || "확인 필요";
  element.dataset.state = item?.state || "needs_attention";
}

function renderReadiness(config) {
  state.config = config;
  readinessItem("readyGpu", config.readiness?.gpu);
  readinessItem("readyLocalAi", config.readiness?.local_ai);
  readinessItem("readyModel", config.readiness?.model);
  readinessItem("readyGeneration", config.readiness?.generation);
  readinessItem("readyStorage", config.readiness?.storage);
  const local = config.backends[LOCAL_BACKEND];
  byId("overallBadge").textContent = config.can_generate ? "사용 준비 완료" : "확인이 필요합니다";
  byId("overallBadge").dataset.state = config.can_generate ? "ready" : "attention";
  byId("readinessMessage").textContent = local?.message || "Local AI 실행 환경을 확인해주세요.";
  byId("generateButton").disabled = !config.can_generate;
  if (config.dev_mode) {
    byId("devControls").classList.remove("hidden");
    byId("devDetails").classList.remove("hidden");
    const select = byId("backend");
    Object.values(config.backends).forEach((backend) => {
      if (![...select.options].some((option) => option.value === backend.name)) {
        select.add(new Option(backend.display_name, backend.name));
      }
    });
  }
}

async function refreshReadiness() {
  try { renderReadiness(await request("/api/config")); }
  catch { byId("readinessMessage").textContent = "HIVEFRAME 상태를 불러오지 못했습니다."; }
}

function clearImage() {
  state.file = null;
  byId("reference").value = "";
  byId("imagePreview").removeAttribute("src");
  byId("imagePreviewWrap").classList.add("hidden");
  byId("uploadLabel").textContent = "PNG, JPEG 또는 WebP 이미지 선택";
  byId("imageMessage").textContent = "";
}

function setMode(mode) {
  state.mode = mode;
  clearImage();
  byId("imageInputSection").classList.toggle("hidden", mode !== "image_to_video");
}

function selectImage(file) {
  clearImage();
  if (!file) return;
  if (!IMAGE_TYPES.has(file.type)) {
    byId("imageMessage").textContent = "PNG, JPEG 또는 WebP 이미지만 사용할 수 있습니다.";
    return;
  }
  if (file.size > MAX_REFERENCE_BYTES) {
    byId("imageMessage").textContent = "이미지는 10MB 이하여야 합니다.";
    return;
  }
  state.file = file;
  byId("uploadLabel").textContent = file.name;
  byId("imagePreview").src = URL.createObjectURL(file);
  byId("imagePreviewWrap").classList.remove("hidden");
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("이미지를 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
}

function renderJob(job) {
  state.job = job;
  byId("statusTitle").textContent = STATUS_LABELS[job.status] || "상태 확인 중";
  byId("cancelButton").classList.toggle("hidden", !["queued", "running"].includes(job.status));
  const failed = job.status === "failed";
  byId("errorPanel").classList.toggle("hidden", !failed);
  byId("errorMessage").textContent = failed ? ERROR_MESSAGES[job.error_code] || "생성 중 문제가 발생했습니다. 실행 환경을 확인해주세요." : "";
  byId("retryButton").disabled = !(failed && job.retry_count < job.max_retry);
  const succeededVideo = job.status === "succeeded" && job.result_url && String(job.result_media_type).startsWith("video/");
  byId("resultPlaceholder").classList.toggle("hidden", succeededVideo);
  byId("resultVideo").classList.toggle("hidden", !succeededVideo);
  byId("downloadLink").classList.toggle("hidden", !succeededVideo);
  byId("feedbackPanel").classList.toggle("hidden", !succeededVideo);
  if (succeededVideo) {
    byId("resultVideo").src = job.result_url;
    byId("downloadLink").href = job.result_url;
    byId("downloadLink").download = job.result_filename || "hiveframe-video.mp4";
  }
  if (!["queued", "running"].includes(job.status)) {
    window.clearInterval(state.elapsedTimer);
    byId("elapsedTime").textContent = state.startedAt ? `${formatElapsed((Date.now() - state.startedAt) / 1000)} 경과` : "";
  }
  if (state.config?.dev_mode) byId("devData").textContent = JSON.stringify(job, null, 2);
}

async function pollJob() {
  if (!state.job) return;
  try {
    const job = await request(`/api/jobs/${state.job.job_id}`);
    renderJob(job);
    if (["queued", "running"].includes(job.status)) state.pollTimer = window.setTimeout(pollJob, 1000);
    else await refreshReadiness();
  } catch { byId("formMessage").textContent = "생성 상태를 확인하지 못했습니다."; }
}

async function submitGeneration(event) {
  event.preventDefault();
  byId("formMessage").textContent = "";
  if (!state.config?.can_generate) return;
  if (state.mode === "image_to_video" && !state.file) {
    byId("imageMessage").textContent = "첫 프레임 이미지를 선택해주세요.";
    return;
  }
  byId("generateButton").disabled = true;
  try {
    const reference = state.mode === "image_to_video" ? {
      name: state.file.name, media_type: state.file.type, content_base64: await fileAsBase64(state.file),
    } : null;
    const backend = state.config.dev_mode ? byId("backend").value : LOCAL_BACKEND;
    const job = await request("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ backend, mode: state.mode, prompt: byId("prompt").value, profile: "standard", generation_consent: byId("generationConsent").checked, reference }),
    });
    state.startedAt = Date.now();
    window.clearTimeout(state.pollTimer);
    window.clearInterval(state.elapsedTimer);
    state.elapsedTimer = window.setInterval(updateElapsed, 1000);
    renderJob(job);
    updateElapsed();
    await pollJob();
  } catch (error) {
    byId("formMessage").textContent = error.message;
    await refreshReadiness();
  }
}

async function saveFeedback(decision, reason = null) {
  if (!state.job) return;
  try {
    await request(`/api/jobs/${state.job.job_id}/feedback`, {
      method: "POST", body: JSON.stringify({ decision, feedback_reason: reason, training_opt_in: false, deletion_requested: false }),
    });
    byId("feedbackMessage").textContent = "의견을 보내주셔서 감사합니다.";
    byId("rejectionPanel").classList.add("hidden");
  } catch (error) { byId("feedbackMessage").textContent = error.message; }
}

document.querySelectorAll('input[name="generationMode"]').forEach((input) => input.addEventListener("change", () => setMode(input.value)));
byId("prompt").addEventListener("input", () => { byId("promptCount").textContent = `${byId("prompt").value.length} / 2000`; });
byId("reference").addEventListener("change", () => selectImage(byId("reference").files[0]));
byId("removeImage").addEventListener("click", clearImage);
byId("generationForm").addEventListener("submit", submitGeneration);
byId("refreshReadiness").addEventListener("click", refreshReadiness);
byId("acceptButton").addEventListener("click", () => saveFeedback("accepted"));
byId("rejectButton").addEventListener("click", () => byId("rejectionPanel").classList.remove("hidden"));
byId("submitRejection").addEventListener("click", () => {
  const reason = byId("feedbackReason").value;
  if (!reason) { byId("feedbackMessage").textContent = "아쉬운 점을 하나 선택해주세요."; return; }
  saveFeedback("rejected", reason);
});
byId("retryButton").addEventListener("click", async () => {
  if (!state.job) return;
  const job = await request(`/api/jobs/${state.job.job_id}/retry`, { method: "POST", body: "{}" });
  state.startedAt = Date.now(); renderJob(job); await pollJob();
});
byId("cancelButton").addEventListener("click", async () => {
  if (!state.job) return;
  renderJob(await request(`/api/jobs/${state.job.job_id}/cancel`, { method: "POST", body: "{}" }));
});

refreshReadiness();

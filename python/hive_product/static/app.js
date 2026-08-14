"use strict";

const state = { job: null, pollTimer: null, config: null };
const byId = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || payload.error || "요청에 실패했습니다.");
  return payload;
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("첫 프레임 이미지를 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
}

function renderBackend() {
  if (!state.config) return;
  const selected = byId("backend").value;
  const backend = state.config.backends[selected];
  const localWaiting = selected === "minimax_h3_comfyui_local" && !backend.can_generate;
  const profile = byId("executionProfile");
  if (selected !== "minimax_h3_comfyui_local") profile.value = "standard";
  profile.disabled = selected !== "minimax_h3_comfyui_local";
  byId("profileMessage").textContent = profile.value === "fast_2m_candidate"
    ? "608x352, 124 frames, 7 steps, SageAttention auto. Standard mode remains available."
    : "864x480, 124 frames, 20 steps.";
  byId("backendBadge").textContent = backend.message || `${backend.display_name} · ${backend.state}`;
  byId("backendMessage").textContent = localWaiting
    ? `Local H3 — ComfyUI를 사용할 수 없습니다 (${backend.reason || "runtime_unavailable"}). Mock H3는 직접 선택할 수 있습니다.`
    : `${backend.display_name} 준비됨. 자동 fallback은 사용하지 않습니다.`;
  byId("generateButton").disabled = localWaiting;
  byId("generateButton").textContent = localWaiting ? "공식 모델 파일 대기 중" : `${backend.display_name} 요청 만들기`;
}

function renderJob(job) {
  state.job = job;
  byId("jobStatus").textContent = job.status;
  byId("jobId").textContent = job.job_id;
  byId("jobModel").textContent = job.model;
  byId("retryCount").textContent = `${job.retry_count} / ${job.max_retry}`;
  const failed = job.status === "failed";
  byId("errorCard").classList.toggle("hidden", !failed);
  byId("errorCode").textContent = failed ? job.error_code || "failed" : "";
  byId("errorMessage").textContent = failed ? job.error_message || "안전하게 실패했습니다." : "";
  const succeeded = job.status === "succeeded";
  byId("downloadLink").classList.toggle("hidden", !succeeded);
  const isRealVideo = succeeded && job.backend === "minimax_h3_comfyui_local";
  byId("resultVideo").classList.toggle("hidden", !isRealVideo);
  byId("resultPlaceholder").classList.toggle("hidden", isRealVideo);
  if (succeeded) {
    byId("downloadLink").href = job.result_url;
    if (isRealVideo) byId("resultVideo").src = job.result_url;
  }
  byId("acceptButton").disabled = !succeeded;
  byId("rejectButton").disabled = !succeeded;
  byId("retryButton").disabled = !(failed && job.retry_count < job.max_retry);
  byId("cancelButton").disabled = !["queued", "running"].includes(job.status);
}

async function pollJob() {
  if (!state.job) return;
  const job = await request(`/api/jobs/${state.job.job_id}`);
  renderJob(job);
  if (["queued", "running"].includes(job.status)) state.pollTimer = window.setTimeout(pollJob, 250);
  else renderBackend();
}

byId("backend").addEventListener("change", renderBackend);
byId("executionProfile").addEventListener("change", renderBackend);
byId("generationForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  byId("formMessage").textContent = "요청을 만드는 중입니다.";
  byId("generateButton").disabled = true;
  try {
    const file = byId("reference").files[0];
    const reference = file ? { name: file.name, media_type: file.type || "application/octet-stream", content_base64: await fileAsBase64(file) } : null;
    const job = await request("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        backend: byId("backend").value,
        prompt: byId("prompt").value,
        resolution: "768P",
        duration_seconds: 4,
        ratio: "16:9",
        profile: byId("executionProfile").value,
        generation_consent: byId("generationConsent").checked,
        reference,
      }),
    });
    renderJob(job);
    byId("formMessage").textContent = "Job을 생성했습니다.";
    window.clearTimeout(state.pollTimer);
    await pollJob();
  } catch (error) {
    byId("formMessage").textContent = error.message;
    renderBackend();
  }
});

async function saveFeedback(decision) {
  if (!state.job) return;
  byId("feedbackMessage").textContent = "피드백을 저장하는 중입니다.";
  try {
    const feedback = await request(`/api/jobs/${state.job.job_id}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        feedback_reason: byId("feedbackReason").value || null,
        training_opt_in: byId("trainingOptIn").checked,
        deletion_requested: byId("deletionRequested").checked,
      }),
    });
    byId("feedbackMessage").textContent = `저장 완료 · ${feedback.training_eligibility}`;
    if (decision === "retry_requested") {
      const job = await request(`/api/jobs/${state.job.job_id}/retry`, { method: "POST", body: "{}" });
      renderJob(job);
      await pollJob();
    }
  } catch (error) { byId("feedbackMessage").textContent = error.message; }
}

byId("acceptButton").addEventListener("click", () => saveFeedback("accepted"));
byId("rejectButton").addEventListener("click", () => saveFeedback("rejected"));
byId("retryButton").addEventListener("click", () => saveFeedback("retry_requested"));
byId("cancelButton").addEventListener("click", async () => {
  if (!state.job) return;
  try {
    const job = await request(`/api/jobs/${state.job.job_id}/cancel`, { method: "POST", body: "{}" });
    renderJob(job);
  } catch (error) { byId("feedbackMessage").textContent = error.message; }
});

request("/api/config").then((config) => { state.config = config; renderBackend(); })
  .catch(() => { byId("backendBadge").textContent = "Configuration unavailable"; });

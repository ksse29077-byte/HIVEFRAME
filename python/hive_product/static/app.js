"use strict";

const state = { job: null, pollTimer: null };
const byId = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || payload.error || "요청이 실패했습니다.");
  return payload;
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("참조 이미지를 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
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
  if (succeeded) byId("downloadLink").href = job.result_url;
  byId("acceptButton").disabled = !succeeded;
  byId("rejectButton").disabled = !succeeded;
  byId("retryButton").disabled = !(failed && job.retry_count < job.max_retry);
}

async function pollJob() {
  if (!state.job) return;
  const job = await request(`/api/jobs/${state.job.job_id}`);
  renderJob(job);
  if (job.status === "queued" || job.status === "running") {
    state.pollTimer = window.setTimeout(pollJob, 250);
  } else {
    byId("generateButton").disabled = false;
  }
}

byId("generationForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  byId("formMessage").textContent = "요청을 만드는 중…";
  byId("generateButton").disabled = true;
  try {
    const file = byId("reference").files[0];
    const reference = file ? {
      name: file.name,
      media_type: file.type || "application/octet-stream",
      content_base64: await fileAsBase64(file),
    } : null;
    const job = await request("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        prompt: byId("prompt").value,
        duration_seconds: Number(byId("duration").value),
        profile: "standard",
        generation_consent: byId("generationConsent").checked,
        backend_transfer_consent: byId("transferConsent").checked,
        reference,
      }),
    });
    renderJob(job);
    byId("formMessage").textContent = "Job이 생성되었습니다.";
    window.clearTimeout(state.pollTimer);
    await pollJob();
  } catch (error) {
    byId("formMessage").textContent = error.message;
    byId("generateButton").disabled = false;
  }
});

async function saveFeedback(decision) {
  if (!state.job) return;
  const reason = byId("feedbackReason").value || null;
  byId("feedbackMessage").textContent = "피드백을 저장하는 중…";
  try {
    const feedback = await request(`/api/jobs/${state.job.job_id}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        feedback_reason: reason,
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
  } catch (error) {
    byId("feedbackMessage").textContent = error.message;
  }
}

byId("acceptButton").addEventListener("click", () => saveFeedback("accepted"));
byId("rejectButton").addEventListener("click", () => saveFeedback("rejected"));
byId("retryButton").addEventListener("click", () => saveFeedback("retry_requested"));

request("/api/config").then((config) => {
  byId("backendBadge").textContent = `${config.backend} · Live calls ${config.live_call_count}`;
}).catch(() => {
  byId("backendBadge").textContent = "Configuration unavailable";
});

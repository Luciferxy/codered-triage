// CodeRed Triage Trauma Console Application Logic

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const ecgCanvas = document.getElementById("ecgCanvas");
  const ctx = ecgCanvas.getContext("2d");
  
  const valHr = document.getElementById("val-hr");
  const valSpo2 = document.getElementById("val-spo2");
  const valBp = document.getElementById("val-bp");
  const rhythmBadge = document.getElementById("rhythm-state-badge");
  const conditionText = document.getElementById("patient-condition-text");
  
  const agentStatePill = document.getElementById("agent-state-pill");
  const metricCutoffLatency = document.getElementById("metric-cutoff-latency");
  const metricRimeTtfa = document.getElementById("metric-rime-ttfa");
  const metricFencedCount = document.getElementById("metric-fenced-count");
  const auditoryStream = document.getElementById("auditory-stream-display");
  const logTableBody = document.getElementById("fence-log-tbody");
  
  const btnDopamine = document.getElementById("btn-action-dopamine");
  const btnInterrupt = document.getElementById("btn-action-interrupt");
  const btnEpi = document.getElementById("btn-action-epi");
  const btnVfib = document.getElementById("btn-action-vfib");
  const speechForm = document.getElementById("speech-form");
  const userInput = document.getElementById("user-input-field");
  const btnClearLogs = document.getElementById("btn-clear-logs");

  let currentHeartRate = 132;
  let isCardiacArrest = false;
  let isSpeaking = false;
  let speechStartTime = 0;
  let simulatedAudioTimer = null;
  let totalFencedCount = 0;

  // --- 1. Real-Time ECG Canvas Waveform Renderer ---
  let ecgX = 0;
  const canvasWidth = ecgCanvas.width;
  const canvasHeight = ecgCanvas.height;
  const centerY = canvasHeight / 2;

  // Pre-clear canvas
  ctx.fillStyle = "#02060a";
  ctx.fillRect(0, 0, canvasWidth, canvasHeight);

  function drawEcgGrid() {
    ctx.strokeStyle = "rgba(0, 255, 136, 0.05)";
    ctx.lineWidth = 1;
    for (let x = 0; x < canvasWidth; x += 20) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvasHeight);
      ctx.stroke();
    }
    for (let y = 0; y < canvasHeight; y += 20) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvasWidth, y);
      ctx.stroke();
    }
  }

  drawEcgGrid();

  function renderEcgFrame() {
    // Lead erase bar ahead of the beam
    ctx.fillStyle = "rgba(2, 6, 10, 0.25)";
    ctx.fillRect(ecgX, 0, 14, canvasHeight);

    let y = centerY;
    const beatInterval = Math.max(15, Math.floor(600 / (currentHeartRate || 1)));

    if (isCardiacArrest) {
      // Flatline with small telemetry baseline noise
      y = centerY + (Math.random() - 0.5) * 3;
    } else {
      // Generate QRS complex when beat triggers
      const phase = ecgX % beatInterval;
      if (phase === 4) y = centerY - 6;          // P-wave
      else if (phase === 8) y = centerY + 8;     // Q-wave
      else if (phase === 10) y = centerY - 55;   // R-wave peak
      else if (phase === 12) y = centerY + 24;   // S-wave
      else if (phase === 18) y = centerY - 14;   // T-wave
      else y = centerY + (Math.random() - 0.5) * 2; // Baseline noise
    }

    ctx.strokeStyle = isCardiacArrest ? "#ff334b" : "#00ff88";
    ctx.shadowBlur = 6;
    ctx.shadowColor = isCardiacArrest ? "rgba(255, 51, 75, 0.8)" : "rgba(0, 255, 136, 0.8)";
    ctx.lineWidth = 2;

    ctx.beginPath();
    ctx.moveTo(ecgX - 2, y);
    ctx.lineTo(ecgX, y);
    ctx.stroke();

    ctx.shadowBlur = 0;
    ecgX = (ecgX + 2) % canvasWidth;
    requestAnimationFrame(renderEcgFrame);
  }

  requestAnimationFrame(renderEcgFrame);

  // --- 2. Pathway Real-Time Vitals EventSource Stream ---
  const eventSource = new EventSource("/api/vitals/stream");
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      currentHeartRate = data.heart_rate_bpm;
      isCardiacArrest = data.is_cardiac_arrest;

      valHr.textContent = data.heart_rate_bpm;
      valSpo2.textContent = data.spo2_pct;
      valBp.textContent = `${data.systolic_bp}/${data.diastolic_bp}`;
      rhythmBadge.textContent = data.rhythm_state.replace(/_/g, " ");

      if (data.is_cardiac_arrest) {
        rhythmBadge.className = "badge badge-emergency";
        conditionText.textContent = "CRITICAL: CARDIAC ARREST DETECTED (NO PULSE)";
        conditionText.className = "patient-cond text-alert";
      } else {
        rhythmBadge.className = "badge badge-pathway";
        conditionText.textContent = "Status: Decompensating Shock";
        conditionText.className = "patient-cond alert-text";
      }
    } catch (e) {
      console.error("Failed to parse vitals event", e);
    }
  };

  // --- 3. Speech Turn Execution & Hard Voice Engineering ---
  async function sendSpeechTurn(text, isInterruption = false) {
    let playbackDuration = 0;
    if (isSpeaking && speechStartTime > 0) {
      playbackDuration = (performance.now() - speechStartTime) / 1000.0;
    }

    // Update UI state
    if (isInterruption) {
      agentStatePill.textContent = "INTERRUPTED & FENCING...";
      agentStatePill.className = "state-pill state-interrupted";
      if (simulatedAudioTimer) clearInterval(simulatedAudioTimer);
    } else {
      agentStatePill.textContent = "EXECUTING TURN...";
      agentStatePill.className = "state-pill";
    }

    try {
      const resp = await fetch("/api/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          was_speaking: isSpeaking || isInterruption,
          playback_duration_sec: playbackDuration
        })
      });

      const data = await resp.json();

      // Handle Interruption Metrics
      if (data.interruption_event) {
        metricCutoffLatency.textContent = `${data.interruption_event.cutoff_latency_ms} ms`;
        recordTurnInStream("EMT (BARGE-IN INTERRUPT)", text, "interrupted");
      } else {
        recordTurnInStream("EMT", text, "user");
      }

      // Handle Fenced Events
      if (data.fenced_events && data.fenced_events.length > 0) {
        totalFencedCount += data.fenced_events.length;
        metricFencedCount.textContent = totalFencedCount;
        data.fenced_events.forEach(addFenceLogRow);
      }

      // Handle Spoken Output via Rime
      if (data.spoken_response) {
        metricRimeTtfa.textContent = `${data.ttfa_ms || 40} ms`;
        recordTurnInStream("RIME (mist_v3)", data.spoken_response, "assistant");
        simulateVoicePlayback(data.spoken_response);
      } else if (data.status === "INTERRUPTED_AND_FENCED") {
        agentStatePill.textContent = "STALE TOOL FENCED & DISCARDED";
        agentStatePill.className = "state-pill state-interrupted";
      }

    } catch (err) {
      console.error("Turn execution failed", err);
      agentStatePill.textContent = "ERROR";
    }
  }

  function simulateVoicePlayback(text) {
    isSpeaking = true;
    speechStartTime = performance.now();
    agentStatePill.textContent = "RIME SPEAKING (celeste)...";
    agentStatePill.className = "state-pill state-speaking";

    const words = text.split(" ");
    const durationMs = Math.max(1200, words.length * 350);

    if (simulatedAudioTimer) clearInterval(simulatedAudioTimer);
    simulatedAudioTimer = setTimeout(() => {
      isSpeaking = false;
      agentStatePill.textContent = "STANDBY";
      agentStatePill.className = "state-pill";
    }, durationMs);
  }

  function recordTurnInStream(sender, text, type) {
    const emptyState = auditoryStream.querySelector(".empty-state");
    if (emptyState) emptyState.remove();

    const entry = document.createElement("div");
    entry.className = `turn-entry ${type}`;
    entry.innerHTML = `<strong>${sender}:</strong> ${text}`;
    auditoryStream.appendChild(entry);
    auditoryStream.scrollTop = auditoryStream.scrollHeight;
  }

  function addFenceLogRow(event) {
    const placeholder = logTableBody.querySelector(".placeholder-row");
    if (placeholder) placeholder.remove();

    const tr = document.createElement("tr");
    const isFenced = event.status === "DISCARDED_STALE" || event.status === "CANCELLED_IN_FLIGHT";
    
    tr.innerHTML = `
      <td>${new Date().toLocaleTimeString()}</td>
      <td>Turn #${event.turn_id}</td>
      <td><code>${event.tool_name}</code></td>
      <td>${JSON.stringify(event.arguments)}</td>
      <td class="${isFenced ? 'status-fenced' : 'status-committed'}">${event.status}</td>
      <td>${event.duration_ms} ms</td>
      <td>${isFenced ? '<span class="tag-fenced">QUARANTINED & DISCARDED</span>' : 'SPOKEN CLEANLY'}</td>
    `;
    logTableBody.prepend(tr);
  }

  // --- 4. Interactive Scenario Buttons ---
  btnDopamine.addEventListener("click", () => {
    sendSpeechTurn("Calculate dopamine inotrope drip for 15kg patient (Heavy 2s calculation)");
  });

  btnInterrupt.addEventListener("click", () => {
    sendSpeechTurn("Stop! Patient flatlined, start asystole protocol!", true);
  });

  btnEpi.addEventListener("click", () => {
    sendSpeechTurn("Calculate pediatric epinephrine 1:10,000 for 15kg child");
  });

  btnVfib.addEventListener("click", () => {
    sendSpeechTurn("Patient in ventricular fibrillation! What is the shock protocol?");
  });

  speechForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const val = userInput.value.trim();
    if (val) {
      sendSpeechTurn(val);
      userInput.value = "";
    }
  });

  btnClearLogs.addEventListener("click", () => {
    logTableBody.innerHTML = '<tr class="placeholder-row"><td colspan="7">Audit logs cleared.</td></tr>';
    auditoryStream.innerHTML = '<div class="empty-state">No speech turns recorded yet.</div>';
  });
});

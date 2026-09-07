// CodeRed Triage - Kinetic Trauma Console Logic

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const ecgCanvas = document.getElementById("ecgCanvas");
  const ctx = ecgCanvas.getContext("2d");

  const valHr = document.getElementById("val-hr");
  const valSpo2 = document.getElementById("val-spo2");
  const valBp = document.getElementById("val-bp");
  const rhythmBadge = document.getElementById("rhythm-state-badge");
  const conditionText = document.getElementById("patient-condition-text");

  const voiceStateBar = document.getElementById("voice-state-bar");
  const agentStatePill = document.getElementById("agent-state-pill");
  const metricCutoffLatency = document.getElementById("metric-cutoff-latency");
  const metricRimeTtfa = document.getElementById("metric-rime-ttfa");
  const metricFencedCount = document.getElementById("metric-fenced-count");
  const dialogueFeed = document.getElementById("auditory-stream-display");
  const fenceAuditList = document.getElementById("fence-audit-list");

  const btnEpi = document.getElementById("btn-action-epi");
  const btnDopamine = document.getElementById("btn-action-dopamine");
  const btnInterrupt = document.getElementById("btn-action-interrupt");
  const btnVfib = document.getElementById("btn-action-vfib");
  const speechForm = document.getElementById("speech-form");
  const userInput = document.getElementById("user-input-field");

  let currentHeartRate = 132;
  let isCardiacArrest = false;
  let isSpeaking = false;
  let speechStartTime = 0;
  let totalFencedCount = 0;
  let activeAudioElement = null;

  // --- 1. Real-Time High-Contrast ECG Rhythm Strip ---
  let ecgX = 0;
  const canvasWidth = ecgCanvas.width;
  const canvasHeight = ecgCanvas.height;
  const centerY = canvasHeight / 2;

  // Initial dark background fill
  ctx.fillStyle = "#02050b";
  ctx.fillRect(0, 0, canvasWidth, canvasHeight);

  function renderEcgFrame() {
    // Clear a small leading slice ahead of the beam
    ctx.fillStyle = "rgba(2, 5, 11, 0.28)";
    ctx.fillRect(ecgX, 0, 12, canvasHeight);

    let y = centerY;
    const beatInterval = Math.max(14, Math.floor(500 / (currentHeartRate || 1)));

    if (isCardiacArrest) {
      // Asystole flatline with minor sensor artifact
      y = centerY + (Math.random() - 0.5) * 2.5;
    } else {
      const phase = ecgX % beatInterval;
      if (phase === 3) y = centerY - 5;          // P wave
      else if (phase === 6) y = centerY + 6;     // Q wave
      else if (phase === 8) y = centerY - 48;    // R wave peak
      else if (phase === 10) y = centerY + 18;   // S wave
      else if (phase === 14) y = centerY - 10;   // T wave
      else y = centerY + (Math.random() - 0.5) * 1.5;
    }

    ctx.strokeStyle = isCardiacArrest ? "#ff2b47" : "#00f588";
    ctx.shadowBlur = 6;
    ctx.shadowColor = isCardiacArrest ? "rgba(255, 43, 71, 0.7)" : "rgba(0, 245, 136, 0.7)";
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

  // --- 2. Pathway Real-Time Vitals Stream (SSE) ---
  const eventSource = new EventSource("/api/vitals/stream");
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      currentHeartRate = data.heart_rate_bpm;
      isCardiacArrest = data.is_cardiac_arrest;

      valHr.textContent = data.heart_rate_bpm;
      valSpo2.textContent = `${data.spo2_pct}%`;
      valBp.textContent = `${data.systolic_bp}/${data.diastolic_bp}`;
      rhythmBadge.textContent = data.rhythm_state.replace(/_/g, " ");

      if (data.is_cardiac_arrest) {
        rhythmBadge.className = "badge badge-emergency";
        conditionText.textContent = "CRITICAL ALERT: CARDIAC ARREST DETECTED (NO PULSE)";
        conditionText.className = "p-status alert-danger";
      } else {
        rhythmBadge.className = "badge badge-normal";
        conditionText.textContent = "Condition: Decompensating Shock (High Heart Rate)";
        conditionText.className = "p-status alert-warning";
      }
    } catch (e) {
      console.error("Vitals parse error", e);
    }
  };

  // --- 3. Speech Turn Execution & Hard Voice Engineering ---
  async function sendSpeechTurn(text, isInterruption = false) {
    let playbackDuration = 0;
    if (isSpeaking && speechStartTime > 0) {
      playbackDuration = (performance.now() - speechStartTime) / 1000.0;
    }

    // Handle instant barge-in cutoff
    if (isInterruption) {
      agentStatePill.textContent = "BARGE-IN DETECTED: FENCING BACKGROUND TASKS...";
      voiceStateBar.className = "voice-state-bar";
      if (activeAudioElement) {
        activeAudioElement.pause();
        activeAudioElement.currentTime = 0;
        activeAudioElement = null;
      }
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    } else {
      agentStatePill.textContent = "PROCESSING CLINICAL TURN...";
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

      // Log interruption record
      if (data.interruption_event) {
        metricCutoffLatency.textContent = `${data.interruption_event.cutoff_latency_ms} ms`;
        addDialogueBubble("PARAMEDIC (BARGE-IN)", text, "user bubble-interrupted");
      } else {
        addDialogueBubble("PARAMEDIC", text, "user");
      }

      // Log Fenced Tool Events
      if (data.fenced_events && data.fenced_events.length > 0) {
        totalFencedCount += data.fenced_events.length;
        metricFencedCount.textContent = `0.0% (${totalFencedCount} Fenced)`;
        data.fenced_events.forEach(addAuditItem);
      }

      // Play Rime Response
      if (data.spoken_response) {
        metricRimeTtfa.textContent = `TTFA: ${data.ttfa_ms ? Math.round(data.ttfa_ms) : 40}ms`;
        const speaker = (data.provider_metadata && data.provider_metadata.speaker) || "falcon";
        addDialogueBubble(`RIME AI (${speaker})`, data.spoken_response, "assistant");
        playRimeAudio(data.spoken_response, data.audio_base64, speaker);
      } else if (data.status === "INTERRUPTED_AND_FENCED") {
        agentStatePill.textContent = "STALE TOOL FENCED & SAFELY DISCARDED";
      }

    } catch (err) {
      console.error("Speech turn failed", err);
      agentStatePill.textContent = "ERROR: Failed to connect to server";
    }
  }

  // Real Audio Playback with Visualizer Glow
  function playRimeAudio(text, audioBase64, speaker) {
    isSpeaking = true;
    speechStartTime = performance.now();
    agentStatePill.textContent = `SPEAKING VIA RIME (${speaker})`;
    voiceStateBar.className = "voice-state-bar speaking-active";

    if (activeAudioElement) {
      activeAudioElement.pause();
      activeAudioElement.currentTime = 0;
      activeAudioElement = null;
    }

    if (audioBase64) {
      try {
        activeAudioElement = new Audio("data:audio/mp3;base64," + audioBase64);
        activeAudioElement.onended = () => {
          isSpeaking = false;
          agentStatePill.textContent = "STANDBY (Awaiting Command)";
          voiceStateBar.className = "voice-state-bar";
        };
        activeAudioElement.play().catch((err) => {
          console.warn("Audio autoplay blocked by browser, using speech synthesis fallback", err);
          fallbackBrowserSpeech(text);
        });
        return;
      } catch (e) {
        console.error("Audio error", e);
      }
    }

    fallbackBrowserSpeech(text);
  }

  function fallbackBrowserSpeech(text) {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05;
      u.onend = () => {
        isSpeaking = false;
        agentStatePill.textContent = "STANDBY (Awaiting Command)";
        voiceStateBar.className = "voice-state-bar";
      };
      window.speechSynthesis.speak(u);
    }
  }

  function addDialogueBubble(sender, text, role) {
    const placeholder = dialogueFeed.querySelector(".feed-placeholder");
    if (placeholder) placeholder.remove();

    const bubble = document.createElement("div");
    bubble.className = `bubble bubble-${role}`;

    bubble.innerHTML = `
      <div class="bubble-sender">
        <span>${sender}</span>
        <span>${new Date().toLocaleTimeString()}</span>
      </div>
      <div class="bubble-body">${text}</div>
    `;

    dialogueFeed.appendChild(bubble);
    dialogueFeed.scrollTop = dialogueFeed.scrollHeight;
  }

  function addAuditItem(event) {
    const empty = fenceAuditList.querySelector(".audit-empty");
    if (empty) empty.remove();

    const isFenced = event.status === "DISCARDED_STALE" || event.status === "CANCELLED_IN_FLIGHT";
    const item = document.createElement("div");
    item.className = `audit-item ${isFenced ? 'fenced' : 'committed'}`;

    item.innerHTML = `
      <div>
        <strong>${event.tool_name.replace(/_/g, " ")}</strong>
        <span style="display:block; font-size:0.6rem; color:#7987a1;">${event.duration_ms}ms • Turn #${event.turn_id}</span>
      </div>
      <span class="audit-status" style="color: ${isFenced ? '#ff2b47' : '#00f588'}">
        ${isFenced ? 'FENCED & DISCARDED' : 'COMMITTED'}
      </span>
    `;

    fenceAuditList.prepend(item);
  }

  // --- 4. Interactive Scenario Buttons ---
  btnEpi.addEventListener("click", () => {
    sendSpeechTurn("Calculate pediatric epinephrine for 15kg child");
  });

  btnDopamine.addEventListener("click", () => {
    sendSpeechTurn("Calculate dopamine inotrope drip for 15kg patient (Heavy 2s calculation)");
  });

  btnInterrupt.addEventListener("click", () => {
    sendSpeechTurn("Stop! Patient flatlined, start asystole protocol!", true);
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
});

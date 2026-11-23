// Aura Offscreen Document — Soft Apple-style Sound Feedback & Background Helper

let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }
  return audioCtx;
}

function playTone(freq, duration = 0.14, gainPeak = 0.05, delay = 0, type = "sine") {
  const ctx = getAudioContext();
  const now = ctx.currentTime + delay;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = type;
  osc.frequency.setValueAtTime(freq, now);

  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(gainPeak, now + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

  osc.connect(gain);
  gain.connect(ctx.destination);

  osc.start(now);
  osc.stop(now + duration + 0.02);
}

function playSound(kind) {
  try {
    if (kind === "start") {
      playTone(587.33, 0.12, 0.04, 0);
      playTone(880.0, 0.18, 0.045, 0.07);
    } else if (kind === "done") {
      playTone(523.25, 0.14, 0.045, 0);
      playTone(659.25, 0.16, 0.045, 0.08);
      playTone(1046.5, 0.28, 0.05, 0.16);
    } else if (kind === "notify") {
      playTone(783.99, 0.18, 0.045, 0);
      playTone(659.25, 0.22, 0.04, 0.1);
    } else if (kind === "click") {
      playTone(920, 0.045, 0.02, 0, "triangle");
    }
  } catch (_) {}
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.target !== "offscreen") return;
  if (msg.type === "PLAY_SOUND") {
    playSound(msg.kind);
    sendResponse({ ok: true });
    return true;
  }
});

"""Local browser UI for exploring the AbletonGPT feature set.

The page is intentionally self-contained: one HTML document, a small JSON API, and no
external frontend dependencies. It exposes the main pure features (SongSpec, compose,
vocal, instruments, contextual analysis, expression, arrangement, audio/loudness tools)
plus a small Live control surface when Ableton is reachable.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..arrange.presets import arrangement_for_style, simple_arrangement
from ..audio import (
    analyze_stereo_field,
    detect_onsets,
    estimate_chords,
    estimate_key,
    estimate_tempo,
    extract_melody,
    extract_spectral_bands,
    extract_spectral_features,
    segment_structure,
    track_beats,
)
from ..cli.serialization import arrangement_to_dict
from ..composition import GENRE_PROFILES, build_song_plan
from ..contextual import analyze_midi_context, build_complementary_track_plan
from ..develop import build_developed_arrangement
from ..expression import build_expression_plan
from ..instruments import build_instrument_plan
from ..jobs import build_job_plan
from ..layering import build_layering_plan
from ..loudness import analyze_loudness_file
from ..narrative import build_narrative_arc
from ..songspec import (
    build_song_spec_from_plan,
    build_song_spec_from_prompt,
    parse_song_spec_text,
    song_spec_to_dict,
    song_spec_to_yaml,
)
from ..vocal import build_vocal_plan


DEFAULT_PROMPT = (
    "110 BPM, D# minor. Mutation Funk, Dub, Tech House hybrid. Slap bass. "
    "Sparse vocoder. 5 minutes."
)
DEFAULT_LYRICS = "la la shine on, move through the night, keep the bassline tight"
DEFAULT_AUDIO_FILE = "exports/test002_MASTER_-9LUFS_-1dBTP.wav"
DEFAULT_CLIP = {
    "track": "Bass",
    "track_index": 1,
    "clip_index": 0,
    "length_beats": 32.0,
    "time_signature": [4, 4],
    "notes": [
        {"pitch": 40, "start_time": 0.0, "duration": 1.0, "velocity": 96},
        {"pitch": 43, "start_time": 2.0, "duration": 1.0, "velocity": 90},
        {"pitch": 45, "start_time": 4.0, "duration": 1.0, "velocity": 92},
        {"pitch": 47, "start_time": 6.0, "duration": 1.0, "velocity": 94},
        {"pitch": 48, "start_time": 8.0, "duration": 1.0, "velocity": 90},
        {"pitch": 50, "start_time": 10.0, "duration": 1.0, "velocity": 92},
    ],
}

_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AbletonGPT Studio</title>
  <style>
    :root {
      --bg: #0d0f14;
      --panel: #151a23;
      --panel-2: #1b2130;
      --text: #edf2ff;
      --muted: #98a2b3;
      --line: #2b3446;
      --accent: #66e3b4;
      --accent-2: #7aa8ff;
      --warn: #ffb86b;
      --danger: #ff7373;
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(122, 168, 255, 0.18), transparent 28%),
        radial-gradient(circle at 80% 10%, rgba(102, 227, 180, 0.15), transparent 22%),
        linear-gradient(180deg, #0b0e13 0%, #0d0f14 100%);
      font-family: Avenir, "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      min-height: 100vh;
    }
    header {
      padding: 28px 28px 12px;
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
    }
    .brand h1 {
      margin: 0;
      font-size: 32px;
      letter-spacing: 0.02em;
    }
    .brand p { margin: 6px 0 0; color: var(--muted); max-width: 64ch; }
    .badge {
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      background: rgba(255,255,255,0.02);
    }
    main {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 16px;
      padding: 16px 28px 28px;
    }
    .panel {
      background: linear-gradient(180deg, rgba(255,255,255,0.03), transparent 32%), var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 18px 20px 12px;
      font-size: 15px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
    }
    .panel-body { padding: 18px 20px 20px; }
    .grid { display: grid; gap: 12px; }
    .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    label { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
    input, select, textarea, button {
      font: inherit;
      border-radius: 14px;
      border: 1px solid var(--line);
      color: var(--text);
      background: var(--panel-2);
    }
    input, select, textarea { padding: 10px 12px; }
    textarea { min-height: 120px; resize: vertical; }
    button {
      padding: 11px 14px;
      cursor: pointer;
      background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent), var(--panel-2);
    }
    button.primary {
      border-color: rgba(102, 227, 180, 0.4);
      background: linear-gradient(180deg, rgba(102, 227, 180, 0.18), rgba(102, 227, 180, 0.04));
    }
    button:hover { border-color: rgba(122,168,255,0.5); }
    .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .tabs button { padding: 8px 12px; border-radius: 999px; }
    .tabs button.active { border-color: rgba(102, 227, 180, 0.7); color: var(--accent); }
    .stack { display: grid; gap: 14px; }
    .card {
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
    }
    .card h3 { margin: 0 0 10px; font-size: 14px; }
    .muted { color: var(--muted); }
    pre {
      margin: 0;
      padding: 14px;
      border-radius: 16px;
      background: #091018;
      border: 1px solid #223047;
      color: #d9e2ff;
      overflow: auto;
      max-height: 360px;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SFMono-Regular", Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
    }
    .result-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      background: rgba(255,255,255,0.02);
      font-size: 12px;
    }
    .pill.ok { color: var(--accent); }
    .pill.warn { color: var(--warn); }
    .pill.bad { color: var(--danger); }
    .hide { display: none !important; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; }
    .row-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .footer-note { color: var(--muted); font-size: 12px; margin-top: 10px; }
    @media (max-width: 1100px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>AbletonGPT Studio</h1>
      <p>SongSpec を中心に、Intent / Compose / Vocal / Instruments / Contextual / Expression / Audio / Live を 1 画面で回すローカル操縦席。</p>
    </div>
    <div class="badge" id="status">localhost UI ready</div>
  </header>
  <main>
    <section class="panel">
      <h2>Control Room</h2>
      <div class="panel-body stack">
        <div class="tabs" id="tabs"></div>
        <div class="card" id="tab-intent">
          <h3>Intent -> SongSpec</h3>
          <div class="grid">
            <label>Prompt<textarea id="intent-prompt">__DEFAULT_PROMPT__</textarea></label>
            <div class="grid two">
              <label>Title<input id="intent-title" value="KIHACHI Beta Demo" /></label>
              <label>Mode<select id="intent-output"><option value="yaml">YAML</option><option value="json">JSON</option></select></label>
            </div>
            <div class="toolbar"><button class="primary" data-action="intent">Build SongSpec</button></div>
          </div>
        </div>

        <div class="card hide" id="tab-compose">
          <h3>Compose</h3>
          <div class="grid three">
            <label>Title<input id="compose-title" value="KIHACHI Beta Demo" /></label>
            <label>Genre<select id="compose-genre"></select></label>
            <label>Mood<select id="compose-mood"></select></label>
          </div>
          <div class="grid three">
            <label>Key<input id="compose-key" value="D#" /></label>
            <label>Mode<select id="compose-mode"><option>major</option><option selected>minor</option></select></label>
            <label>Tempo<input id="compose-tempo" type="number" step="1" value="110" /></label>
          </div>
          <div class="grid three">
            <label>Bars<input id="compose-bars" type="number" step="1" value="8" /></label>
            <label>Complexity<select id="compose-complexity"><option>triad</option><option selected>seventh</option><option>ninth</option></select></label>
            <label>Seed<input id="compose-seed" type="number" step="1" value="42" /></label>
          </div>
          <div class="grid three">
            <label>Density<input id="compose-density" type="number" step="0.01" value="0.55" /></label>
            <label>Swing<input id="compose-swing" type="number" step="0.01" value="0.4" /></label>
            <label>Humanize<input id="compose-humanize" type="number" step="0.01" value="0.3" /></label>
          </div>
          <label>SongSpec YAML / JSON<textarea id="compose-spec">__DEFAULT_SPEC_YAML__</textarea></label>
          <div class="toolbar">
            <button class="primary" data-action="compose">Build Sketch</button>
            <button class="primary" data-action="compose-from-spec">Build From SongSpec</button>
            <button class="primary" data-action="live-from-spec">Create In Live</button>
          </div>
        </div>

        <div class="card hide" id="tab-live">
          <h3>Live</h3>
          <div class="grid two">
            <label>Live action<select id="live-action">
              <option value="status">status</option>
              <option value="mix">mix snapshot</option>
              <option value="transport">transport play/stop</option>
              <option value="song-sketch">create song sketch</option>
              <option value="instruments">plan instruments</option>
              <option value="drum-kit">apply drum kit</option>
            </select></label>
            <label>Transport<select id="live-transport"><option value="play">play</option><option value="stop">stop</option></select></label>
          </div>
          <div class="grid three">
            <label>Track index<input id="live-track-index" type="number" value="1" /></label>
            <label>Role<input id="live-role" value="chords" /></label>
            <label>Genre<select id="live-genre"></select></label>
          </div>
          <div class="grid three">
            <label>Mood<select id="live-mood"></select></label>
            <label>Edition<select id="live-edition"><option>unknown</option><option>standard</option><option>suite</option></select></label>
            <label>Preferred instrument<input id="live-preferred-instrument" placeholder="Wavetable" /></label>
          </div>
          <div class="toolbar"><button class="primary" data-action="live">Run Live Action</button></div>
        </div>

        <div class="card hide" id="tab-vocal">
          <h3>Vocal</h3>
          <div class="grid two">
            <label>Lyrics<textarea id="vocal-lyrics">__DEFAULT_LYRICS__</textarea></label>
            <div class="grid">
              <label>Title<input id="vocal-title" value="KIHACHI Vocal Demo" /></label>
              <label>Genre<select id="vocal-genre"></select></label>
              <label>Mood<select id="vocal-mood"></select></label>
              <label>Key<input id="vocal-key" value="C" /></label>
              <label>Mode<select id="vocal-mode"><option>major</option><option selected>minor</option></select></label>
              <label>Tempo<input id="vocal-tempo" type="number" value="110" /></label>
              <label>Bars<input id="vocal-bars" type="number" value="8" /></label>
            </div>
          </div>
          <div class="toolbar"><button class="primary" data-action="vocal">Build Vocal Plan</button></div>
        </div>

        <div class="card hide" id="tab-contextual">
          <h3>Contextual / Expression / Develop</h3>
          <div class="grid two">
            <label>Clip JSON<textarea id="clip-json">__DEFAULT_CLIP__</textarea></label>
            <div class="grid">
              <label>Target role<select id="target-role"><option>melody</option><option>bass</option><option>chords</option><option>pad</option><option>countermelody</option><option>drums</option></select></label>
              <label>Source role<select id="source-role"><option>auto</option><option>chords</option><option>bass</option><option>melody</option><option>pad</option><option>drums</option></select></label>
              <label>Accent<input id="accent" type="number" step="0.01" value="0.35" /></label>
              <label>Swing<input id="swing" type="number" step="0.01" value="0.25" /></label>
              <label>Humanize<input id="humanize" type="number" step="0.01" value="0.2" /></label>
              <label>Weak beat probability<input id="weak-prob" type="number" step="0.01" value="0.7" /></label>
            </div>
          </div>
          <div class="toolbar">
            <button class="primary" data-action="contextual-analyze">Analyze Clip</button>
            <button class="primary" data-action="contextual-plan">Plan Complement</button>
            <button class="primary" data-action="expression">Express Clip</button>
            <button class="primary" data-action="develop">Develop Arrangement</button>
            <button class="primary" data-action="layering">Layering Plan</button>
            <button class="primary" data-action="narrative">Narrative Arc</button>
          </div>
        </div>

        <div class="card hide" id="tab-audio">
          <h3>Audio / Loudness</h3>
          <div class="grid two">
            <label>File path<input id="audio-file" value="__DEFAULT_AUDIO_FILE__" /></label>
            <label>Target LUFS<input id="target-lufs" type="number" step="0.1" value="-14" /></label>
          </div>
          <div class="toolbar">
            <button class="primary" data-action="audio-loudness">Loudness</button>
            <button class="primary" data-action="audio-tempo">Tempo</button>
            <button class="primary" data-action="audio-key">Key</button>
            <button class="primary" data-action="audio-chords">Chords</button>
            <button class="primary" data-action="audio-melody">Melody</button>
            <button class="primary" data-action="audio-onsets">Onsets</button>
            <button class="primary" data-action="audio-beats">Beats</button>
            <button class="primary" data-action="audio-spectral">Spectral</button>
            <button class="primary" data-action="audio-bands">Bands</button>
            <button class="primary" data-action="audio-stereo">Stereo</button>
            <button class="primary" data-action="audio-structure">Structure</button>
          </div>
        </div>

        <div class="card hide" id="tab-arrange">
          <h3>Arrange / Jobs</h3>
          <div class="grid two">
            <label>Style<select id="arrange-style"><option>dark-tech-house</option><option>deep-house</option><option>minimal-techno</option><option>dub-techno</option><option>pop-song</option></select></label>
            <label>Structure<textarea id="arrange-structure">Intro, Verse, Chorus, Breakdown, Chorus, Outro</textarea></label>
          </div>
          <div class="toolbar">
            <button class="primary" data-action="arrangement">Build Arrangement</button>
            <button class="primary" data-action="job-plan">Build Job Plan</button>
          </div>
        </div>
      </div>
      <div class="footer-note">The UI is local-only. Results are shown as JSON for inspection and can be fed back into the CLI or Ableton steps.</div>
    </section>

    <section class="panel">
      <h2>Results</h2>
      <div class="panel-body stack">
        <div class="card">
          <h3>Latest Result</h3>
          <div class="result-meta" id="meta"></div>
          <pre id="output">Pick a tab and press a button.</pre>
        </div>
        <div class="card">
          <h3>Quick Notes</h3>
          <pre id="notes">{}</pre>
        </div>
      </div>
    </section>
  </main>
  <script>
    const TABS = ["intent", "compose", "live", "vocal", "contextual", "audio", "arrange"];
    const GENRES = __GENRES__;
    const MOODS = __MOODS__;
    const tabButtons = document.getElementById("tabs");
    const meta = document.getElementById("meta");
    const output = document.getElementById("output");
    const notes = document.getElementById("notes");
    const status = document.getElementById("status");

    function setStatus(text, kind = "") {
      status.textContent = text;
      status.className = "badge" + (kind ? " " + kind : "");
    }

    function showTab(name) {
      for (const tab of TABS) {
        document.getElementById("tab-" + tab).classList.toggle("hide", tab !== name);
      }
      for (const button of tabButtons.querySelectorAll("button")) {
        button.classList.toggle("active", button.dataset.tab === name);
      }
    }

    function addResultPill(label, kind = "") {
      const span = document.createElement("span");
      span.className = "pill" + (kind ? " " + kind : "");
      span.textContent = label;
      meta.appendChild(span);
    }

    function renderResult(action, payload) {
      meta.innerHTML = "";
      addResultPill(action, "ok");
      if (payload && payload.read_only === true) addResultPill("read-only", "warn");
      if (payload && payload.error) addResultPill("error", "bad");
      if (action === "intent" && payload && payload.song_spec) {
        syncComposeFromSongSpec(payload.song_spec, payload.format === "yaml" ? payload.text : JSON.stringify(payload.song_spec, null, 2));
        addResultPill("compose synced", "ok");
      }
      if (action === "compose-from-spec" && payload && payload.song_spec_source) {
        syncComposeFromSongSpec(payload.song_spec_source, document.getElementById("compose-spec").value);
      }
      output.textContent = JSON.stringify(payload, null, 2);
      notes.textContent = JSON.stringify({
        action,
        top_level_keys: payload ? Object.keys(payload).slice(0, 10) : [],
      }, null, 2);
    }

    function fillSelect(id, values) {
      const select = document.getElementById(id);
      select.innerHTML = values.map((value) => `<option value="${value}">${value}</option>`).join("");
    }

    function setSelectValue(id, value) {
      const select = document.getElementById(id);
      if ([...select.options].some((option) => option.value === value)) {
        select.value = value;
      }
    }

    function syncComposeFromSongSpec(songSpec, rawText) {
      const settings = songSpec.settings || {};
      document.getElementById("compose-spec").value = rawText;
      document.getElementById("compose-title").value = songSpec.title || "Untitled Sketch";
      document.getElementById("compose-key").value = songSpec.key || "C";
      setSelectValue("compose-mode", songSpec.mode || "major");
      document.getElementById("compose-tempo").value = Number(songSpec.tempo || 110);
      document.getElementById("compose-bars").value = Number(songSpec.bars || 8);
      setSelectValue("compose-genre", songSpec.genre || "pop");
      setSelectValue("compose-mood", songSpec.mood || "bright");
      setSelectValue("compose-complexity", settings.chord_complexity || "triad");
      document.getElementById("compose-density").value = Number(settings.melody_density ?? 0.75);
      document.getElementById("compose-swing").value = Number(settings.swing ?? 0.0);
      document.getElementById("compose-humanize").value = Number(settings.humanize ?? 0.0);
      document.getElementById("compose-seed").value = Number(settings.seed ?? 0);
    }

    async function post(action, payload) {
      setStatus("running " + action, "warn");
      const response = await fetch("/api/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action, payload}),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error || response.statusText);
      }
      setStatus("ready", "ok");
      renderResult(action, body);
    }

    document.getElementById("tabs").innerHTML = TABS.map((tab) => `<button data-tab="${tab}">${tab}</button>`).join("");
    for (const button of tabButtons.querySelectorAll("button")) {
      button.addEventListener("click", () => showTab(button.dataset.tab));
    }
    fillSelect("compose-genre", GENRES);
    fillSelect("compose-mood", MOODS);
    fillSelect("live-genre", GENRES);
    fillSelect("live-mood", MOODS);
    fillSelect("vocal-genre", GENRES);
    fillSelect("vocal-mood", MOODS);
    showTab("intent");

    document.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const action = button.dataset.action;
          const payload = collect(action);
          await post(action, payload);
        } catch (error) {
          setStatus("error", "bad");
          renderResult("error", {error: String(error)});
        }
      });
    });

    function collect(action) {
      switch (action) {
        case "intent":
          return {prompt: document.getElementById("intent-prompt").value, title: document.getElementById("intent-title").value, output: document.getElementById("intent-output").value};
        case "compose":
          return {
            title: document.getElementById("compose-title").value,
            genre: document.getElementById("compose-genre").value,
            mood: document.getElementById("compose-mood").value,
            key: document.getElementById("compose-key").value,
            mode: document.getElementById("compose-mode").value,
            tempo: Number(document.getElementById("compose-tempo").value),
            bars: Number(document.getElementById("compose-bars").value),
            complexity: document.getElementById("compose-complexity").value,
            density: Number(document.getElementById("compose-density").value),
            swing: Number(document.getElementById("compose-swing").value),
            humanize: Number(document.getElementById("compose-humanize").value),
            seed: Number(document.getElementById("compose-seed").value),
          };
        case "compose-from-spec":
          return {song_spec: document.getElementById("compose-spec").value};
        case "live-from-spec":
          return {
            song_spec: document.getElementById("compose-spec").value,
            auto_apply_instruments: true,
            auto_fire_scene: true,
            auto_play: true,
            clip_index: 0,
            scene_index: 0,
          };
        case "live":
          return {
            live_action: document.getElementById("live-action").value,
            transport: document.getElementById("live-transport").value,
            track_index: Number(document.getElementById("live-track-index").value),
            role: document.getElementById("live-role").value,
            genre: document.getElementById("live-genre").value,
            mood: document.getElementById("live-mood").value,
            edition: document.getElementById("live-edition").value,
            preferred_instrument: document.getElementById("live-preferred-instrument").value,
          };
        case "vocal":
          return {
            title: document.getElementById("vocal-title").value,
            lyrics: document.getElementById("vocal-lyrics").value,
            genre: document.getElementById("vocal-genre").value,
            mood: document.getElementById("vocal-mood").value,
            key: document.getElementById("vocal-key").value,
            mode: document.getElementById("vocal-mode").value,
            tempo: Number(document.getElementById("vocal-tempo").value),
            bars: Number(document.getElementById("vocal-bars").value),
          };
        case "contextual-analyze":
          return {clip: document.getElementById("clip-json").value, source_role: document.getElementById("source-role").value};
        case "contextual-plan":
          return {
            clip: document.getElementById("clip-json").value,
            target_role: document.getElementById("target-role").value,
            source_role: document.getElementById("source-role").value,
            genre: document.getElementById("compose-genre").value,
            mood: document.getElementById("compose-mood").value,
          };
        case "expression":
          return {
            clip: document.getElementById("clip-json").value,
            accent: Number(document.getElementById("accent").value),
            swing: Number(document.getElementById("swing").value),
            humanize: Number(document.getElementById("humanize").value),
            weak_beat_probability: Number(document.getElementById("weak-prob").value),
          };
        case "develop":
          return {clip: document.getElementById("clip-json").value};
        case "layering":
          return {tracks: defaultTracks(), structure: defaultStructure()};
        case "narrative":
          return {structure: defaultStructure()};
        case "audio-loudness":
        case "audio-tempo":
        case "audio-key":
        case "audio-chords":
        case "audio-melody":
        case "audio-onsets":
        case "audio-beats":
        case "audio-spectral":
        case "audio-bands":
        case "audio-stereo":
        case "audio-structure":
          return {file_path: document.getElementById("audio-file").value, target_lufs: Number(document.getElementById("target-lufs").value)};
        case "arrangement":
          return {style: document.getElementById("arrange-style").value, name: "studio_layout"};
        case "job-plan":
          return {style: document.getElementById("arrange-style").value, name: "studio_layout"};
        default:
          return {};
      }
    }

    function defaultStructure() {
      return ["intro", "verse", "chorus", "breakdown", "chorus", "outro"];
    }

    function defaultTracks() {
      return [
        {index: 0, name: "Kick", role: "drums"},
        {index: 1, name: "Bass", role: "bass"},
        {index: 2, name: "Chords", role: "chords"},
        {index: 3, name: "Lead", role: "lead"},
        {index: 4, name: "Pad", role: "pad"},
      ];
    }
  </script>
</body>
</html>
"""


def _json_body(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _read_json_request(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    data = handler.rfile.read(length) if length else b"{}"
    if not data:
        return {}
    body = json.loads(data.decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def _clip_from_text(text: str) -> dict[str, Any]:
    return json.loads(text)


def _normalize_numeric(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _normalize_numeric(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numeric(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_numeric(item) for item in value]
    return value


def _arrangement_document(style: str, name: str) -> dict[str, Any]:
    if style == "dark-tech-house":
        plan = arrangement_for_style("dark-tech-house", name)
    elif style == "deep-house":
        plan = arrangement_for_style("deep-house", name)
    elif style == "minimal-techno":
        plan = arrangement_for_style("minimal-techno", name)
    elif style == "dub-techno":
        plan = arrangement_for_style("dub-techno", name)
    else:
        plan = simple_arrangement(name)
    return arrangement_to_dict(plan)


def _arrangement_plan(style: str, name: str):
    if style == "dark-tech-house":
        return arrangement_for_style("dark-tech-house", name)
    if style == "deep-house":
        return arrangement_for_style("deep-house", name)
    if style == "minimal-techno":
        return arrangement_for_style("minimal-techno", name)
    if style == "dub-techno":
        return arrangement_for_style("dub-techno", name)
    return simple_arrangement(name)


def _song_spec_inputs(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    spec_data = parse_song_spec_text(payload.get("song_spec", ""))
    settings = dict(spec_data.get("settings") or {})
    return spec_data, settings


def _role_from_track_name(track_name: str) -> str:
    lowered = str(track_name).strip().lower()
    if "drum" in lowered:
        return "drums"
    if "bass" in lowered:
        return "bass"
    if "chord" in lowered:
        return "chords"
    if "pad" in lowered:
        return "pad"
    if "lead" in lowered:
        return "lead"
    if "melody" in lowered:
        return "melody"
    return "chords"


def _dispatch(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "intent":
        spec = build_song_spec_from_prompt(payload.get("prompt", DEFAULT_PROMPT), title=payload.get("title") or None)
        output = str(payload.get("output", "yaml"))
        return {
            "action": action,
            "song_spec": song_spec_to_dict(spec),
            "format": output,
            "text": song_spec_to_yaml(spec) if output == "yaml" else json.dumps(song_spec_to_dict(spec), indent=2, sort_keys=True, ensure_ascii=False),
            "read_only": True,
        }
    if action == "compose":
        plan = build_song_plan(
            payload.get("title", "Untitled Sketch"),
            payload.get("genre", "pop"),
            payload.get("mood", "bright"),
            payload.get("key", "C"),
            payload.get("mode", "major"),
            float(payload.get("tempo", 110.0)),
            int(payload.get("bars", 8)),
            chord_complexity=payload.get("complexity", "triad"),
            melody_density=float(payload.get("density", 0.75)),
            swing=float(payload.get("swing", 0.0)),
            humanize=float(payload.get("humanize", 0.0)),
            seed=int(payload.get("seed", 0)),
        )
        plan["song_spec"] = song_spec_to_dict(
            build_song_spec_from_plan(plan)
        )
        return plan
    if action == "compose-from-spec":
        spec_data, settings = _song_spec_inputs(payload)
        progression = settings.get("progression_degrees") or None
        plan = build_song_plan(
            str(spec_data.get("title", "Untitled Sketch")),
            str(spec_data.get("genre", "pop")),
            str(spec_data.get("mood", "bright")),
            str(spec_data.get("key", "C")),
            str(spec_data.get("mode", "major")),
            float(spec_data.get("tempo", 110.0)),
            int(spec_data.get("bars", 8)),
            progression=[int(value) for value in progression] if progression else None,
            chord_complexity=str(settings.get("chord_complexity", "triad")),
            harmonic_rhythm_beats=float(settings.get("harmonic_rhythm_beats", 4.0)),
            melody_density=float(settings.get("melody_density", 0.75)),
            swing=float(settings.get("swing", 0.0)),
            humanize=float(settings.get("humanize", 0.0)),
            seed=int(settings.get("seed", 0)),
        )
        plan["song_spec"] = song_spec_to_dict(build_song_spec_from_plan(plan))
        plan["song_spec_source"] = spec_data
        return plan
    if action == "live-from-spec":
        spec_data, _settings = _song_spec_inputs(payload)
        live_payload = {
            "title": str(spec_data.get("title", "Live Sketch")),
            "genre": str(spec_data.get("genre", "pop")),
            "mood": str(spec_data.get("mood", "bright")),
            "key": str(spec_data.get("key", "C")),
            "mode": str(spec_data.get("mode", "major")),
            "tempo": float(spec_data.get("tempo", 110.0)),
            "bars": int(spec_data.get("bars", 8)),
            "clip_index": int(payload.get("clip_index", 0)),
        }
        result = _dispatch("live-song-sketch", live_payload)
        result.setdefault("ok", True)
        if bool(payload.get("auto_apply_instruments", False)):
            applied_results: list[dict[str, Any]] = []
            for created_track in result.get("created", []):
                track_index = int(created_track.get("track_index", -1))
                if track_index < 0:
                    continue
                role = _role_from_track_name(str(created_track.get("track", "")))
                try:
                    if role == "drums":
                        applied = _dispatch(
                            "live-drum-kit",
                            {
                                "track_index": track_index,
                                "genre": live_payload["genre"],
                                "mood": live_payload["mood"],
                                "role": "drums",
                                "preferred_kit": str(payload.get("preferred_kit", "")),
                            },
                        )
                    else:
                        applied = _dispatch(
                            "live-instrument",
                            {
                                "track_index": track_index,
                                "role": role,
                                "genre": live_payload["genre"],
                                "mood": live_payload["mood"],
                                "edition": str(payload.get("edition", "unknown")),
                                "preferred_instrument": str(payload.get("preferred_instrument", "")),
                            },
                        )
                    readback = _dispatch("live-devices", {"track_index": track_index})
                    if not readback.get("devices"):
                        raise RuntimeError(
                            "Live did not report an inserted device after applying %s" % role
                        )
                    applied_results.append(
                        {
                            "track_index": track_index,
                            "role": role,
                            "ok": True,
                            "result": applied,
                            "devices": readback["devices"],
                        }
                    )
                except Exception as exc:
                    applied_results.append({"track_index": track_index, "role": role, "ok": False, "error": str(exc)})
            result["auto_apply_instruments"] = applied_results
            result["ok"] = bool(applied_results) and all(item.get("ok") for item in applied_results)
        if bool(payload.get("auto_fire_scene", False)):
            try:
                result["scene_fire"] = _dispatch(
                    "live-fire-scene",
                    {"scene_index": int(payload.get("scene_index", live_payload["clip_index"]))},
                )
            except Exception as exc:
                result["scene_fire_error"] = str(exc)
        if bool(payload.get("auto_play", False)):
            try:
                result["transport"] = _dispatch("live-transport-play", {})
            except Exception as exc:
                result["transport_error"] = str(exc)
        result["song_spec_source"] = spec_data
        return _normalize_numeric(result)
    if action == "vocal":
        return build_vocal_plan(
            title=payload.get("title", "Vocal Guide"),
            lyrics=payload.get("lyrics", DEFAULT_LYRICS),
            genre=payload.get("genre", "pop"),
            mood=payload.get("mood", "bright"),
            key=payload.get("key", "C"),
            mode=payload.get("mode", "major"),
            tempo=float(payload.get("tempo", 110.0)),
            bars=int(payload.get("bars", 8)),
            seed=int(payload.get("seed", 0)),
        )
    if action == "instruments":
        return build_instrument_plan(
            payload.get("genre", "pop"),
            payload.get("mood", "bright"),
            payload.get("roles") or ["chords", "bass", "melody", "drums"],
            payload.get("edition", "unknown"),
        )
    if action == "contextual-analyze":
        return analyze_midi_context(_clip_from_text(payload.get("clip", json.dumps(DEFAULT_CLIP))), source_role=payload.get("source_role", "auto"))
    if action == "contextual-plan":
        return build_complementary_track_plan(
            _clip_from_text(payload.get("clip", json.dumps(DEFAULT_CLIP))),
            target_role=payload.get("target_role", "melody"),
            source_role=payload.get("source_role", "auto"),
            genre=payload.get("genre", "pop"),
            mood=payload.get("mood", "bright"),
            key_override=payload.get("key", ""),
            mode_override=payload.get("mode", ""),
            seed=int(payload.get("seed", 0)),
            title=payload.get("title", ""),
        )
    if action == "expression":
        clip = _clip_from_text(payload.get("clip", json.dumps(DEFAULT_CLIP)))
        return build_expression_plan(
            clip,
            accent=float(payload.get("accent", 0.0)),
            swing=float(payload.get("swing", 0.0)),
            humanize=float(payload.get("humanize", 0.0)),
            weak_beat_probability=float(payload.get("weak_beat_probability", 1.0)),
            beats_per_bar=int(payload.get("beats_per_bar", 4)),
            grid_beats=float(payload.get("grid_beats", 0.5)),
            seed=int(payload.get("seed", 0)),
        )
    if action == "develop":
        clip = _clip_from_text(payload.get("clip", json.dumps(DEFAULT_CLIP)))
        return build_developed_arrangement(clip, payload.get("structure") or ["intro", "verse", "chorus", "breakdown", "chorus", "outro"], section_repeats=int(payload.get("section_repeats", 2)), seed=int(payload.get("seed", 0)))
    if action == "layering":
        return build_layering_plan(payload.get("structure") or ["intro", "verse", "chorus", "breakdown", "chorus", "outro"], payload.get("tracks") or [])
    if action == "narrative":
        return build_narrative_arc(payload.get("structure") or ["Intro", "Verse", "Chorus", "Breakdown", "Chorus", "Outro"])
    if action == "audio-tempo":
        return estimate_tempo(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-key":
        return estimate_key(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-loudness":
        return analyze_loudness_file(payload.get("file_path", DEFAULT_AUDIO_FILE), target_lufs=payload.get("target_lufs"))
    if action == "audio-chords":
        return estimate_chords(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-melody":
        return extract_melody(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-onsets":
        return detect_onsets(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-beats":
        return track_beats(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-spectral":
        return extract_spectral_features(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-bands":
        return extract_spectral_bands(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-stereo":
        return analyze_stereo_field(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "audio-structure":
        return segment_structure(payload.get("file_path", DEFAULT_AUDIO_FILE))
    if action == "arrangement":
        return _arrangement_document(payload.get("style", "dark-tech-house"), payload.get("name", "studio_layout"))
    if action == "job-plan":
        return build_job_plan(_arrangement_plan(payload.get("style", "dark-tech-house"), payload.get("name", "studio_layout")))

    if action == "live":
        live_action = str(payload.get("live_action", "status"))
        live_payload = dict(payload)
        if live_action == "status":
            return _dispatch("live-status", live_payload)
        if live_action == "mix":
            return _dispatch("live-plot", live_payload)
        if live_action == "transport":
            transport = str(live_payload.get("transport", "play"))
            return _dispatch(f"live-transport-{transport}", live_payload)
        if live_action == "song-sketch":
            return _dispatch("live-song-sketch", live_payload)
        if live_action == "instruments":
            return _dispatch("live-instruments", live_payload)
        if live_action == "drum-kit":
            return _dispatch("live-drum-kit", live_payload)
        raise ValueError(f"unknown live_action: {live_action}")

    # Live actions are imported lazily so the UI still boots when Ableton is unavailable.
    live_server = sys.modules.get("abletongpt.server")
    if live_server is None:
        live_server = importlib.import_module("abletongpt.server")
    if hasattr(live_server, "__package__") and getattr(live_server, "__package__", None) == "abletongpt":
        import abletongpt
        setattr(abletongpt, "server", live_server)

    if action == "live-status":
        return {
            "state": _normalize_numeric(live_server.get_live_state()),
            "mix": _normalize_numeric(live_server.get_mix_snapshot()),
        }
    if action == "live-transport":
        return live_server.set_transport(payload.get("transport", "play"))
    if action == "live-song-sketch":
        return live_server.create_song_sketch(
            title=payload.get("title", "Live Sketch"),
            genre=payload.get("genre", "pop"),
            mood=payload.get("mood", "bright"),
            key=payload.get("key", "C"),
            mode=payload.get("mode", "major"),
            tempo=float(payload.get("tempo", 110.0)),
            bars=int(payload.get("bars", 8)),
            clip_index=int(payload.get("clip_index", 0)),
        )
    if action == "live-instruments":
        return live_server.plan_live_instruments(
            genre=payload.get("genre", "pop"),
            mood=payload.get("mood", "bright"),
            roles=payload.get("roles") or ["chords", "bass", "melody", "drums"],
            live_edition=payload.get("edition", "unknown"),
        )
    if action == "live-devices":
        return live_server.get_track_devices(int(payload.get("track_index", 0)))
    if action == "live-drum-kit":
        return live_server.apply_live_drum_kit(
            track_index=int(payload.get("track_index", 0)),
            genre=payload.get("genre", "pop"),
            mood=payload.get("mood", "bright"),
            role=payload.get("role", "drums"),
            preferred_kit=payload.get("preferred_kit", ""),
        )
    if action == "live-instrument":
        return live_server.apply_live_instrument_selection(
            track_index=int(payload.get("track_index", 0)),
            role=payload.get("role", "chords"),
            genre=payload.get("genre", "pop"),
            mood=payload.get("mood", "bright"),
            live_edition=payload.get("edition", "unknown"),
            preferred_instrument=payload.get("preferred_instrument", ""),
        )
    if action == "live-transport-play":
        return live_server.set_transport("play")
    if action == "live-transport-stop":
        return live_server.set_transport("stop")
    if action == "live-fire-scene":
        return live_server.fire_scene(int(payload.get("scene_index", 0)))
    if action == "live-plot":
        return live_server.get_mix_snapshot()

    raise ValueError(f"unknown action: {action}")


class _UIHandler(BaseHTTPRequestHandler):
    server_version = "AbletonGPTUI/1.0"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler hook
        if self.path in {"/", "/index.html"}:
            self._send_text(HTTPStatus.OK, self.server.render_index())
            return
        if self.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler hook
        if self.path != "/api/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            request = _read_json_request(self)
            result = _dispatch(str(request.get("action", "")), dict(request.get("payload", {})))
            self._send_json(HTTPStatus.OK, result)
        except Exception as exc:  # pragma: no cover - converted to an HTTP error payload
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, *_args: object) -> None:
        return

    def _send_text(self, status: HTTPStatus, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        data = _json_body(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def render_index() -> str:
    default_spec_yaml = song_spec_to_yaml(
        build_song_spec_from_prompt(DEFAULT_PROMPT, title="KIHACHI Beta Demo")
    )
    html = _HTML.replace("__DEFAULT_PROMPT__", DEFAULT_PROMPT)
    html = html.replace("__DEFAULT_LYRICS__", DEFAULT_LYRICS)
    html = html.replace("__DEFAULT_CLIP__", json.dumps(DEFAULT_CLIP, ensure_ascii=False, indent=2))
    html = html.replace("__DEFAULT_AUDIO_FILE__", DEFAULT_AUDIO_FILE)
    html = html.replace("__DEFAULT_SPEC_YAML__", default_spec_yaml)
    html = html.replace("__GENRES__", json.dumps(sorted(GENRE_PROFILES)))
    html = html.replace("__MOODS__", json.dumps(["bright", "uplifting", "chill", "dark", "bittersweet", "tense"]))
    return html


def serve(host: str, port: int, *, open_browser: bool = False) -> int:
    httpd = ThreadingHTTPServer((host, port), _UIHandler)
    httpd.render_index = render_index  # type: ignore[attr-defined]
    url = f"http://{host}:{port}/"
    print(f"AbletonGPT Studio running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.ui",
        description="Start the local AbletonGPT Studio web UI.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: %(default)s).")
    parser.add_argument("--port", type=int, default=8787, help="Port to bind (default: %(default)s).")
    parser.add_argument("--open-browser", action="store_true", help="Open the UI in a browser automatically.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return serve(args.host, args.port, open_browser=args.open_browser)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
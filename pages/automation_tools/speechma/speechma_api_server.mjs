import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { promisify } from "node:util";
import { execFile as execFileCb } from "node:child_process";

const execFile = promisify(execFileCb);

const PORT = Number(process.env.SPEECHMA_API_PORT || 8787);
const HOST = process.env.SPEECHMA_API_HOST || "127.0.0.1";
const REPO_ROOT = process.cwd();
const TOOL_ROOT = path.dirname(new URL(import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, "$1");
const NODE_EXE = "C:\\Program Files\\nodejs\\node.exe";
const BROWSEROS_JS = "C:\\Users\\Saurabh\\Downloads\\videoAgent\\node_modules\\browseros-cli\\bin\\browseros-cli.js";

function json(res, status, data) {
  const body = JSON.stringify(data, null, 2);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(body);
}

async function run(cmd, args, opts = {}) {
  try {
    const resolvedCmd = cmd === "browseros-cli" ? NODE_EXE : cmd;
    const resolvedArgs = cmd === "browseros-cli" ? [BROWSEROS_JS, ...args] : args;
    const { stdout, stderr } = await execFile(resolvedCmd, resolvedArgs, {
      cwd: REPO_ROOT,
      maxBuffer: 1024 * 1024 * 20,
      ...opts,
    });
    return { stdout: stdout ?? "", stderr: stderr ?? "" };
  } catch (error) {
    const stdout = error.stdout ?? "";
    const stderr = error.stderr ?? "";
    throw new Error(`Command failed: ${cmd} ${args.join(" ")}\n${stdout}\n${stderr}\n${error.message}`);
  }
}

function parseJsonFromOutput(text) {
  const trimmed = String(text || "").trim();
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start < 0 || end < 0 || end <= start) throw new Error(`Could not parse JSON: ${trimmed.slice(0, 400)}`);
  return JSON.parse(trimmed.slice(start, end + 1));
}

async function detectSpeechmaPages() {
  const { stdout } = await run("browseros-cli", ["pages", "--json"]);
  const parsed = JSON.parse(stdout);
  const pages = parsed.pages || [];
  return pages.filter((p) => String(p.url || "").includes("speechmapro.com"));
}

async function ensureFreshSpeechmaPage(preferredPageId) {
  const pages = await detectSpeechmaPages();
  if (Number.isFinite(Number(preferredPageId))) {
    const p = pages.find((x) => Number(x.pageId) === Number(preferredPageId));
    if (p) return Number(p.pageId);
  }

  for (const p of pages) {
    try { await run("browseros-cli", ["close", "--page", String(p.pageId)]); } catch {}
  }

  await run("browseros-cli", ["open", "https://speechmapro.com"]);

  for (let i = 0; i < 80; i += 1) {
    await new Promise((r) => setTimeout(r, 250));
    const list = await detectSpeechmaPages();
    if (!list.length) continue;
    const pid = Number(list[0].pageId);
    const { stdout } = await run("browseros-cli", [
      "eval",
      "--page",
      String(pid),
      "(() => ({ ok: !!document.getElementById('textInput') }))()",
    ]);
    const probe = parseJsonFromOutput(stdout);
    if (probe.ok) return pid;
  }
  throw new Error("Could not open fresh Speechma page with textInput ready.");
}

async function selectVoice(pageId, voiceLabel) {
  const safe = String(voiceLabel || "").replace(/`/g, "");
  const js = `(() => {
    const normalize = (s) => (s || "").toLowerCase().replace(/\\s+/g, " ").trim();
    const want = normalize(\`${safe}\`);
    const search = document.getElementById("voiceSearch");
    if (search) {
      search.value = \`${safe}\`;
      search.dispatchEvent(new Event("input", { bubbles: true }));
      search.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const opts = [...document.querySelectorAll("#voicesContainer .voice-option, .voice-option")];
    const hit = opts.find((el) => {
      const t = normalize(el.textContent || "");
      return t && (t.startsWith(want + " ") || t.includes(want));
    });
    if (!hit) return { ok:false, reason:"voice_not_found", want };
    hit.click();
    return { ok:true, selected:(hit.textContent||"").trim().slice(0,120), cls: hit.className || "" };
  })()`;
  const { stdout } = await run("browseros-cli", ["eval", "--page", String(pageId), js]);
  return parseJsonFromOutput(stdout);
}

async function applyEffects(pageId, pitch, speed, volume) {
  const openJs = `(() => {
    const byId = document.getElementById("voiceSettingsBtn");
    const byText = [...document.querySelectorAll("button,[role=button],a,div,span")]
      .find(n => ((n.textContent||"").trim().toLowerCase() === "voice effects"));
    const btn = byId || byText;
    if (!btn) return {ok:false, reason:"voice_effects_button_not_found"};
    btn.click();
    return {ok:true};
  })()`;
  const { stdout: o } = await run("browseros-cli", ["eval", "--page", String(pageId), openJs]);
  const opened = parseJsonFromOutput(o);
  if (!opened.ok) return opened;

  for (let i = 0; i < 40; i += 1) {
    const { stdout } = await run("browseros-cli", ["eval", "--page", String(pageId), "(() => ({a:!!document.getElementById('pitchSlider'),b:!!document.getElementById('rateSlider'),c:!!document.getElementById('volumeSlider')}))()"]);
    const p = parseJsonFromOutput(stdout);
    if (p.a && p.b && p.c) break;
    await new Promise((r) => setTimeout(r, 100));
  }

  const setJs = `(() => {
    const set = (id,v) => { const el=document.getElementById(id); if(!el) return false; el.value=String(v); el.dispatchEvent(new Event("input",{bubbles:true})); el.dispatchEvent(new Event("change",{bubbles:true})); return true; };
    const remember = document.getElementById("rememberSettings");
    if (remember && !remember.checked) remember.click();
    const ok1=set("pitchSlider", ${Number(pitch)});
    const ok2=set("rateSlider", ${Number(speed)});
    const ok3=set("volumeSlider", ${Number(volume)});
    return {ok:ok1&&ok2&&ok3, now:{pitch:document.getElementById("pitchSlider")?.value||"", speed:document.getElementById("rateSlider")?.value||"", volume:document.getElementById("volumeSlider")?.value||""}};
  })()`;
  const { stdout: s } = await run("browseros-cli", ["eval", "--page", String(pageId), setJs]);
  return parseJsonFromOutput(s);
}

async function setSpeechmaText(pageId, text) {
  const b64 = Buffer.from(text, "utf8").toString("base64");
  const js = `(() => { const txt=atob(\`${b64}\`); const el=document.getElementById("textInput"); if(!el) return {ok:false}; el.value=txt; el.dispatchEvent(new Event("input",{bubbles:true})); el.dispatchEvent(new Event("change",{bubbles:true})); return {ok:true,len:txt.length}; })()`;
  const { stdout } = await run("browseros-cli", ["eval", "--page", String(pageId), js]);
  return parseJsonFromOutput(stdout);
}

async function getAudioState(pageId, phrase) {
  const safe = phrase.replace(/`/g, "");
  const js = `(() => {
    const normalize = (s)=>(s||"").toLowerCase().replace(/\\s+/g," ").trim();
    const p = normalize(\`${safe}\`);
    const oldRows = [...document.querySelectorAll(".audio-text")];
    const newRows = [...document.querySelectorAll("#generatedAudioContainer .generated-audio, .generated-audio-list .generated-audio")];
    const all=[...oldRows,...newRows];
    const total=all.length;
    const matches=all.filter(e=>normalize(e.textContent||"").includes(p)).length;
    const signature=all.map(e=>normalize((e.textContent||"").slice(0,220))).join("|").slice(0,3000);
    return {total,matches,signature};
  })()`;
  const { stdout } = await run("browseros-cli", ["eval", "--page", String(pageId), js]);
  return parseJsonFromOutput(stdout);
}

async function clickGenerate(pageId) {
  const js = "(() => { const b=[...document.querySelectorAll('button,[role=button],a,div,span')].find(n=>((n.textContent||'').trim().toLowerCase()==='generate audio')); if(!b) return {ok:false,reason:'no_button'}; b.click(); return {ok:true}; })()";
  const { stdout } = await run("browseros-cli", ["eval", "--page", String(pageId), js]);
  return parseJsonFromOutput(stdout);
}

async function clickDownloadByPhrase(pageId, phrase) {
  const js = `(() => {
    const normalize = (s) => (s || "").toLowerCase().replace(/\\s+/g, " ").trim();
    const phrase = normalize(\`${phrase.replace(/`/g, "")}\`);
    const els = [
      ...document.querySelectorAll('.audio-text'),
      ...document.querySelectorAll('#generatedAudioContainer .generated-audio, .generated-audio-list .generated-audio')
    ].filter(e => normalize(e.textContent || "").includes(phrase));
    if (!els.length) return { ok:false, reason:'no_match' };
    let el = els[0];
    for (let i=0;i<10 && el;i++) {
      const btn = el.querySelector?.('button.audio-control-btn.download-btn') || el.querySelector?.('button.download-btn') || el.querySelector?.('.download-btn');
      if (btn) { btn.click(); return { ok:true, level:i }; }
      el = el.parentElement;
    }
    return { ok:false, reason:'no_btn' };
  })()`;
  const { stdout } = await run("browseros-cli", ["eval", "--page", String(pageId), js]);
  return parseJsonFromOutput(stdout);
}

function latestSpeechmaDownload() {
  const downloads = path.join(os.homedir(), "Downloads");
  const files = fs.readdirSync(downloads)
    .filter((name) => /^speechma_audio_.*\.mp3$/i.test(name))
    .map((name) => ({ name, full: path.join(downloads, name), mtimeMs: fs.statSync(path.join(downloads, name)).mtimeMs }))
    .sort((a, b) => b.mtimeMs - a.mtimeMs);
  return files[0] || null;
}

async function ffprobeDuration(filePath) {
  const candidates = [
    path.join(REPO_ROOT, "tools", "ffmpeg", "ffmpeg-8.1.1-essentials_build", "bin", "ffprobe.exe"),
    "C:\\Users\\Saurabh\\Documents\\AutoVideoAgent\\tools\\ffmpeg\\ffmpeg-8.1.1-essentials_build\\bin\\ffprobe.exe",
    "ffprobe",
  ];
  const ffprobe = candidates.find((p) => p === "ffprobe" || fs.existsSync(p));
  const { stdout } = await run(ffprobe, ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filePath]);
  return Number(String(stdout || "0").trim());
}

async function speechmaRun(payload) {
  const workspace = payload.workspacePath;
  if (!workspace || !path.isAbsolute(workspace)) throw new Error("workspacePath must be an absolute path.");
  if (!fs.existsSync(workspace)) throw new Error(`workspacePath does not exist: ${workspace}`);

  const scriptPath = payload.scriptPath || path.join(workspace, "script", "script_v1.txt");
  const outInputPath = payload.inputPath || path.join(workspace, "voice", "speechma_input_v1.txt");
  const outVoicePath = payload.outputVoicePath || path.join(workspace, "voice", "voice_v1.mp3");
  const phraseFromPayload = payload.matchPhrase;
  const pitch = Number(payload.pitch ?? 0);
  const speed = Number(payload.speed ?? 25);
  const volume = Number(payload.volume ?? 200);
  const voiceLabel = String(payload.voiceLabel || "Ava");

  const pageId = await ensureFreshSpeechmaPage(payload.pageId);

  await run("powershell", [
    "-ExecutionPolicy", "Bypass",
    "-File", path.join(TOOL_ROOT, "prepare_speechma_input.ps1"),
    "-ScriptPath", scriptPath,
    "-OutPath", outInputPath,
  ]);

  const cleanText = fs.readFileSync(outInputPath, "utf8");
  const firstLine = cleanText.split(/\r?\n/).map((s) => s.trim()).find((s) => s.length > 0);
  const phraseRaw = phraseFromPayload || firstLine || "The smartest person you know";
  const phrase = phraseRaw.replace(/\s+/g, " ").trim().slice(0, 80);

  const setRes = await setSpeechmaText(pageId, cleanText);
  if (!setRes.ok) throw new Error("Failed to set textInput.");

  const voiceRes = await selectVoice(pageId, voiceLabel);
  if (!voiceRes.ok) throw new Error(`Voice select failed: ${JSON.stringify(voiceRes)}`);

  const fxRes = await applyEffects(pageId, pitch, speed, volume);
  if (!fxRes.ok) throw new Error(`Voice effects failed: ${JSON.stringify(fxRes)}`);

  const before = await getAudioState(pageId, phrase);
  const startedAt = Date.now();

  const genRes = await clickGenerate(pageId);
  if (!genRes.ok) throw new Error(`Generate click failed: ${JSON.stringify(genRes)}`);

  let detected = false;
  for (let i = 0; i < 300; i += 1) {
    await new Promise((r) => setTimeout(r, 1000));
    const now = await getAudioState(pageId, phrase);
    if (now.total > before.total || now.matches > before.matches || (now.total > 0 && now.signature && now.signature !== before.signature)) {
      detected = true;
      break;
    }
  }
  if (!detected) throw new Error("Timed out waiting for generated audio DOM update.");

  const dlRes = await clickDownloadByPhrase(pageId, phrase);
  if (!dlRes.ok) throw new Error(`Download click failed: ${JSON.stringify(dlRes)}`);

  // Switched to fixed wait-based download handling:
  // wait a bit for browser download completion, then move latest file.
  await new Promise((r) => setTimeout(r, 12000));
  let latest = latestSpeechmaDownload();
  if ((!latest || latest.mtimeMs < startedAt - 2000)) {
    // one short grace wait
    await new Promise((r) => setTimeout(r, 5000));
    latest = latestSpeechmaDownload();
  }
  if (!latest) throw new Error("No speechma_audio_*.mp3 found in Downloads.");
  if (latest.mtimeMs < startedAt - 2000) throw new Error(`Latest Speechma download appears stale: ${latest.name}`);

  fs.mkdirSync(path.dirname(outVoicePath), { recursive: true });
  fs.renameSync(latest.full, outVoicePath);
  const duration = await ffprobeDuration(outVoicePath);

  return {
    ok: true,
    pageId,
    outputVoicePath: outVoicePath,
    durationSeconds: duration,
    settings: { pitch, speed, volume, voiceLabel },
    matchPhraseUsed: phrase,
  };
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (d) => chunks.push(d));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (err) { reject(err); }
    });
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") return json(res, 200, { ok: true, service: "speechma-local-api" });
    if (req.method === "POST" && req.url === "/speechma/run") {
      const payload = await readJsonBody(req);
      const result = await speechmaRun(payload);
      return json(res, 200, result);
    }
    return json(res, 404, { ok: false, error: "Not found" });
  } catch (err) {
    return json(res, 500, { ok: false, error: err.message });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Speechma local API running at http://${HOST}:${PORT}`);
  console.log("POST /speechma/run");
});

// Regenerates docs/screenshots by RUNNING the real system:
//   * the docker-compose stack is built and started, a fault is injected through the simulator's control API,
//     and Playwright screenshots what Grafana and Alertmanager then show;
//   * the simulator, the collector and the 50-turbine performance test are run for real, and their combined
//     stdout/stderr is captured as it arrives and rendered into a terminal card.
// Nothing is typed, edited or reworded by hand. The command shown on each card is the command that ran. A
// long-running server (simulator, collector) is stopped after a few seconds, and the card title says so.
//
// Requires: Docker with Compose v2, the project's virtualenv (.venv, `pip install -e ".[dev]"`), and
// `cd scripts/capture && npm install`. Run from the repo root:  node scripts/capture/capture-screenshots.mjs
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "..", "..");
const OUT = path.join(ROOT, "docs", "screenshots");
const PY = path.join(ROOT, ".venv", "bin", "python");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stripAnsi = (s) => s.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "");

function findChromium() {
  for (const dir of [path.join(os.homedir(), "Library/Caches/ms-playwright"), path.join(os.homedir(), ".cache/ms-playwright")]) {
    if (!fs.existsSync(dir)) continue;
    for (const d of fs.readdirSync(dir).filter((x) => x.startsWith("chromium-")).sort().reverse()) {
      for (const rel of ["chrome-mac/Chromium.app/Contents/MacOS/Chromium", "chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium", "chrome-linux/chrome"]) {
        const p = path.join(dir, d, rel);
        if (fs.existsSync(p)) return p;
      }
    }
  }
  return undefined;
}

function run(cmd, cwd = ROOT) {
  return new Promise((resolve) => {
    const child = spawn("bash", ["-c", cmd], { cwd });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ out: stripAnsi(out).replace(/\s+$/, ""), code }));
  });
}

/** Starts a long-running command, lets it run for `seconds`, stops it and returns what it printed. */
function runFor(cmd, seconds, cwd = ROOT) {
  return new Promise((resolve) => {
    const child = spawn("bash", ["-c", cmd], { cwd, detached: true });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", () => resolve(stripAnsi(out).replace(/\s+$/, "")));
    setTimeout(() => { try { process.kill(-child.pid, "SIGINT"); } catch { /* done */ } }, seconds * 1000);
    setTimeout(() => { try { process.kill(-child.pid, "SIGKILL"); } catch { /* done */ } }, seconds * 1000 + 4000);
  });
}

const browser = await chromium.launch({ executablePath: findChromium() });

async function card(file, title, steps) {
  const page = await browser.newPage({ viewport: { width: 1040, height: 400 }, deviceScaleFactor: 2 });
  await page.goto("file://" + path.join(here, "terminal.html"));
  await page.evaluate(({ title, steps }) => {
    document.getElementById("title").textContent = title;
    document.getElementById("exit").remove();
    const body = document.getElementById("body");
    steps.forEach((s, i) => {
      const p = document.createElement("span"); p.className = "p"; p.textContent = "$ ";
      const c = document.createElement("span"); c.className = "c"; c.textContent = s.cmd;
      body.append(p, c, document.createTextNode("\n" + s.out + (i < steps.length - 1 ? "\n\n" : "")));
    });
  }, { title, steps });
  await page.locator("#win").screenshot({ path: path.join(OUT, file) });
  await page.close();
  console.log("wrote", file);
}

async function waitUntil(label, fn, seconds = 180) {
  for (let i = 0; i < seconds; i++) { try { if (await fn()) return; } catch { /* not yet */ } await sleep(1000); }
  throw new Error("timed out waiting for " + label);
}
const json = async (url) => (await fetch(url)).json();

fs.mkdirSync(OUT, { recursive: true });
for (const f of fs.readdirSync(OUT)) if (f.endsWith(".png") || f.endsWith(".txt")) fs.rmSync(path.join(OUT, f));

try {
  // ---- the compose stack: Grafana and Alertmanager ---------------------------------------------------
  spawnSync("docker", ["compose", "down", "-v", "--remove-orphans"], { cwd: ROOT });
  console.log("starting the compose stack (builds the simulator and collector images) ...");
  const up = spawnSync("docker", ["compose", "up", "-d", "--build"], { cwd: ROOT, encoding: "utf8" });
  if (up.status !== 0) throw new Error("docker compose up failed:\n" + up.stderr);
  await waitUntil("10 turbines up in Prometheus", async () => {
    const r = await json("http://localhost:9090/api/v1/query?query=" + encodeURIComponent("sum(windfarm_turbine_up)"));
    return Number(r.data.result[0]?.value[1]) >= 10;
  }, 240);
  await waitUntil("Grafana dashboard", async () => (await json("http://localhost:3000/api/search?type=dash-db")).length > 0, 120);
  const dash = (await json("http://localhost:3000/api/search?type=dash-db"))[0];
  const dashUrl = `http://localhost:3000${dash.url}?orgId=1&from=now-5m&to=now&refresh=5s`;
  await sleep(45000); // let the panels fill with a few minutes of real data

  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, deviceScaleFactor: 1.5 });
  await page.goto(dashUrl);
  await sleep(8000);
  await page.screenshot({ path: path.join(OUT, "grafana-dashboard-healthy.png") });
  console.log("wrote grafana-dashboard-healthy.png");

  const inj = await fetch("http://localhost:8080/turbines/2/faults", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "overspeed", duration_s: 300 }) });
  if (!inj.ok) throw new Error("fault injection failed: " + inj.status);
  await waitUntil("TurbineOverspeed firing in Alertmanager", async () => (await json("http://localhost:9093/api/v2/alerts")).some((a) => a.labels.alertname === "TurbineOverspeed"), 240);
  await sleep(25000);
  await page.goto(dashUrl);
  await sleep(8000);
  await page.screenshot({ path: path.join(OUT, "grafana-dashboard-overspeed-fault.png") });
  console.log("wrote grafana-dashboard-overspeed-fault.png");

  const am = await browser.newPage({ viewport: { width: 1400, height: 800 }, deviceScaleFactor: 2 });
  await am.goto("http://localhost:9093/#/alerts");
  await sleep(4000);
  const info = am.getByText("Info", { exact: true }).first();
  if (await info.count()) await info.click().catch(() => {});
  await sleep(1500);
  await am.screenshot({ path: path.join(OUT, "alertmanager-turbineoverspeed.png") });
  console.log("wrote alertmanager-turbineoverspeed.png");
} finally {
  spawnSync("docker", ["compose", "down", "-v", "--remove-orphans"], { cwd: ROOT });
}

// ---- the Python pieces run directly -----------------------------------------------------------------
const simCmd = ".venv/bin/python -m windfarm.simulator.cli --turbines 5 --modbus-port 5020 --control-port 8080";
const simOut = await runFor(simCmd, 4);
await card("terminal-simulator-startup.png", "simulator CLI (stopped after 4 seconds)", [{ cmd: simCmd.replace(".venv/bin/python", "python"), out: simOut }]);

const sim = spawn("bash", ["-c", simCmd], { cwd: ROOT, detached: true, stdio: "ignore" });
await sleep(3000);
const colCmd = ".venv/bin/python -m windfarm.collector.cli --turbines 5 --modbus-port 5020 --metrics-port 9200";
const colPromise = runFor(colCmd, 14);
await sleep(9000);
const metrics = await run("curl -s http://localhost:9200/metrics | grep windfarm_turbine_up");
const colOut = await colPromise;
try { process.kill(-sim.pid, "SIGKILL"); } catch { /* gone */ }
await card("terminal-collector-metrics.png", "collector CLI polling the simulator (stopped after 14 seconds)", [
  { cmd: colCmd.replace(".venv/bin/python", "python"), out: colOut },
  { cmd: "curl -s http://localhost:9200/metrics | grep windfarm_turbine_up", out: metrics.out },
]);

console.log("running the 50-turbine performance test (about two minutes) ...");
const perfCmd = ".venv/bin/python scripts/perf_test.py --turbines 50 --poll-duration 30 --scrape-duration 25";
const perf = await run(perfCmd);
if (perf.code !== 0) throw new Error("perf_test.py exited " + perf.code + "\n" + perf.out);
await card("terminal-perf-test.png", "50-turbine performance test", [{ cmd: perfCmd.replace(".venv/bin/python", "python"), out: perf.out }]);
await browser.close();

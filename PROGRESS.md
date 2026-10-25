# Progress

## Vision

A simulated wind farm SCADA environment, built for learning and portfolio
purposes (not real OT equipment):

- Python turbine simulators expose Modbus TCP, one gateway process standing
  in for N turbines addressed by Modbus unit id.
- A read-only collector polls the turbines with per-request timeouts, retry
  with backoff, and stale-data detection, then exports telemetry to
  Prometheus.
- Grafana dashboards, Alertmanager fault alerts with runbooks, and Loki logs
  run in docker-compose.
- A 50-turbine performance test measures real poll latency and Prometheus
  load on the machine it ran on.
- An IEC 62443-informed design note explains the zones/conduits model and
  why the collector is read-only.

## Architecture

```
          Modbus TCP (read-only: read_holding_registers only)
┌────────────────────┐        unit id 1..N        ┌──────────────────────┐
│  Turbine simulator  │ ◄───────────────────────── │  Async collector     │
│  (pymodbus server,  │                             │  - per-turbine poll  │
│   one gateway,      │                             │    loop, own timeout │
│   N turbine states) │                             │  - retry w/ backoff  │
│                      │                             │  - stale-data detect │
│  + aiohttp control   │                             │  - Prometheus export │
│    API (fault inj.)  │                             └──────────┬───────────┘
└──────────┬───────────┘                                        │ /metrics
           │ HTTP (test harness only, not a real OT interface)   ▼
           │                                              ┌─────────────┐
           ▼                                              │ Prometheus  │
   CLI / scale-test script                                └──────┬──────┘
                                                                   │
                                      ┌────────────────────────────┼─────────────┐
                                      ▼                            ▼             ▼
                                 ┌─────────┐              ┌──────────────┐ ┌─────────┐
                                 │ Grafana │              │ Alertmanager │ │  Loki   │
                                 │ (dash   │              │ (3 rules +   │ │ (via    │
                                 │  as     │              │  runbooks)   │ │Promtail)│
                                 │  code)  │              └──────────────┘ └─────────┘
                                 └─────────┘
```

Shared code lives in `windfarm.common` (the Modbus register map and status
codes) so the simulator and collector can never drift out of sync on wire
format.

Fault injection (overspeed, overheating, comm loss) happens over a small
HTTP control API on the simulator -- deliberately separate from Modbus,
since a real SCADA collector could never write a fault into a real turbine.
Comm-loss is simulated by having the simulator's Modbus datastore raise
`NoSuchSlaveException` for the affected turbine with `ignore_missing_slaves`
enabled on the server, which makes pymodbus send no response at all: the
collector experiences a genuine client-side timeout, not a fabricated error.

## Build plan (4 sessions)

### Phase 1 — Foundation: simulator + collector core — DONE
- [x] Repo scaffold, `pyproject.toml`, venv, `.gitignore`.
- [x] `windfarm.common`: Modbus register map + status/fault enums shared by
      both sides.
- [x] Turbine physics simulator (`windfarm.simulator`): wind-driven power
      curve, gearbox thermal model, fault injection (overspeed, overheating,
      comm loss) with optional auto-expiry.
- [x] Modbus TCP server wiring: one gateway, turbines addressed by unit id,
      live register updates from a background physics tick loop.
- [x] HTTP control API (aiohttp) for fault injection and turbine status.
- [x] Async, read-only collector (`windfarm.collector`): per-turbine poll
      loop with its own timeout, collector-level retry with exponential
      backoff, stale-data detection (debounced `up` gauge plus a
      continuously-updated `last_seen_age_seconds` gauge), Prometheus
      metrics export.
- [x] Unit tests for registers, turbine physics, fault injection, control
      API, staleness logic, metrics, and the poller (against a fake Modbus
      client).
- [x] Integration test: a real pymodbus server polled by a real collector
      poller, including a genuine timeout from an injected comm-loss fault.
- [x] Manual end-to-end smoke test: both CLIs run as real processes; an
      overspeed fault injected via the control API is visible in the
      collector's exported Prometheus metrics within one poll cycle.
- [x] 51 tests passing, no flakiness across repeated runs.

### Phase 2 — Observability stack (docker-compose) — DONE
- [x] Dockerfiles for the simulator and collector (`docker/simulator.Dockerfile`,
      `docker/collector.Dockerfile`; plain `python:3.12-slim` + `pip install .`,
      no compiled deps).
- [x] `docker-compose.yml` wiring simulator + collector + Prometheus +
      Grafana + Alertmanager + Loki + Promtail, defaulted to 10 turbines
      for fast local iteration.
- [x] Prometheus scrape config targeting the collector's `/metrics`
      (`docker/prometheus/prometheus.yml`).
- [x] Grafana dashboard provisioned as code: datasource provisioning
      (Prometheus + Loki) and one dashboard JSON
      (`docker/grafana/provisioning/dashboards/json/windfarm-overview.json`)
      with farm-level stats, per-turbine rotor speed/gearbox temp/wind
      speed/staleness timeseries, and a status-code state timeline.
      Nothing clicked together by hand.
- [x] Alertmanager: 3 rules in `docker/prometheus/windfarm.rules.yml`
      (`TurbineOverspeed`, `TurbineGearboxOverheat`, `TurbineSilent`),
      each annotated with a `runbook_url`.
- [x] One runbook markdown file per alert under `docs/runbooks/`
      (`turbine-overspeed.md`, `turbine-gearbox-overheat.md`,
      `turbine-silent.md`), each with what the alert means on a real
      site and concrete triage steps using this repo's control API.
- [x] Verified against a real running stack (`docker compose up -d --build`,
      7 containers): collector metrics scraped by Prometheus, dashboard
      auto-provisioned in Grafana, Loki receiving container logs via
      Promtail. Injected overspeed, overheating, and comm-loss faults in
      turn and watched all three alerts move from Prometheus `pending` to
      `firing` to Alertmanager `active`, then clear on fault removal.
- [x] `scripts/compose_smoke_test.sh`: automates the above (build, wait for
      a healthy Prometheus target and provisioned dashboard, inject an
      overspeed fault, poll Alertmanager until it fires, clear the fault,
      tear down). Runs clean -- no containers left behind on success or
      failure (`trap cleanup EXIT`). This will be the Phase 3 CI gate.

### Phase 3 — Performance test, OT-security note, CI — DONE
- [x] `scripts/perf_test.py`: starts a real simulator subprocess and drives
      real `TurbinePoller` instances against it in-process to measure exact
      per-poll latency (no histogram-bucket estimation), then starts a real
      collector subprocess and a temporary, real `prom/prometheus` container
      to measure scrape payload size, scrape duration, and PromQL query
      latency. Cleans up its subprocess and container unconditionally.
- [x] `docs/performance.md` with the real measured numbers from a 50-turbine
      run (7,350 polls, 0 failures, p99 5.8ms poll latency, ~100KB scrape
      payload, ~31ms Prometheus scrape duration), explicit that it's a
      one-machine measurement, not a production benchmark. Raw JSON kept at
      `docs/performance-50-turbines.json`.
- [x] `docs/ot-security.md`: IEC 62443 zones/conduits framing (process/OT
      zone vs. monitoring/IT zone, the Modbus read-only conduit, the
      test-harness-only control API as a deliberate, isolated zone
      violation), why the collector is strictly read-only, IT/OT separation
      in the compose topology, and an explicit list of what a real
      deployment would still need beyond this project.
- [x] CI pipeline (`.github/workflows/ci.yml`): a `test` job running
      `pytest -v` on Python 3.12, then a `compose-smoke-test` job running
      `scripts/compose_smoke_test.sh` as the integration gate, with
      container logs dumped on failure.
- [x] 6 new unit tests for the perf script's percentile math
      (`tests/test_perf_test.py`); full suite now 57 tests passing.
- [x] Verified `scripts/compose_smoke_test.sh` end to end again on a clean
      build: builds, waits for a healthy Prometheus target and provisioned
      dashboard, injects an overspeed fault, polls Alertmanager until it
      fires, clears the fault, tears down with no containers left behind.

### Phase 4 — Previews, polish, final docs
- [ ] Playwright captures of the Grafana dashboard: healthy farm, then with
      an injected overspeed fault.
- [ ] Playwright capture of the Alertmanager page showing a firing alert.
- [ ] Terminal captures of the simulator, the collector, and the scale test,
      from real runs (no hand-edited output).
- [ ] At least 4-5 verified screenshots in `docs/screenshots/`, embedded in
      a Preview section near the top of `README.md`.
- [ ] Final README pass: quick start, preview, status, license.
- [ ] `DAILY_REPORT.md`.
- [ ] `STATUS: COMPLETE` once everything above is true, tested, and
      documented.

## Resume point

**Start of session 4: Phase 4** -- previews, polish, final docs. This is
the last session; everything must end COMPLETE.

1. Capture the Grafana "Windfarm Overview" dashboard with Playwright:
   once showing a healthy farm, once with an injected overspeed fault
   visible on the per-turbine panels (`docker compose up -d --build`,
   wait for provisioning the same way `scripts/compose_smoke_test.sh`
   does, inject via the control API, screenshot, clear the fault, tear
   down).
2. Capture the Alertmanager UI (`http://localhost:9093`) showing the
   `TurbineOverspeed` alert `active`.
3. Capture terminal output from real runs (not hand-typed) for: the
   simulator CLI starting up, the collector CLI starting up and polling,
   and `scripts/perf_test.py` producing its JSON summary -- render each
   into a dark terminal-style HTML template and screenshot that, per the
   project rules (exact command in the prompt line, no edited output,
   `... (output truncated)` for anything abridged).
4. Look at every screenshot before embedding it; re-capture anything
   blank, broken, or showing an error overlay.
5. Add a "Preview" section near the top of `README.md` embedding all of
   them (at least 4-5, more if there are genuinely distinct views worth
   showing), then do a final README pass: quick start, preview, a short
   factual Status section near the bottom, license. No build-diary
   language ("tonight", "session N", etc.) -- that belongs in this file.
6. Write `DAILY_REPORT.md` summarizing all 4 sessions: what was built,
   test results, known limitations (see `docs/performance.md`'s
   Limitations section and `docs/ot-security.md`'s closing section for
   source material), future ideas.
7. Set `STATUS: COMPLETE` below once the full test suite is green, the
   compose smoke test passes, README is final with Preview section in
   place, and `DAILY_REPORT.md` exists.

STATUS: IN_PROGRESS

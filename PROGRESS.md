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

### Phase 2 — Observability stack (docker-compose)
- [ ] Dockerfiles for the simulator and collector.
- [ ] `docker-compose.yml` wiring simulator + collector + Prometheus +
      Grafana + Alertmanager + Loki + Promtail.
- [ ] Prometheus scrape config targeting the collector's `/metrics`.
- [ ] Grafana dashboard provisioned as code (datasource + dashboard JSON via
      provisioning, not clicked together by hand).
- [ ] Alertmanager: 3 rules (overspeed, high gearbox temperature, turbine
      silent), each annotated with a runbook link.
- [ ] One runbook markdown file per alert under `docs/runbooks/`.
- [ ] Verify against a running stack: metrics flow end to end, and each
      alert can be made to fire by injecting the matching fault.

### Phase 3 — Performance test, OT-security note, CI
- [ ] 50-turbine performance test script: measures poll latency percentiles
      and Prometheus scrape/query load.
- [ ] `docs/performance.md` with the real measured numbers from that run,
      stating plainly it was measured on one Mac, not a production
      benchmark.
- [ ] `docs/ot-security.md`: IEC 62443 zones/conduits framing, why the
      collector is strictly read-only, IT/OT separation -- written as
      design intent for a simulation, not a certification claim.
- [ ] CI pipeline: pytest, plus a docker-compose smoke test that injects a
      fault and polls the Alertmanager API until the matching alert fires.

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

**Start of session 2: Phase 2, item 1** -- write Dockerfiles for the
simulator and collector (both are plain Python/pip installs, no compiled
deps, so this should be quick), then build `docker-compose.yml` around the
already-pulled images (`prom/prometheus`, `prom/alertmanager`,
`grafana/grafana`, `grafana/loki`, `grafana/promtail`). Default the compose
stack to a modest turbine count (e.g. 10) for fast local iteration; the
50-turbine run is Phase 3's dedicated performance test, not the default
compose setup.

STATUS: IN_PROGRESS

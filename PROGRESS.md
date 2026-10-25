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

**Start of session 3: Phase 3, item 1** -- write the 50-turbine
performance test script. Use `scripts/compose_smoke_test.sh` and the
compose stack built in Phase 2 as the base: either scale the simulator's
`--turbines` flag and the collector's target list to 50 inside a
dedicated performance-test compose override, or drive it directly with
the Python CLIs outside Docker (simpler, and avoids attributing Docker's
own overhead to the numbers). Record real measured poll-latency
percentiles and Prometheus load into `docs/performance.md`, explicit that
it's a one-machine measurement, not a benchmark claim. Then
`docs/ot-security.md` (IEC 62443 zones/conduits framing, already partly
written as prose in the Architecture section above -- formalize it into
its own doc). Finish with a CI workflow (pytest, plus
`scripts/compose_smoke_test.sh` as the integration gate).

STATUS: IN_PROGRESS

# Daily Report

Final summary of the windfarm-scada-observability build, covering all four
build sessions. Phase-by-phase detail and exact checklists live in
[PROGRESS.md](PROGRESS.md); this is the rollup.

## What was built

A simulated wind farm SCADA environment, built to demonstrate industrial
telemetry/observability patterns end to end, not to control real OT
equipment:

1. **Turbine simulator** (`windfarm.simulator`) -- a wind-driven power
   curve and gearbox thermal model per turbine, served over real Modbus
   TCP (one `pymodbus` gateway process, turbines addressed by unit id),
   plus a small HTTP control API for injecting faults (overspeed,
   overheating, comm loss) with optional auto-expiry.
2. **Read-only collector** (`windfarm.collector`) -- an async poller that
   only ever issues `read_holding_registers`, with one poll loop per
   turbine, its own per-request timeout, exponential-backoff retries, and
   stale-data detection via a continuously-updated
   `last_seen_age_seconds` gauge independent of the last reported value.
   Exports everything as Prometheus metrics.
3. **Shared register map** (`windfarm.common`) -- the single source of
   truth for the Modbus wire format and status/fault codes, imported by
   both the simulator and the collector so they cannot drift apart.
4. **Observability stack** (`docker-compose.yml`, `docker/`) -- Prometheus
   scraping the collector, three alert rules (`TurbineOverspeed`,
   `TurbineGearboxOverheat`, `TurbineSilent`) each linked to a runbook
   under `docs/runbooks/`, Alertmanager, a Grafana dashboard provisioned
   entirely as code (datasources, dashboard JSON, nothing clicked
   together by hand), and Loki/Promtail for container logs.
5. **`scripts/compose_smoke_test.sh`** -- brings the full stack up for
   real, waits for a healthy Prometheus target and a provisioned
   dashboard, injects a real overspeed fault, polls Alertmanager until it
   fires, clears the fault, and tears everything down unconditionally.
   This is also the integration gate in CI.
6. **Performance measurement** (`scripts/perf_test.py`,
   [docs/performance.md](docs/performance.md)) -- drives the collector's
   real poll code against a real simulator subprocess to measure exact
   per-poll latency, and points a temporary, real `prom/prometheus`
   container at a real collector process to measure scrape payload size,
   scrape duration, and PromQL query latency. The checked-in 50-turbine
   run: 7,350 polls, 0 failures, p99 5.8ms poll latency, ~100KB scrape
   payload, ~31ms Prometheus scrape duration.
7. **OT security design notes** ([docs/ot-security.md](docs/ot-security.md))
   -- frames the simulator/collector split using IEC 62443 zones and
   conduits, explains why the collector's Modbus path is strictly
   read-only, and is explicit about what a real deployment would still
   need beyond this project (network-layer conduit enforcement,
   authentication on the Modbus path, TLS on monitoring-zone links,
   OT patch management, an incident-response plan).
8. **CI** (`.github/workflows/ci.yml`) -- a `test` job running the unit
   suite on Python 3.12, then a `compose-smoke-test` job running the
   same end-to-end smoke test described above, with container logs
   dumped on failure.
9. **Preview assets** (`docs/screenshots/`) -- six screenshots captured
   with Playwright/Chromium against a real running stack and real CLI
   runs: the Grafana dashboard healthy and with a live overspeed fault,
   the Alertmanager UI with a firing alert and its runbook link, and
   terminal captures of the simulator starting, the collector polling
   with live `/metrics` output, and a real `perf_test.py` run.

## Test results

- Full unit test suite: **57 passed**, no flakiness across repeated runs
  (`pytest -q`).
- `scripts/compose_smoke_test.sh`: verified against a clean build --
  stack comes up, Prometheus target goes healthy, Grafana dashboard
  provisions, an injected overspeed fault reaches `firing` in
  Alertmanager, the fault clears, and the stack tears down with no
  containers left behind.
- Manual verification during Preview capture: `docker compose up -d
  --build` brought up all 7 containers; injecting overspeed on turbine 2
  via the control API was visible in the Grafana dashboard (rotor-speed
  spike, red status band, fault counter) and in Alertmanager (alert
  active with description, summary, and runbook link) within the
  expected poll/evaluation window; the fault was cleared and the stack
  torn down afterward.

## Known limitations

- `docs/performance.md`'s numbers are from one run on one machine (Apple
  M2 Max, Docker Desktop, CPython 3.14), not a statistically replicated
  benchmark. The "turbines" in that test are one `pymodbus` process
  multiplexing unit ids, not independent physical gateways on a real
  network, and Docker Desktop's `host.docker.internal` path removes a
  network hop a real deployment would have.
- The project is a simulation end to end: there is no real Modbus
  hardware, no RTU-to-TCP bridge, and no field network latency or packet
  loss modeled anywhere.
- The simulator's HTTP control API is a deliberate, isolated zone
  violation that only exists for this test harness -- a real SCADA
  collector could never write a fault into a real turbine, and
  `docs/ot-security.md` is explicit about that.
- Nothing here implements the network-layer conduit enforcement,
  Modbus-path authentication, TLS on monitoring-zone links, OT patch
  management, or incident-response planning that `docs/ot-security.md`
  lists as required beyond this project for a real site.
- Grafana and the control API run with simple default credentials
  (`admin`/`admin`, no auth) suitable only for local/demo use, not
  production.

## Ideas for more

- A second simulated farm (or a second collector instance) to exercise
  multi-site aggregation in Grafana and cross-farm alert routing in
  Alertmanager.
- A chaos-style test that randomly injects and clears faults across many
  turbines concurrently to probe the collector's retry/backoff behavior
  under sustained partial failure, beyond the single-fault smoke test.
- Export collector internals (retry counts, backoff durations) as their
  own Prometheus metrics for direct dashboarding, not just inferred from
  `last_seen_age_seconds`.
- An authenticated reverse proxy in front of Grafana/Alertmanager/the
  control API, as a step toward the "what a real deployment would need"
  list in `docs/ot-security.md`.
- A Helm chart or Kubernetes manifests as an alternative to
  `docker-compose.yml` for anyone wanting to run this on a cluster.

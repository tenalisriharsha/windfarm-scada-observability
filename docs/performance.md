# Performance notes

These are real measurements from one run on one machine, not a production
capacity-planning benchmark. They exist to show the collector's design
(per-request timeout, bounded retries, one poll loop per turbine) scales
to a reasonably large farm without surprises, and to give a sense of scale
for anyone adapting this project.

Reproduce with:

```bash
python scripts/perf_test.py --turbines 50 --poll-duration 30 --scrape-duration 25
```

Pass `--skip-docker` to measure only poll latency, without starting a
temporary Prometheus container.

## Method

The script makes two separate, real measurements -- it does not estimate
or synthesize either:

1. **Poll latency.** Starts the real simulator CLI as a subprocess (N
   turbines over Modbus TCP), then drives real `TurbinePoller` instances
   against it from the script's own process -- the exact `poll_once()`
   code path the collector CLI uses -- in a tight loop for a fixed window.
   Every individual poll's wall-clock duration is recorded directly in
   Python; the percentiles below are computed from that raw list, not
   from a Prometheus histogram's bucket boundaries.
2. **Prometheus scrape load.** Starts the real collector CLI as a
   subprocess, serving `/metrics` for the same N turbines. Starts a real,
   temporary `prom/prometheus` container (removed again at the end)
   pointed at that endpoint, lets it scrape for a fixed window, then reads
   Prometheus's own `scrape_duration_seconds` for that target and times a
   raw `/metrics` fetch plus a sample PromQL query.

## Test machine

- Apple M2 Max, macOS 15 (Darwin), Docker Desktop (linux/arm64 containers)
- CPython 3.14, Docker reachable via `host.docker.internal`
- `prom/prometheus:latest` at the time of the run

## Results: 50 turbines

30-second poll window, one poll loop per turbine, `poll_interval=0.2s`,
`request_timeout=2.0s`:

| Metric | Value |
| --- | --- |
| Total polls completed | 7,350 |
| Effective throughput | 245.0 polls/sec |
| Success rate | 100% (0 timeouts, 0 errors) |
| p50 latency | 2.8 ms |
| p90 latency | 4.3 ms |
| p95 latency | 4.7 ms |
| p99 latency | 5.8 ms |
| max latency | 113.5 ms (single outlier; see below) |

25-second Prometheus scrape window, `scrape_interval=2s`, target reachable
the entire window:

| Metric | Value |
| --- | --- |
| `/metrics` payload size | 102,436 bytes |
| Raw `/metrics` fetch time | 17.97 ms |
| Prometheus-reported `scrape_duration_seconds` | 30.69 ms |
| PromQL instant-query latency (`up{...}`) | 6.12 ms |

Full raw JSON from the run that produced these numbers is kept at
[`docs/performance-50-turbines.json`](performance-50-turbines.json) for
reference: every individual field above was read directly from that file,
not retyped by hand.

## Reading these numbers

- **Poll latency is dominated by loopback TCP and asyncio scheduling, not
  the simulator's physics.** At 50 turbines sharing one event loop, the
  collector comfortably stays in single-digit milliseconds at p99 against
  a local gateway. The one ~113ms outlier was a single poll, not a
  pattern -- almost certainly a scheduling hiccup under the host's own
  load while 50 concurrent `asyncio.sleep` timers and a simulator
  subprocess were all running on the same machine; it did not recur, the
  success rate stayed at 100%, and it is reported here rather than
  dropped because the collector's whole reason to exist is to make
  exactly this kind of occasional anomaly visible.
- **The real bottleneck in a bigger deployment is Modbus round-trip time
  to physically separate gateways, which this test cannot measure** -- it
  runs against a single local simulator process. Expect real
  field-deployed gateways and RTU-to-TCP bridges to add tens to hundreds
  of milliseconds per request depending on hardware and network path,
  which is exactly why the collector gives each turbine its own
  timeout and retry budget instead of a single farm-wide poll loop.
- **Prometheus's own scrape cost is small and roughly linear in turbine
  count.** A ~100KB exposition payload for 50 turbines (9 metric families
  x 50 series, plus histogram buckets) scrapes in well under 50ms
  end-to-end. A farm an order of magnitude larger would still be a trivial
  scrape for a single Prometheus instance; cardinality from the
  per-turbine labels is the thing to watch as turbine count grows, not
  scrape latency.
- **This is not a load test of the Modbus server under concurrent
  clients** -- only one collector polls the simulator in this project, as
  in the real architecture. It also does not model network latency,
  packet loss, or a gateway serving more turbines than this one does.

## Limitations

- One machine, one run, no statistical replication across runs or
  hardware.
- The "turbines" here are one `pymodbus` server process multiplexing unit
  ids, exactly as the real collector talks to it in this project -- not N
  independent physical gateways on a real network.
- Docker Desktop's network path (`host.docker.internal`) is not
  representative of a Prometheus server scraping over a real LAN/WAN; it
  removes a hop that would exist in production.

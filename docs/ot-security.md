# OT security design notes

This project simulates a SCADA-style telemetry pipeline for a wind farm.
It is a learning/portfolio project, not a certified OT deployment, and
nothing here is a compliance claim. The goal is to show the *design
intent* behind a few IEC 62443-informed decisions that a real industrial
monitoring system would need to make, and why they were made the way
they were in this codebase.

## Why this matters even in a simulation

Operational technology (turbines, PLCs, RTUs, gateways) differs from IT
in one load-bearing way: availability and physical safety outrank
confidentiality. A monitoring system that is clever but occasionally
writes something to a turbine, or that takes a turbine's control path
down trying to poll it, is worse than no monitoring system at all. Every
design decision below follows from treating that as a hard constraint,
not a nice-to-have.

## Zones and conduits

IEC 62443 frames a system as **zones** (groups of assets that share a
security requirement) connected by **conduits** (the communication paths
between them, which carry the controls). Mapped onto this project:

```
┌─────────────────────────┐        Modbus TCP conduit        ┌───────────────────────────┐
│   Zone: Process/OT       │  (read_holding_registers only)   │   Zone: Monitoring/IT      │
│                           │ ────────────────────────────────▶ │                           │
│  Turbine simulator        │                                    │  Collector                │
│  (windfarm.simulator)     │                                    │  (windfarm.collector)     │
│                           │ ◀──────────────────────────────── │                           │
│                           │        register values only        │                           │
└───────────┬───────────────┘                                    └──────────────┬─────────────┘
            │ HTTP conduit (test-harness only,                                     │ /metrics conduit
            │ not a production interface)                                         ▼
            ▼                                                            Prometheus / Grafana /
    Fault-injection control API                                          Alertmanager / Loki
    (windfarm.simulator.control_api)                                     (Zone: Monitoring/IT)
```

- **Process/OT zone**: the turbine simulator. In a real deployment this
  is the turbine's control unit and the local gateway that exposes its
  registers -- the zone with the physical safety requirement.
- **Monitoring/IT zone**: the collector and everything downstream of it
  (Prometheus, Alertmanager, Grafana, Loki). This zone's job is to
  observe the process zone, never to act on it.
- **The Modbus TCP conduit** is the only path from the monitoring zone
  back into the process zone, and it is restricted at the application
  layer to one function code: `read_holding_registers`. The collector
  code never calls a write function (`write_register`,
  `write_coil`, etc.) -- there is no code path in `windfarm.collector`
  that could send one even if misconfigured, because the poller only
  ever constructs read requests.
- **The HTTP control API** is a deliberate zone violation that exists
  *only* for this project's own test harness -- it lets automated tests
  and the smoke-test script inject and clear faults without touching
  Modbus. It is clearly out of band from the telemetry conduit, is never
  used by the collector, and would not exist in a real deployment: no
  real SCADA collector has (or should have) a side channel to make a
  turbine misbehave on demand.

## Why the collector is strictly read-only

A monitoring system's entire value proposition is observing the process
without becoming part of its control loop. Concretely, in this codebase:

- `windfarm.collector.poller.TurbinePoller.poll_once` issues exactly one
  kind of Modbus request: `client.read_holding_registers(...)`. There is
  no write path anywhere in the collector package.
- The shared register map (`windfarm.common.registers`) is consumed by
  both sides, but the collector only ever calls `decode_reading`, never
  anything that would produce a write payload.
- Faults are injected through the simulator's own HTTP control API
  (`windfarm.simulator.control_api`), which exists purely as a test
  harness for *this project* and is architecturally separate from the
  Modbus conduit. On a real turbine there is no equivalent: nothing a
  monitoring system touches should be able to put a turbine into an
  overspeed or overheat state. That capability lives in this repo only
  so its own tests and demos can exercise the alerting pipeline, and the
  separation is the point being demonstrated.

This read-only boundary is also why a comm-loss fault produces a genuine
client-side timeout (see `windfarm.simulator.modbus_server`'s use of
`NoSuchSlaveException` with `ignore_missing_slaves`) rather than a
fabricated error response: the collector experiences exactly what a real
collector would experience when a gateway or network path drops, with no
special-cased "test mode" behavior that could mask a real failure mode in
production.

## IT/OT separation in the stack

- The process zone (simulator) and monitoring zone (collector,
  Prometheus, Alertmanager, Grafana, Loki) are separate services even in
  the local `docker-compose.yml` topology, each with its own container
  and network identity -- not because Compose requires it, but so the
  zone boundary drawn above is visible in the deployment, not just in
  the code.
- The collector initiates every connection to the simulator; nothing in
  the process zone ever calls back into the monitoring zone. Information
  flows out of the OT zone (telemetry) and never flows a command back in
  through the telemetry path.
- Alerting is designed around *reachability*, not just reported values:
  `windfarm_turbine_up` and `windfarm_turbine_last_seen_age_seconds` are
  independent of whatever the turbine last reported, so a turbine that
  goes silent (comms failure, gateway down, turbine powered off) is
  caught even though it can no longer self-report. See the
  `TurbineSilent` alert and its [runbook](runbooks/turbine-silent.md) --
  this is the alert that would catch a *failure of the monitoring path
  itself*, which is the first thing to lose in a real incident and the
  easiest thing for a naive dashboard to silently miss.

## What a real deployment would need beyond this project

This project demonstrates the application-layer read-only boundary and
the zones/conduits framing in code. A real site would additionally need,
at minimum: network-layer enforcement of the conduit (a firewall or
data diode between zones, not just "the client code happens not to send
writes"), authentication on the Modbus conduit or a protocol gateway that
adds it (plain Modbus TCP has none), TLS or an equivalent on every
monitoring-zone link that leaves a trusted network, patch and
vulnerability management for the OT-zone devices themselves, and a
documented incident-response plan for the process zone that assumes the
monitoring zone can be compromised without that compromise reaching the
turbines. None of that is simulated here; it's listed so the boundary
this project draws isn't mistaken for a complete security posture.

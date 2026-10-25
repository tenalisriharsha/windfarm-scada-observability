# Runbook: TurbineSilent

## Alert

Fires when `windfarm_turbine_up == 0` for at least 15 seconds, meaning the
collector has exhausted its retries (default: 3 retries with exponential
backoff) and still cannot get a successful Modbus read from the turbine.

This is deliberately a *reachability* alert, not a *data* alert: it fires
on silence, not on a reported fault code, so a turbine that has gone dark
is caught even though it can no longer report its own status.

## What this means in a real wind farm

This almost always means a communications failure, not a turbine failure:
a network link, a gateway, or the turbine's control unit has stopped
responding. The turbine itself may be running fine and simply unmonitored,
which is its own risk (faults developing with nobody watching).

## Triage steps

1. Open the Grafana "Windfarm Overview" dashboard and check the **Seconds
   since last successful poll** panel for the affected `turbine_id`. A
   value that keeps climbing (rather than resetting) confirms the
   collector genuinely has no fresh data, as opposed to one delayed poll.
2. Check the collector's own logs/metrics (`windfarm_collector_poll_attempts_total`
   with `outcome="timeout"` or `outcome="error"`) to see whether this
   turbine is timing out or erroring outright.
3. In this simulation, a comms-loss fault is injected the same way as
   other faults, and the turbine's Modbus server stops responding
   entirely for that unit id until the fault is cleared or expires:
   ```bash
   curl http://localhost:8080/turbines/<id>
   curl -X DELETE http://localhost:8080/turbines/<id>/faults
   ```
4. On a real site, this is where you would check the physical network
   path to the turbine (switch, fiber run, gateway device) before
   assuming anything about the turbine's mechanical state -- you simply
   don't know it yet.

## Resolution

The alert clears automatically once the collector completes a successful
poll of the turbine (`windfarm_turbine_up` returns to `1`).

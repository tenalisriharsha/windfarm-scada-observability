# Runbook: TurbineOverspeed

## Alert

Fires when `windfarm_turbine_status_code == 2` (`FAULT_OVERSPEED`) for at
least 10 seconds. In the simulation this means the turbine's rotor is
spinning at roughly 1.6x its rated rpm and its power output register is
reporting roughly 1.3x rated power.

## What this means in a real wind farm

An overspeed condition usually points to a pitch or brake control failure:
the turbine is no longer regulating rotor speed against wind speed. Left
unaddressed, this risks mechanical failure of the rotor, gearbox, or
generator, and is one of the fastest-developing fault modes a SCADA system
monitors for.

## Triage steps

1. Open the Grafana "Windfarm Overview" dashboard and check the **Rotor
   speed (rpm)** and **Turbine status code** panels for the affected
   `turbine_id`. Confirm the spike is sustained, not a single noisy sample.
2. Check whether other turbines are also overspeeding. A single turbine
   points to a local control fault; several at once points to a shared
   cause (e.g. a sudden wind gust across the whole site).
3. In this simulation, faults are injected and cleared through the
   turbine's control API:
   ```bash
   curl http://localhost:8080/turbines/<id>
   curl -X DELETE http://localhost:8080/turbines/<id>/faults
   ```
4. On a real site, this is where you would dispatch a SCADA operator to
   command an emergency pitch-to-feather or initiate a controlled shutdown
   of the affected turbine, then schedule inspection of the pitch/brake
   system before returning it to service.

## Resolution

The alert clears automatically once `status_code` returns to `0` (`OK`)
or `1` (`WARNING`) for a full evaluation interval.

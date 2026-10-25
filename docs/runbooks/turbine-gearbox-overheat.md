# Runbook: TurbineGearboxOverheat

## Alert

Fires when `windfarm_turbine_status_code == 3` (`FAULT_OVERHEAT`) for at
least 10 seconds. In the simulation this means the turbine's gearbox
temperature register is reporting somewhere in the 132-148°C range,
against a rated operating temperature of 65°C.

## What this means in a real wind farm

Sustained gearbox overheating usually points to a lubrication or cooling
system failure. Continued operation at these temperatures accelerates
bearing wear and can lead to a gearbox seizure, which is one of the most
expensive single-component failures on a turbine.

## Triage steps

1. Open the Grafana "Windfarm Overview" dashboard and check the **Gearbox
   temperature (°C)** panel for the affected `turbine_id`. The panel's
   threshold line (100°C) marks the point where this starts to be a
   concern well before the hard fault threshold.
2. Cross-check the **Rotor speed (rpm)** panel: a high-load, high-speed
   period combined with rising temperature is consistent with a cooling
   system that can't keep up; a temperature spike with normal rotor speed
   points more directly at a lubrication fault.
3. In this simulation, faults are injected and cleared through the
   turbine's control API:
   ```bash
   curl http://localhost:8080/turbines/<id>
   curl -X DELETE http://localhost:8080/turbines/<id>/faults
   ```
4. On a real site, this is where you would command a controlled shutdown
   to stop further heat generation, and dispatch a technician to inspect
   the gearbox oil level, cooling fan, and heat exchanger before
   re-energizing.

## Resolution

The alert clears automatically once `status_code` returns to `0` (`OK`)
or `1` (`WARNING`) for a full evaluation interval.

#!/usr/bin/env bash
# End-to-end smoke test for the docker-compose observability stack.
#
# Brings the full stack up, waits for the collector to be scraped, injects
# an overspeed fault via the simulator's control API, polls Alertmanager
# until the matching alert fires, then clears the fault and tears the
# stack down. Exits non-zero on any failure so it is safe to use as a CI
# gate.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE="docker compose"
TIMEOUT_S=90

cleanup() {
    $COMPOSE down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> building and starting the stack"
$COMPOSE up -d --build

wait_for() {
    local description="$1"
    local check="$2"
    local deadline=$((SECONDS + TIMEOUT_S))
    until eval "$check" >/dev/null 2>&1; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "FAILED waiting for: $description" >&2
            $COMPOSE logs --tail 50 >&2 || true
            exit 1
        fi
        sleep 2
    done
    echo "==> ready: $description"
}

wait_for "collector target healthy in prometheus" \
    'curl -sf http://localhost:9090/api/v1/targets | python3 -c "import sys,json; d=json.load(sys.stdin); assert any(t[\"health\"]==\"up\" for t in d[\"data\"][\"activeTargets\"])"'

wait_for "windfarm dashboard provisioned in grafana" \
    'curl -sf -u admin:admin "http://localhost:3000/api/search?query=Windfarm" | python3 -c "import sys,json; assert json.load(sys.stdin)"'

echo "==> injecting overspeed fault on turbine 2"
curl -sf -X POST http://localhost:8080/turbines/2/faults \
    -H 'Content-Type: application/json' \
    -d '{"type": "overspeed", "duration_s": 60}' >/dev/null

wait_for "TurbineOverspeed alert firing in alertmanager" \
    'curl -sf http://localhost:9093/api/v2/alerts | python3 -c "
import sys, json
alerts = json.load(sys.stdin)
assert any(a[\"labels\"].get(\"alertname\") == \"TurbineOverspeed\" and a[\"status\"][\"state\"] == \"active\" for a in alerts)
"'

echo "==> clearing the fault"
curl -sf -X DELETE http://localhost:8080/turbines/2/faults >/dev/null

echo "==> smoke test passed"

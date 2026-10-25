#!/usr/bin/env python3
"""Measure real poll latency and Prometheus scrape load for an N-turbine farm.

Two real measurements, no estimation or synthetic data:

1. Poll latency: starts a real simulator subprocess (N turbines over Modbus
   TCP), then drives real ``TurbinePoller`` instances against it in-process
   -- the same poll-once code path the collector CLI uses -- for a fixed
   window, and records every individual poll's wall-clock duration.
2. Prometheus load: starts a real collector CLI subprocess serving
   ``/metrics`` for the same N turbines, points a temporary, real
   ``prom/prometheus`` container at it (removed again at the end), lets it
   scrape for a fixed window, then reads Prometheus's own
   ``scrape_duration_seconds`` for that target and times a sample PromQL
   query plus a raw ``/metrics`` fetch.

Usage:
    python scripts/perf_test.py --turbines 50 --poll-duration 30 \\
        --scrape-duration 25

Prints a JSON summary to stdout. Pass --out to also write it to a file.
This is a one-machine measurement for a portfolio project, not a
production capacity-planning benchmark -- see docs/performance.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from windfarm.collector.config import CollectorConfig, single_gateway_targets  # noqa: E402
from windfarm.collector.metrics import build_metrics  # noqa: E402
from windfarm.collector.poller import TurbinePoller  # noqa: E402
from prometheus_client import CollectorRegistry  # noqa: E402

PROM_CONTAINER_NAME = "windfarm-perf-prometheus"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--turbines", type=int, default=50, help="number of simulated turbines (default: 50)")
    parser.add_argument("--modbus-port", type=int, default=15020, help="simulator Modbus TCP port")
    parser.add_argument("--control-port", type=int, default=18080, help="simulator control API port")
    parser.add_argument("--metrics-port", type=int, default=19200, help="collector CLI /metrics port")
    parser.add_argument("--prometheus-port", type=int, default=19090, help="temporary Prometheus container port")
    parser.add_argument("--poll-interval", type=float, default=0.2, help="seconds between polls per turbine in the latency run")
    parser.add_argument("--request-timeout", type=float, default=2.0, help="per-request Modbus timeout in seconds")
    parser.add_argument("--poll-duration", type=float, default=30.0, help="seconds to run the latency measurement")
    parser.add_argument("--scrape-duration", type=float, default=25.0, help="seconds to let Prometheus scrape the collector")
    parser.add_argument("--scrape-interval", type=str, default="2s", help="Prometheus scrape_interval for the temporary job")
    parser.add_argument("--skip-docker", action="store_true", help="skip the Prometheus scrape-load measurement (latency only)")
    parser.add_argument("--out", type=Path, default=None, help="also write the JSON summary to this file")
    return parser.parse_args(argv)


def wait_for_tcp(host: str, port: int, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"nothing listening on {host}:{port} after {timeout_s}s")


def wait_for_http_ok(url: str, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"{url} did not return 200 after {timeout_s}s")


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


async def measure_poll_latency(args: argparse.Namespace) -> dict:
    targets = single_gateway_targets(list(range(1, args.turbines + 1)), "127.0.0.1", args.modbus_port)
    config = CollectorConfig(
        targets=targets,
        poll_interval_s=args.poll_interval,
        request_timeout_s=args.request_timeout,
        stale_after_s=15.0,
    )
    registry = CollectorRegistry()
    metrics = build_metrics(registry)
    pollers = [TurbinePoller(target, config, metrics) for target in targets]

    durations: list[float] = []
    outcomes = {"success": 0, "timeout": 0, "error": 0}
    lock = asyncio.Lock()

    async def poll_loop(poller: TurbinePoller, stop_at: float) -> None:
        while time.monotonic() < stop_at:
            result = await poller.poll_once()
            async with lock:
                durations.append(result.duration_s)
                outcomes["success" if result.success else ("timeout" if "timeout" in (result.error or "").lower() else "error")] += 1
            await asyncio.sleep(config.poll_interval_s)

    stop_at = time.monotonic() + args.poll_duration
    try:
        await asyncio.gather(*(poll_loop(p, stop_at) for p in pollers))
    finally:
        await asyncio.gather(*(p.close() for p in pollers), return_exceptions=True)

    durations.sort()
    total = len(durations)
    return {
        "turbine_count": args.turbines,
        "window_seconds": args.poll_duration,
        "configured_poll_interval_s": args.poll_interval,
        "total_polls": total,
        "polls_per_second": round(total / args.poll_duration, 2) if args.poll_duration else None,
        "outcomes": outcomes,
        "latency_seconds": {
            "min": round(min(durations), 6) if durations else None,
            "mean": round(statistics.mean(durations), 6) if durations else None,
            "p50": round(percentile(durations, 50), 6),
            "p90": round(percentile(durations, 90), 6),
            "p95": round(percentile(durations, 95), 6),
            "p99": round(percentile(durations, 99), 6),
            "max": round(max(durations), 6) if durations else None,
        },
    }


def run_simulator_subprocess(args: argparse.Namespace) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "windfarm.simulator.cli",
        "--turbines", str(args.turbines),
        "--modbus-host", "0.0.0.0",
        "--modbus-port", str(args.modbus_port),
        "--control-host", "0.0.0.0",
        "--control-port", str(args.control_port),
        "--seed", "99",
        "--log-level", "WARNING",
    ]
    env = {**__import__("os").environ, "PYTHONPATH": str(SRC_ROOT)}
    return subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_collector_subprocess(args: argparse.Namespace) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "windfarm.collector.cli",
        "--turbines", str(args.turbines),
        "--modbus-host", "127.0.0.1",
        "--modbus-port", str(args.modbus_port),
        "--metrics-host", "0.0.0.0",
        "--metrics-port", str(args.metrics_port),
        "--poll-interval", "2",
        "--request-timeout", str(args.request_timeout),
        "--stale-after", "15",
        "--log-level", "WARNING",
    ]
    env = {**__import__("os").environ, "PYTHONPATH": str(SRC_ROOT)}
    return subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def measure_prometheus_load(args: argparse.Namespace) -> dict:
    subprocess.run(["docker", "rm", "-f", PROM_CONTAINER_NAME], capture_output=True)

    scrape_config = f"""global:
  scrape_interval: {args.scrape_interval}
  evaluation_interval: {args.scrape_interval}

scrape_configs:
  - job_name: windfarm-collector-perf
    static_configs:
      - targets: ["host.docker.internal:{args.metrics_port}"]
"""
    config_path = REPO_ROOT / "scripts" / ".perf_prometheus.yml"
    config_path.write_text(scrape_config)

    try:
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", PROM_CONTAINER_NAME,
                "--add-host", "host.docker.internal:host-gateway",
                "-p", f"{args.prometheus_port}:9090",
                "-v", f"{config_path}:/etc/prometheus/prometheus.yml:ro",
                "prom/prometheus:latest",
            ],
            check=True,
            capture_output=True,
        )

        wait_for_http_ok(f"http://localhost:{args.prometheus_port}/-/ready", timeout_s=30.0)
        time.sleep(args.scrape_duration)

        fetch_start = time.monotonic()
        with urllib.request.urlopen(f"http://localhost:{args.metrics_port}/metrics", timeout=5.0) as resp:
            payload = resp.read()
        fetch_duration = time.monotonic() - fetch_start

        query_url = (
            f"http://localhost:{args.prometheus_port}/api/v1/query"
            "?query=" + urllib.request.quote('scrape_duration_seconds{job="windfarm-collector-perf"}')
        )
        query_start = time.monotonic()
        with urllib.request.urlopen(query_url, timeout=5.0) as resp:
            query_result = json.load(resp)
        query_duration = time.monotonic() - query_start

        scrape_durations = [
            float(r["value"][1]) for r in query_result.get("data", {}).get("result", [])
        ]

        up_url = (
            f"http://localhost:{args.prometheus_port}/api/v1/query"
            "?query=" + urllib.request.quote('up{job="windfarm-collector-perf"}')
        )
        with urllib.request.urlopen(up_url, timeout=5.0) as resp:
            up_result = json.load(resp)
        target_up = bool(up_result.get("data", {}).get("result")) and up_result["data"]["result"][0]["value"][1] == "1"

        return {
            "turbine_count": args.turbines,
            "scrape_interval": args.scrape_interval,
            "scrape_window_seconds": args.scrape_duration,
            "target_up": target_up,
            "metrics_payload_bytes": len(payload),
            "metrics_fetch_seconds": round(fetch_duration, 6),
            "prometheus_reported_scrape_duration_seconds": (
                round(scrape_durations[-1], 6) if scrape_durations else None
            ),
            "promql_query_seconds": round(query_duration, 6),
        }
    finally:
        subprocess.run(["docker", "rm", "-f", PROM_CONTAINER_NAME], capture_output=True)
        config_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    print(f"==> starting simulator subprocess ({args.turbines} turbines, port {args.modbus_port})", file=sys.stderr)
    simulator = run_simulator_subprocess(args)
    try:
        wait_for_tcp("127.0.0.1", args.modbus_port, timeout_s=20.0)
        wait_for_http_ok(f"http://127.0.0.1:{args.control_port}/healthz", timeout_s=20.0)

        print(f"==> measuring poll latency for {args.poll_duration}s", file=sys.stderr)
        latency_result = asyncio.run(measure_poll_latency(args))

        prometheus_result: dict | None = None
        if not args.skip_docker:
            print(f"==> starting collector subprocess (/metrics on {args.metrics_port})", file=sys.stderr)
            collector = run_collector_subprocess(args)
            try:
                wait_for_http_ok(f"http://127.0.0.1:{args.metrics_port}/metrics", timeout_s=20.0)
                print(f"==> starting temporary Prometheus container, scraping for {args.scrape_duration}s", file=sys.stderr)
                prometheus_result = measure_prometheus_load(args)
            finally:
                collector.terminate()
                collector.wait(timeout=10)
    finally:
        simulator.terminate()
        try:
            simulator.wait(timeout=10)
        except subprocess.TimeoutExpired:
            simulator.kill()

    summary = {
        "poll_latency": latency_result,
        "prometheus_scrape_load": prometheus_result,
    }
    output = json.dumps(summary, indent=2)
    print(output)
    if args.out:
        args.out.write_text(output + "\n")
        print(f"==> wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

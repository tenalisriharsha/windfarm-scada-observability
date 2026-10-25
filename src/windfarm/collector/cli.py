"""Entrypoint: poll N turbines over Modbus TCP and export Prometheus metrics.

    python -m windfarm.collector.cli --turbines 5 --modbus-host 127.0.0.1 \\
        --modbus-port 5020 --metrics-port 9200
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from prometheus_client import REGISTRY, start_http_server

from windfarm.collector.config import CollectorConfig, single_gateway_targets
from windfarm.collector.metrics import build_metrics
from windfarm.collector.service import Collector

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turbines", type=int, default=5, help="number of turbines to poll (ids 1..N)")
    parser.add_argument("--modbus-host", default="127.0.0.1", help="simulator Modbus TCP host")
    parser.add_argument("--modbus-port", type=int, default=5020, help="simulator Modbus TCP port")
    parser.add_argument("--metrics-host", default="0.0.0.0", help="Prometheus /metrics bind address")
    parser.add_argument("--metrics-port", type=int, default=9200, help="Prometheus /metrics bind port")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="seconds between polls per turbine")
    parser.add_argument("--request-timeout", type=float, default=2.0, help="per-request Modbus timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=3, help="retries after the first failed attempt")
    parser.add_argument("--backoff-base", type=float, default=0.5, help="base retry backoff in seconds")
    parser.add_argument("--backoff-max", type=float, default=5.0, help="retry backoff ceiling in seconds")
    parser.add_argument("--stale-after", type=float, default=15.0, help="seconds without a success before marking a turbine down")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> CollectorConfig:
    targets = single_gateway_targets(list(range(1, args.turbines + 1)), args.modbus_host, args.modbus_port)
    return CollectorConfig(
        targets=targets,
        poll_interval_s=args.poll_interval,
        request_timeout_s=args.request_timeout,
        max_retries=args.max_retries,
        backoff_base_s=args.backoff_base,
        backoff_max_s=args.backoff_max,
        stale_after_s=args.stale_after,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = build_config(args)
    metrics = build_metrics(REGISTRY)
    start_http_server(args.metrics_port, addr=args.metrics_host, registry=REGISTRY)
    logger.info("metrics listening on %s:%d", args.metrics_host, args.metrics_port)
    logger.info("polling %d turbine(s) at %s:%d every %.1fs", args.turbines, args.modbus_host, args.modbus_port, args.poll_interval)

    collector = Collector(config, metrics)
    try:
        asyncio.run(collector.run_forever())
    except KeyboardInterrupt:
        logger.info("shutting down")


if __name__ == "__main__":
    main()

"""Wires together one poller per configured turbine and runs them forever."""

from __future__ import annotations

import asyncio
import logging

from windfarm.collector.config import CollectorConfig
from windfarm.collector.metrics import Metrics
from windfarm.collector.poller import ClientFactory, TurbinePoller, default_client_factory

logger = logging.getLogger(__name__)


class Collector:
    def __init__(
        self,
        config: CollectorConfig,
        metrics: Metrics,
        client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self.config = config
        self.metrics = metrics
        self.pollers = [TurbinePoller(target, config, metrics, client_factory) for target in config.targets]

    async def run_forever(self) -> None:
        try:
            await asyncio.gather(
                *(self._poll_loop(poller) for poller in self.pollers),
                self._staleness_refresh_loop(),
            )
        finally:
            await asyncio.gather(*(p.close() for p in self.pollers), return_exceptions=True)

    async def _poll_loop(self, poller: TurbinePoller) -> None:
        while True:
            try:
                await poller.poll_once()
            except Exception:  # noqa: BLE001 - a single turbine's bug must not take down the collector
                logger.exception("unexpected error polling turbine %s", poller.target.turbine_id)
            await asyncio.sleep(self.config.poll_interval_s)

    async def _staleness_refresh_loop(self) -> None:
        while True:
            for poller in self.pollers:
                poller.refresh_staleness()
            await asyncio.sleep(self.config.staleness_refresh_interval_s)

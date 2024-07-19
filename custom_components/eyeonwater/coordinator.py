"""EyeOnWater coordinator."""
import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import UpdateFailed
from pyonwater import Account, Client, EyeOnWaterAPIError, EyeOnWaterAuthError, Meter

from .sensor import (
    async_import_statistics,
    convert_statistic_data,
    get_statistic_metadata,
)

_LOGGER = logging.getLogger(__name__)


class EyeOnWaterData:
    """Manages coordination of API data updates."""

    def __init__(self, hass: HomeAssistant, account: Account) -> None:
        """Initialize the data coordinator."""
        self.hass = hass
        self.account = account
        self.client = Client(aiohttp_client.async_get_clientsession(hass), account)
        self.meters: list[Meter] = []

    async def setup(self) -> None:
        """Fetch all of the user's meters."""
        try:
            self.meters = await self.account.fetch_meters(self.client)
            _LOGGER.debug("Discovered %i meter(s)", len(self.meters))
        except (EyeOnWaterAPIError, EyeOnWaterAuthError) as error:
            _LOGGER.error("Error fetching meters: %s", error)
            raise UpdateFailed from error

    async def read_meters(self, days_to_load: int = 3) -> list[Meter]:
        """Read each meter."""
        try:
            tasks = [
                meter.read_meter_info(client=self.client)
                for meter in self.meters
            ] + [
                meter.read_historical_data(client=self.client, days_to_load=days_to_load)
                for meter in self.meters
            ]
            await asyncio.gather(*tasks)
        except (EyeOnWaterAPIError, EyeOnWaterAuthError) as error:
            raise UpdateFailed(error) from error

        return self.meters

    async def import_historical_data(self, days: int) -> None:
        """Import historical data."""
        for meter in self.meters:
            try:
                data = await meter.read_historical_data(client=self.client, days_to_load=days)
                _LOGGER.info("%i data points will be imported", len(data))
                statistics = convert_statistic_data(data)
                metadata = get_statistic_metadata(meter)
                await async_import_statistics(self.hass, metadata, statistics)
            except (EyeOnWaterAPIError, EyeOnWaterAuthError) as error:
                _LOGGER.error("Error importing historical data for meter %s: %s", meter.meter_id, error)
                raise UpdateFailed from error

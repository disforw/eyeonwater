"""Support for EyeOnWater sensors."""
from __future__ import annotations

import datetime
import logging
from typing import Any

import pyonwater
from homeassistant import exceptions
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DATA_COORDINATOR, DATA_SMART_METER, DOMAIN, WATER_METER_NAME
from .statistic_helper import (
    convert_statistic_data,
    filter_newer_data,
    get_ha_native_unit_of_measurement,
    get_last_imported_time,
    get_statistic_metadata,
    normalize_id,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EyeOnWater sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]
    meters = hass.data[DOMAIN][config_entry.entry_id][DATA_SMART_METER].meters

    sensors = [
        sensor
        for meter in meters
        for sensor in (
            EyeOnWaterStatistic(meter, coordinator, await get_last_imported_time(hass, meter)),
            EyeOnWaterSensor(meter, coordinator),
            *(EyeOnWaterTempSensor(meter, coordinator) for _ in [1] if meter.meter_info.sensors and meter.meter_info.sensors.endpoint_temperature)
        )
    ]

    async_add_entities(sensors)


class NoDataFound(exceptions.HomeAssistantError):
    """Error to indicate there is no data."""


class EyeOnWaterStatistic(CoordinatorEntity, SensorEntity):
    """Representation of an EyeOnWater statistic sensor."""

    def __init__(
        self,
        meter: pyonwater.Meter,
        coordinator: DataUpdateCoordinator,
        last_imported_time: datetime.datetime | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.meter = meter
        self._uuid = normalize_id(meter.meter_uuid)
        self._id = normalize_id(meter.meter_id)
        self._last_imported_time = last_imported_time

        self._attr_name = f"{WATER_METER_NAME} {self._id} Statistic"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_unique_id = f"{self._uuid}_statistic"
        self._attr_native_unit_of_measurement = get_ha_native_unit_of_measurement(meter.native_unit_of_measurement)
        self._attr_suggested_display_precision = 0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uuid)},
            name=f"{WATER_METER_NAME} {self._id}",
            model=meter.meter_info.reading.model,
            manufacturer=meter.meter_info.reading.customer_name,
            hw_version=meter.meter_info.reading.hardware_version,
            sw_version=meter.meter_info.reading.firmware_version,
        )

        self._state: pyonwater.DataPoint | None = None
        self._available = False
        self._last_historical_data: list[pyonwater.DataPoint] = []

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def native_value(self) -> float | None:
        """Get the latest reading."""
        return self._state.reading if self._state else None

    @callback
    def _state_update(self) -> None:
        """Call when the coordinator has an update."""
        self._available = self.coordinator.last_update_success
        if self._available:
            self._state = self.meter.reading

            if not self.meter.last_historical_data:
                raise NoDataFound("Meter doesn't have recent readings")

            self._last_historical_data = filter_newer_data(self.meter.last_historical_data, self._last_imported_time)
            if self._last_historical_data:
                self.import_historical_data()
                self._last_imported_time = self._last_historical_data[-1].dt

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(self.coordinator.async_add_listener(self._state_update))

        if self.coordinator.last_update_success:
            return

        if last_state := await self.async_get_last_state():
            self._state = last_state.state
            self._available = True

    def import_historical_data(self) -> None:
        """Import historical data for today and past N days."""
        if not self._last_historical_data:
            _LOGGER.info("There is no new historical data")
            return

        _LOGGER.info("%i data points will be imported", len(self._last_historical_data))
        statistics = convert_statistic_data(self._last_historical_data)
        metadata = get_statistic_metadata(self.meter)

        async_import_statistics(self.hass, metadata, statistics)


class EyeOnWaterTempSensor(CoordinatorEntity, SensorEntity):
    """Representation of an EyeOnWater temperature sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, meter: pyonwater.Meter, coordinator: DataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.meter = meter
        self._uuid = normalize_id(meter.meter_uuid)
        self._id = normalize_id(meter.meter_id)

        self._attr_unique_id = f"{self._uuid}_temperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uuid)},
            name=f"{WATER_METER_NAME} {self._id}",
            model=meter.meter_info.reading.model,
            manufacturer=meter.meter_info.reading.customer_name,
            hw_version=meter.meter_info.reading.hardware_version,
            sw_version=meter.meter_info.reading.firmware_version,
        )

    @property
    def native_value(self) -> float | None:
        """Get the latest temperature reading."""
        return self.meter.meter_info.sensors.endpoint_temperature.seven_day_min if self.meter.meter_info.sensors and self.meter.meter_info.sensors.endpoint_temperature else None


class EyeOnWaterSensor(CoordinatorEntity, SensorEntity):
    """Representation of an EyeOnWater sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, meter: pyonwater.Meter, coordinator: DataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.meter = meter
        self._uuid = normalize_id(meter.meter_uuid)
        self._id = normalize_id(meter.meter_id)

        self._state: pyonwater.DataPoint | None = None
        self._available = False

        self._attr_unique_id = self._uuid
        self._attr_native_unit_of_measurement = get_ha_native_unit_of_measurement(meter.native_unit_of_measurement)
        self._attr_suggested_display_precision = 0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uuid)},
            name=f"{WATER_METER_NAME} {self._id}",
            model=meter.meter_info.reading.model,
            manufacturer=meter.meter_info.reading.customer_name,
            hw_version=meter.meter_info.reading.hardware_version,
            sw_version=meter.meter_info.reading.firmware_version,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def native_value(self) -> float | None:
        """Get the latest reading."""
        return self._state.reading if self._state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the device specific state attributes."""
        return self.meter.meter_info.reading.dict()

    @callback
    def _state_update(self) -> None:
        """Call when the coordinator has an update."""
        self._available = self.coordinator.last_update_success
        if self._available:
            self._state = self.meter.reading
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(self.coordinator.async_add_listener(self._state_update))

        if self.coordinator.last_update_success:
            return

        if last_state := await self.async_get_last_state():
            self._state = last_state.state
            self._available = True

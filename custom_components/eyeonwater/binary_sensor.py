"""Support for EyeOnWater binary sensors."""
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from pyonwater import Meter

from .const import DATA_COORDINATOR, DATA_SMART_METER, DOMAIN, WATER_METER_NAME
from .statistic_helper import normalize_id


@dataclass
class Description:
    """Binary sensor description."""

    key: str
    device_class: BinarySensorDeviceClass
    translation_key: str | None = None


FLAG_SENSORS = [
    Description(
        key="leak",
        translation_key="leak",
        device_class=BinarySensorDeviceClass.MOISTURE,
    ),
    Description(
        key="empty_pipe",
        translation_key="emptypipe",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    Description(
        key="tamper",
        translation_key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
    ),
    Description(
        key="cover_removed",
        translation_key="coverremoved",
        device_class=BinarySensorDeviceClass.TAMPER,
    ),
    Description(
        key="reverse_flow",
        translation_key="reverseflow",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    Description(
        key="low_battery",
        device_class=BinarySensorDeviceClass.BATTERY,
    ),
    Description(
        key="battery_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
]


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the EyeOnWater binary sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]
    meters = hass.data[DOMAIN][config_entry.entry_id][DATA_SMART_METER].meters

    sensors = [
        EyeOnWaterBinarySensor(meter, coordinator, description)
        for meter in meters
        for description in FLAG_SENSORS
    ]

    async_add_entities(sensors)


class EyeOnWaterBinarySensor(CoordinatorEntity, RestoreEntity, BinarySensorEntity):
    """Representation of an EyeOnWater binary flag sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        meter: Meter,
        coordinator: DataUpdateCoordinator,
        description: Description,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = BinarySensorEntityDescription(
            key=description.key,
            device_class=description.device_class,
            translation_key=description.translation_key,
        )
        self.meter = meter
        self._uuid = normalize_id(meter.meter_uuid)
        self._id = normalize_id(meter.meter_id)
        self._attr_unique_id = f"{description.key}_{self._uuid}"
        self._attr_is_on = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uuid)},
            name=f"{WATER_METER_NAME} {self._id}",
            model=meter.meter_info.reading.model,
            manufacturer=meter.meter_info.reading.customer_name,
            hw_version=meter.meter_info.reading.hardware_version,
            sw_version=meter.meter_info.reading.firmware_version,
        )

    def get_flag(self) -> bool:
        """Get flag value."""
        return getattr(self.meter.meter_info.reading.flags, self.entity_description.key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self.get_flag()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

        if self.coordinator.last_update_success:
            self._handle_coordinator_update()
        else:
            last_state = await self.async_get_last_state()
            if last_state:
                self._attr_is_on = last_state.state == "on"
                self._available = True

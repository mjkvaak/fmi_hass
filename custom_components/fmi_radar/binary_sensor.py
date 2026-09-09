"""Rain now / will-rain binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alert import STATUS_RAIN, will_rain_flag

from .const import DOMAIN
from .coordinator import FmiRadarCoordinator
from .entity import FmiRadarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FmiRadarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FmiRadarRainingSensor(coordinator),
            FmiRadarWillRainSensor(coordinator, 5),
            FmiRadarWillRainSensor(coordinator, 10),
            FmiRadarWillRainSensor(coordinator, 15),
        ]
    )


class FmiRadarRainingSensor(FmiRadarEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:weather-pouring"

    def __init__(self, coordinator: FmiRadarCoordinator) -> None:
        super().__init__(coordinator, "raining")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.alert.status == STATUS_RAIN


class FmiRadarWillRainSensor(FmiRadarEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: FmiRadarCoordinator, lead: int) -> None:
        super().__init__(coordinator, f"will_rain_{lead}")
        self._lead = lead
        self._attr_translation_key = "will_rain"
        self._attr_translation_placeholders = {"minutes": str(lead)}

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        flag = will_rain_flag(self.coordinator.data.nowcast_alerts.get(self._lead))
        if flag == "unknown":
            return None
        return flag == "true"

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        flag = will_rain_flag(self.coordinator.data.nowcast_alerts.get(self._lead))
        return flag != "unknown"

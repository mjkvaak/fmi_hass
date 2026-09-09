"""FMI radar sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolumetricFlux
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
            FmiRadarStatusSensor(coordinator),
            FmiRadarRateSensor(coordinator, "mean_rr", lambda r: r.alert.mean_rr_mmh),
            FmiRadarRateSensor(coordinator, "max_rr", lambda r: r.alert.max_rr_mmh),
            FmiRadarTimestampSensor(coordinator),
        ]
    )


class FmiRadarStatusSensor(FmiRadarEntity, SensorEntity):
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: FmiRadarCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.alert.status


class FmiRadarRateSensor(FmiRadarEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.PRECIPITATION_INTENSITY
    _attr_native_unit_of_measurement = UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:weather-pouring"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: FmiRadarCoordinator, key: str, getter) -> None:
        super().__init__(coordinator, key)
        self._getter = getter

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return round(float(self._getter(self.coordinator.data)), 4)


class FmiRadarTimestampSensor(FmiRadarEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: FmiRadarCoordinator) -> None:
        super().__init__(coordinator, "timestamp")

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.crop.timestamp

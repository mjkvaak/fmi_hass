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
            FmiRadarStatusSensor(coordinator),
            FmiRadarRateSensor(coordinator, "mean_rr", lambda r: r.alert.mean_rr_mmh),
            FmiRadarRateSensor(coordinator, "max_rr", lambda r: r.alert.max_rr_mmh),
            FmiRadarTimestampSensor(coordinator),
            FmiRadarRainingSensor(coordinator),
            FmiRadarWillRainSensor(coordinator, 5),
            FmiRadarWillRainSensor(coordinator, 10),
            FmiRadarWillRainSensor(coordinator, 15),
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


class FmiRadarRainingSensor(FmiRadarEntity, SensorEntity):
    _attr_icon = "mdi:weather-pouring"

    def __init__(self, coordinator: FmiRadarCoordinator) -> None:
        super().__init__(coordinator, "raining")

    @property
    def native_value(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.alert.status == STATUS_RAIN


class FmiRadarWillRainSensor(FmiRadarEntity, SensorEntity):
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: FmiRadarCoordinator, lead: int) -> None:
        super().__init__(coordinator, f"will_rain_{lead}")
        self._lead = lead
        self._attr_translation_key = "will_rain"
        self._attr_translation_placeholders = {"minutes": str(lead)}

    @property
    def native_value(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return will_rain_flag(self.coordinator.data.nowcast_alerts.get(self._lead))

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        return will_rain_flag(self.coordinator.data.nowcast_alerts.get(self._lead)) is not None


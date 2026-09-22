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

from .alert import STATUS_RAIN
from .const import DOMAIN
from .coordinator import FmiRadarCoordinator
from .entity import FmiRadarEntity


def _nowcast_rate(lead: int, attr: str):
    def getter(result) -> float | None:
        alert = result.nowcast_alerts.get(lead)
        if alert is None:
            return None
        return float(getattr(alert, attr))

    return getter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FmiRadarCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        FmiRadarStatusSensor(coordinator),
        FmiRadarRateSensor(coordinator, "mean_rr", lambda r: r.alert.mean_rr_mmh),
        FmiRadarRateSensor(coordinator, "max_rr", lambda r: r.alert.max_rr_mmh),
        FmiRadarTimestampSensor(coordinator),
        FmiRadarRainingSensor(coordinator),
    ]
    for lead in (5, 10, 15):
        entities.append(
            FmiRadarRateSensor(
                coordinator,
                "mean_rr",
                _nowcast_rate(lead, "mean_rr_mmh"),
                lead=lead,
            )
        )
        entities.append(
            FmiRadarRateSensor(
                coordinator,
                "max_rr",
                _nowcast_rate(lead, "max_rr_mmh"),
                lead=lead,
            )
        )
    async_add_entities(entities)


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

    def __init__(
        self,
        coordinator: FmiRadarCoordinator,
        key: str,
        getter,
        *,
        lead: int | None = None,
    ) -> None:
        unique = f"{key}_{lead}" if lead is not None else key
        super().__init__(coordinator, unique)
        self._getter = getter
        if lead is not None:
            self._attr_translation_key = f"{key}_lead"
            self._attr_translation_placeholders = {"minutes": str(lead)}

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = self._getter(self.coordinator.data)
        if value is None:
            return None
        return round(float(value), 4)

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        return self._getter(self.coordinator.data) is not None


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

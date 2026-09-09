"""Radar map cameras (PNG still and GIF nowcast)."""

from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
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
            FmiRadarMapCamera(coordinator),
            FmiRadarGifCamera(coordinator),
        ]
    )


class FmiRadarMapCamera(FmiRadarEntity, Camera):
    _attr_icon = "mdi:radar"
    _attr_content_type = "image/png"

    def __init__(self, coordinator: FmiRadarCoordinator) -> None:
        FmiRadarEntity.__init__(self, coordinator, "map")
        Camera.__init__(self)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator.png_bytes


class FmiRadarGifCamera(FmiRadarEntity, Camera):
    _attr_icon = "mdi:animation-play"
    _attr_content_type = "image/gif"

    def __init__(self, coordinator: FmiRadarCoordinator) -> None:
        FmiRadarEntity.__init__(self, coordinator, "nowcast")
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.gif_bytes)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator.gif_bytes

"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FmiRadarCoordinator


class FmiRadarEntity(CoordinatorEntity[FmiRadarCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FmiRadarCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info
        self._attr_translation_key = key

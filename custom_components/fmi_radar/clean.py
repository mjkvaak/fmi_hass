"""Drop tiny isolated radar echoes on FMI composites (not on advected nowcasts).

Bird flocks and similar clutter often appear as one- or two-pixel speckles at
250 m. Real rain at this resolution is almost always a larger connected patch.
Optical-flow advection can smear rain into small blobs; those frames are left
alone so nowcast speckles are not stripped.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from .log import get_logger

if TYPE_CHECKING:
    from .process import RadarCrop

LOGGER = get_logger(__name__)

# 250 m pixels: 3 cells ≈ 0.19 km². Smaller wet islands are treated as clutter.
MIN_ECHO_PIXELS = 3


def _label_4(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected labels, 1..n (0 = background)."""
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent = [0]

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    next_label = 0
    wet = np.asarray(mask, dtype=bool)
    for row in range(height):
        for col in range(width):
            if not wet[row, col]:
                continue
            left = labels[row, col - 1] if col else 0
            up = labels[row - 1, col] if row else 0
            if left and up:
                labels[row, col] = left
                root_left, root_up = find(left), find(up)
                if root_left != root_up:
                    parent[root_up] = root_left
            elif left:
                labels[row, col] = left
            elif up:
                labels[row, col] = up
            else:
                next_label += 1
                parent.append(next_label)
                labels[row, col] = next_label
    remap: dict[int, int] = {}
    count = 0
    out = np.zeros_like(labels)
    for row in range(height):
        for col in range(width):
            lab = labels[row, col]
            if lab == 0:
                continue
            root = find(lab)
            mapped = remap.get(root)
            if mapped is None:
                count += 1
                remap[root] = count
                mapped = count
            out[row, col] = mapped
    return out, count


def despike_crop(crop: RadarCrop, rr_min: float) -> RadarCrop:
    """Clear wet islands smaller than ``MIN_ECHO_PIXELS`` (FMI input only)."""
    wet = crop.valid & np.isfinite(crop.rr) & (crop.rr >= float(rr_min))
    if not np.any(wet):
        return crop
    labels, n_comp = _label_4(wet)
    if n_comp == 0:
        return crop
    counts = np.bincount(labels.ravel(), minlength=n_comp + 1)
    small = counts < MIN_ECHO_PIXELS
    small[0] = False
    drop = small[labels]
    removed = int(np.count_nonzero(drop))
    if removed == 0:
        return crop
    LOGGER.debug(
        "Removed %s isolated echo pixel(s) in %s small island(s)",
        removed,
        int(np.count_nonzero(small)),
    )
    rr = crop.rr.copy()
    dbzh = crop.dbzh.copy()
    valid = crop.valid.copy()
    rr[drop] = np.nan
    dbzh[drop] = np.nan
    valid[drop] = False
    return replace(crop, rr=rr, dbzh=dbzh, valid=valid)

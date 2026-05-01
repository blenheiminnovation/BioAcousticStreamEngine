"""
Shared mutable state for the API — avoids circular imports between app.py and routes.

Author: David Green, Blenheim Palace
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ecoacoustics.api.pipeline_manager import PipelineManager

# Keyed by device_key (e.g. "default", "device_2"). One entry per active or ever-started device.
pipeline_instances: dict[str, "PipelineManager"] = {}

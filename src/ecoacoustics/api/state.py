"""
Shared mutable state for the API — avoids circular imports between app.py and routes.

Author: David Green, Blenheim Palace
"""

import asyncio
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ecoacoustics.api.pipeline_manager import PipelineManager

# Keyed by device_key (e.g. "default", "device_2"). One entry per active or ever-started device.
pipeline_instances: dict[str, "PipelineManager"] = {}

# Set once during lifespan startup — used by sync route handlers that need to wire
# new pipeline managers to the async broadcast queue without access to the running loop.
event_loop: Optional[asyncio.AbstractEventLoop] = None
broadcast_queue: Optional[asyncio.Queue] = None

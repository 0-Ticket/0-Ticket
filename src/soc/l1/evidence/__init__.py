"""Evidence request queue (box 26, D-034): L1 and L2 requests, one at a time, in order.

Backends register in the ``evidence_queues`` group; ``[evidence_queue] backend``
picks one and the core opens it with ``open_evidence_queue`` without naming it.
The worker is ``soc.l1.evidence.service.EvidenceQueueService``.
"""

import os
from collections.abc import Mapping

from soc.config import Settings
from soc.plugins import PluginRegistry

from .base import EvidenceQueue
from .postgresql import create_postgresql_evidence_queue

EVIDENCE_QUEUES = PluginRegistry("evidence_queues")
EVIDENCE_QUEUES.register("postgresql", create_postgresql_evidence_queue)


def open_evidence_queue(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> EvidenceQueue:
    """Open the queue backend ``[evidence_queue] backend`` names."""
    environ = os.environ if environ is None else environ
    registry = EVIDENCE_QUEUES if registry is None else registry
    return registry.get(settings.evidence_queue.backend)(settings, environ)

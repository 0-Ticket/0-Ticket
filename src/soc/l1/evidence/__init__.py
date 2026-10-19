"""Evidence request queue (box 26, D-034): L1 and L2 requests, one at a time, in order.

Backends register in the ``evidence_queues`` group; ``[evidence_queue] backend``
picks one and the core opens it with ``open_evidence_queue`` without naming it.
The worker is ``soc.l1.evidence.service.EvidenceQueueService``.

A backend registers two names: ``<backend>`` for the queue the worker writes
through and ``<backend>.readonly`` for the same rows through a read-only
connection, which the screen API (box 27) reads with ``readonly=True``
(docs/extensibility.md, docs/security-policy.md 4).
"""

import os
from collections.abc import Mapping

from soc.config import Settings
from soc.plugins import PluginRegistry

from .base import EvidenceQueue
from .postgresql import (
    create_postgresql_evidence_queue,
    create_postgresql_readonly_evidence_queue,
)

# The read-only name of a backend; see this module's docstring.
READONLY_SUFFIX = ".readonly"

EVIDENCE_QUEUES = PluginRegistry("evidence_queues")
EVIDENCE_QUEUES.register("postgresql", create_postgresql_evidence_queue)
EVIDENCE_QUEUES.register(f"postgresql{READONLY_SUFFIX}", create_postgresql_readonly_evidence_queue)


def open_evidence_queue(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
    *,
    readonly: bool = False,
) -> EvidenceQueue:
    """Open the queue backend ``[evidence_queue] backend`` names.

    With ``readonly=True`` it opens that backend's ``<backend>.readonly``
    implementation, which reads the same rows and fails on every write.
    """
    environ = os.environ if environ is None else environ
    registry = EVIDENCE_QUEUES if registry is None else registry
    name = settings.evidence_queue.backend + (READONLY_SUFFIX if readonly else "")
    return registry.get(name)(settings, environ)

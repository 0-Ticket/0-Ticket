"""Specialist Agents (boxes 13, 14): the domain analysis behind an L1 verdict.

Implementations register in the ``specialists`` group under the C22 ``domain``
they answer for, and the core opens one with ``open_specialist(domain, ...)``
without naming it. Web is built; Cloud (13) is one registration away once its
source is decided (D-005).
"""

from soc.l1.specialists.base import (
    NoStoredEvidenceError as NoStoredEvidenceError,
)
from soc.l1.specialists.base import (
    Specialist as Specialist,
)
from soc.l1.specialists.base import (
    SpecialistContext as SpecialistContext,
)
from soc.l1.specialists.web import WEB_DOMAIN, web_specialist
from soc.plugins import PluginRegistry

SPECIALISTS = PluginRegistry("specialists")
SPECIALISTS.register(WEB_DOMAIN, web_specialist)

# The domain a specialist_agent request falls back to when it names none.
DEFAULT_DOMAIN = WEB_DOMAIN


def open_specialist(
    domain: str, context: SpecialistContext, registry: PluginRegistry | None = None
) -> Specialist:
    """Build the specialist registered for ``domain``."""
    registry = SPECIALISTS if registry is None else registry
    return registry.get(domain)(context)

"""Sample external plugin module, standing in for a company package installed beside the core."""


class AcmeSiemAdapter:
    """Minimal stand-in for an implementation registered through an entry point."""

    name = "acme_siem"


class RivalSiemAdapter:
    """A second package's implementation, used to collide on one entry point name."""

    name = "rival_siem"

"""Sample external plugin that fails to import, pinning the entry point failure policy."""

raise RuntimeError("this sample plugin fails to import on purpose")

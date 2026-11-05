"""L2 Incident 분석 워커 공개 진입점."""


def build_worker(config: dict[str, object]):
    from soc.l2.analyze.worker import build_worker as factory

    return factory(config)  # type: ignore[arg-type]


__all__ = ["build_worker"]

from threading import Lock


def _format_key(name: str, labels: dict[str, str] | None) -> str:
    if not labels:
        return name
    label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}"


class Metrics:
    """进程内轻量指标注册表（第 17 节）。第二阶段可替换为 Prometheus client。

    counter 语义用 increment（累加），gauge 语义用 observe（记录最新值）。
    """

    def __init__(self) -> None:
        self._values: dict[str, float] = {}
        self._lock = Lock()

    def increment(
        self, name: str, amount: float = 1, labels: dict[str, str] | None = None
    ) -> None:
        key = _format_key(name, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = _format_key(name, labels)
        with self._lock:
            self._values[key] = value

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)


def _format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def render_prometheus(metrics: Metrics) -> str:
    """把指标快照渲染为 Prometheus 文本格式（第 13.2 节 /metrics）。"""
    lines = [f"{key} {_format_number(val)}" for key, val in sorted(metrics.snapshot().items())]
    return "".join(f"{line}\n" for line in lines)

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Service:
    """MCP 工具运行期依赖容器，由服务启动时的 lifespan 装配。"""

    orchestrator: Any
    db: Any
    data_dir: Path
    inline_limit_bytes: int
    max_markdown_bytes: int

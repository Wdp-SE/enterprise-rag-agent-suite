"""Keep Minimal Core tests offline and isolated from optional online tool imports."""

import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# app.tool/__init__.py eagerly loads Search/Browser integrations. These offline tests
# load only the real BaseTool and KnowledgeDraftTool modules from the package path.
tool_package = types.ModuleType("app.tool")
tool_package.__path__ = [str(PROJECT_ROOT / "app" / "tool")]
sys.modules.setdefault("app.tool", tool_package)

# The local assessment interpreter lacks the declared structlog dependency. A no-op
# logger isolates that environment gap without replacing or modifying BaseTool itself.
try:
    import structlog  # noqa: F401
except ModuleNotFoundError:
    logger_module = types.ModuleType("app.utils.logger")

    class _NoOpLogger:
        def debug(self, *args, **kwargs):
            return None

        info = warning = error = exception = debug

    logger_module.logger = _NoOpLogger()
    sys.modules.setdefault("app.utils.logger", logger_module)

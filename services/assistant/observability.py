import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any


logger = logging.getLogger("assistant_observability")


def configure_observability() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _safe_dump(payload: Any) -> str:
    try:
        return json.dumps(payload, default=_json_default, ensure_ascii=True)
    except TypeError:
        return repr(payload)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return str(value)


def log_call(name: str, payload: Any, *, result: Any = None, error: Exception | None = None, kind: str) -> None:
    if error is None:
        logger.info("%s name=%s input=%s output=%s", kind, name, _safe_dump(payload), _safe_dump(result))
        return
    logger.exception("%s name=%s input=%s failed=%s", kind, name, _safe_dump(payload), str(error))


def invoke_with_logging(name: str, target: Any, payload: Any, **kwargs: Any) -> Any:
    try:
        result = target.invoke(payload, **kwargs)
    except Exception as error:
        log_call(name, payload, error=error, kind="invoke")
        raise
    log_call(name, payload, result=result, kind="invoke")
    return result


def logged_node(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        payload = args[0] if args else {"args": args, "kwargs": kwargs}
        try:
            result = fn(*args, **kwargs)
        except Exception as error:
            log_call(name, payload, error=error, kind="node")
            raise
        log_call(name, payload, result=result, kind="node")
        return result

    return wrapper

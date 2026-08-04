# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adapter for an external query-correction service.

The service receives a JSON object containing ``query`` and, when selected, a
``language`` value.  It should return ``{"correction": "corrected query"}`` or
``{"correction": null}`` when no conservative correction is available.
"""

import threading
import time
import typing as t
import unicodedata
from urllib.parse import urlparse

from searx.result_types import EngineResults


if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

DOCUMENTATION_URL = "https://docs.searxng.org/dev/engines/online/query_corrector.html"

about = {
    "website": DOCUMENTATION_URL,
    "official_api_documentation": "",
    "use_official_api": False,
    "require_api_key": False,
    "results": "JSON",
}

categories = ["general", "query correction"]
paging = False
send_accept_language_header = False

base_url = ""
enable_http = False
api_path = "/v1/correct"
max_query_length = 80
max_correction_length = 256
timeout = 1.0

_ALLOWED_FORMAT_CHARACTERS = frozenset(("\u200c", "\u200d"))
_HTTP_WARNING_INTERVAL = 300.0
_HTTP_WARNING_LOCK = threading.Lock()
_last_http_warning = float("-inf")


def _normalized_query(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _without_allowed_format_characters(value: str) -> str:
    return "".join(char for char in value if char not in _ALLOWED_FORMAT_CHARACTERS)


def _is_equivalent_correction(correction: str, original_query: str) -> bool:
    correction_key = _normalized_query(correction)
    original_key = _normalized_query(original_query)
    if correction_key == original_key:
        return True

    if _without_allowed_format_characters(correction_key) != _without_allowed_format_characters(original_key):
        return False

    correction_format_count = sum(char in _ALLOWED_FORMAT_CHARACTERS for char in correction_key)
    original_format_count = sum(char in _ALLOWED_FORMAT_CHARACTERS for char in original_key)
    return correction_format_count < original_format_count


def _now() -> float:
    return time.monotonic()


def _log_http_failure(status_code: int) -> None:
    global _last_http_warning  # pylint: disable=global-statement

    with _HTTP_WARNING_LOCK:
        now = _now()
        if now - _last_http_warning >= _HTTP_WARNING_INTERVAL:
            logger.warning(
                "query corrector returned HTTP %s; repeated warnings are suppressed for %.0f seconds",
                status_code,
                _HTTP_WARNING_INTERVAL,
            )
            _last_http_warning = now
        else:
            logger.debug("query corrector returned HTTP %s", status_code)


def setup(_engine_settings: dict[str, t.Any]) -> bool:
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise ValueError("query corrector base_url must be an absolute HTTP(S) URL")
    if parsed_url.scheme == "http" and not enable_http:
        raise ValueError("query corrector HTTP base_url requires enable_http: true")
    if not api_path.startswith("/"):
        raise ValueError("query corrector api_path must start with '/'")
    if max_query_length < 1:
        raise ValueError("query corrector max_query_length must be greater than zero")
    if max_correction_length < 1:
        raise ValueError("query corrector max_correction_length must be greater than zero")
    return True


def request(query: str, params: "OnlineParams") -> None:
    query = query.strip()
    if not query or len(query) > max_query_length:
        params["url"] = None
        return

    payload: dict[str, str] = {"query": query}
    language = params["searxng_locale"]
    if language not in ("", "all", "auto"):
        payload["language"] = language

    params["method"] = "POST"
    params["url"] = base_url.rstrip("/") + api_path
    params["json"] = payload
    params["headers"]["Accept"] = "application/json"
    params["raise_for_httperror"] = False


def response(resp: "SXNG_Response") -> EngineResults:
    results = EngineResults()

    if not 200 <= resp.status_code < 300:
        _log_http_failure(resp.status_code)
        return results

    try:
        payload_obj = t.cast(object, resp.json())
    except ValueError:
        return results

    if not isinstance(payload_obj, dict):
        return results

    payload = t.cast(dict[str, object], payload_obj)
    correction = payload.get("correction")
    if not isinstance(correction, str):
        return results

    correction = correction.strip()
    original_query = resp.search_params["query"].strip()
    if (
        not correction
        or len(correction) > max_correction_length
        or _is_equivalent_correction(correction, original_query)
        or any(token[0] in "!:<" for token in correction.split())
        or any(
            (char.isspace() and char != " ")
            or (unicodedata.category(char).startswith("C") and char not in _ALLOWED_FORMAT_CHARACTERS)
            for char in correction
        )
    ):
        return results

    results.add(results.types.LegacyResult(correction=correction))
    return results

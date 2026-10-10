#!/usr/bin/env python3
"""Read-only discovery helper for a locally running Wan2GP/Gradio server."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MAX_RESPONSE_BYTES = 2_000_000
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_local_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("URL must point to localhost (127.0.0.1, localhost, or ::1) using HTTP(S)")
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials in the local URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Query strings and fragments are not accepted in the base URL")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def get_json(base_url: str, path: str, timeout: float) -> tuple[int, Any]:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    url = base_url.rstrip("/") + path
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "wan2gp-api-inspector/1.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return response.status, {"_response_too_large": True, "limit_bytes": MAX_RESPONSE_BYTES}
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return response.status, {"_non_json_response": True}
            if not isinstance(parsed, (dict, list)):
                return response.status, {"_unexpected_json_type": type(parsed).__name__}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        return exc.code, {"_http_error": str(exc.reason)[:200]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        # Avoid echoing the full URL, which could contain local/private details.
        message = str(reason if reason is not None else type(exc).__name__)[:240]
        return 0, {"_connection_error": message}


def component_label(component: Any) -> dict[str, Any]:
    if not isinstance(component, dict):
        return {"id": None, "type": "unknown"}
    props = component.get("props") if isinstance(component.get("props"), dict) else {}
    result: dict[str, Any] = {
        "id": component.get("id"),
        "type": component.get("type") or component.get("component"),
    }
    # Labels help identify controls; intentionally omit values/defaults and data.
    for key in ("label", "info"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value[:160]
    return result


def summarize_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {"format": "unrecognized", "top_level_keys": []}
    components = config.get("components", [])
    by_id: dict[Any, Any] = {}
    if isinstance(components, list):
        by_id = {
            item.get("id"): item for item in components
            if isinstance(item, dict) and item.get("id") is not None
        }
    dependencies = config.get("dependencies", [])
    endpoints = []
    if isinstance(dependencies, list):
        for dep in dependencies:
            if not isinstance(dep, dict):
                continue
            inputs, outputs = dep.get("inputs", []), dep.get("outputs", [])
            endpoints.append({
                "api_name": dep.get("api_name"),
                "trigger": dep.get("trigger"),
                "inputs": [component_label(by_id.get(item)) for item in inputs] if isinstance(inputs, list) else [],
                "outputs": [component_label(by_id.get(item)) for item in outputs] if isinstance(outputs, list) else [],
                "queue": dep.get("queue"),
            })
    return {
        "version": config.get("version"),
        "mode": config.get("mode"),
        "api_prefix": config.get("api_prefix"),
        "component_count": len(components) if isinstance(components, list) else None,
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7860", help="Local Wan2GP URL (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        base_url = validate_local_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))

    parsed = urllib.parse.urlsplit(base_url)
    safe_display_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    report: dict[str, Any] = {"base_url": safe_display_url, "checks": {}}
    config_status, config = get_json(base_url, "/config", args.timeout)
    report["checks"]["/config"] = {
        "http_status": config_status,
        "metadata": summarize_config(config) if config_status == 200 else config,
    }
    for path in ("/info", "/openapi.json"):
        status, data = get_json(base_url, path, args.timeout)
        item: dict[str, Any] = {"http_status": status}
        if status == 200 and isinstance(data, dict):
            item["top_level_keys"] = list(data.keys())[:40]
            if path == "/openapi.json":
                paths = data.get("paths", {})
                item["paths"] = list(paths.keys())[:100] if isinstance(paths, dict) else []
        else:
            item["result"] = data
        report["checks"][path] = item

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if config_status != 200:
        print(
            "\nNo readable /config endpoint. Start Wan2GP and confirm its local URL. "
            "The inspector accepts loopback URLs only; do not expose Wan2GP publicly.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only discovery helper for a locally running Wan2GP/Gradio server.

This script does not submit jobs, upload files, or print component default values.
It only inspects public Gradio metadata so the adapter can be mapped to the
installed Wan2GP version instead of guessing API names and input order.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def get_json(base_url: str, path: str, timeout: float) -> tuple[int, Any]:
    url = base_url.rstrip("/") + path
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "wan2gp-api-inspector/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(8_000_000)
            try:
                return response.status, json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return response.status, {"_non_json_response": True}
    except urllib.error.HTTPError as exc:
        return exc.code, {"_http_error": exc.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"_connection_error": str(exc)[:300]}


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
        return {"format": "unrecognized", "top_level_keys": list(config)[:30] if isinstance(config, dict) else []}

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
            api_name = dep.get("api_name")
            inputs = dep.get("inputs", [])
            outputs = dep.get("outputs", [])
            endpoints.append({
                "api_name": api_name,
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
    parser.add_argument(
        "--url", default="http://127.0.0.1:7860",
        help="Base URL of the local Wan2GP/Gradio server (default: %(default)s)",
    )
    parser.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    report: dict[str, Any] = {"base_url": base_url, "checks": {}}
    config_status, config = get_json(base_url, "/config", args.timeout)
    report["checks"]["/config"] = {
        "http_status": config_status,
        "metadata": summarize_config(config) if config_status == 200 else config,
    }

    for path in ("/info", "/openapi.json"):
        status, data = get_json(base_url, path, args.timeout)
        item: dict[str, Any] = {"http_status": status}
        if status == 200 and isinstance(data, dict):
            # Keep only useful schema names, never dump all values or descriptions.
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
            "\nNo readable /config endpoint. Start Wan2GP first and confirm its local URL; "
            "do not expose the server publicly.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

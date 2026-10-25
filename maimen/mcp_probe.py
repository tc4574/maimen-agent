"""Discover real MCP tools; optionally call only the two public-data smoke tools."""
import argparse
import asyncio
import importlib.metadata
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .adapters.mcd import ENDPOINT, SMOKE_TOOLS, call_smoke_tool, connect, discover, load_token


def write_private_report(path, report, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(rendered.replace(token, "[REDACTED]"), encoding="utf-8")


def safe_error_types(error):
    errors = [type(error).__name__]
    for child in getattr(error, "exceptions", ()):
        errors.extend(safe_error_types(child))
    return sorted(set(errors))


def tool_status(result):
    if result.is_error:
        return "tool_error"
    payload = result.structured_content
    # The two observed McDonald's APIs carry their own business status envelope.
    if not isinstance(payload, dict) or "success" not in payload or "code" not in payload:
        return "unverified_response"
    return "success" if payload["success"] is True and payload["code"] == 200 else "business_error"


async def run(smoke, report_path):
    token = load_token()
    report = {
        "source": "live_mcp", "endpoint": ENDPOINT,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sdk_version": importlib.metadata.version("mcp"),
        "status": "pending", "tool_calls": [], "tools": [],
    }
    started = time.monotonic()
    try:
        async with asyncio.timeout(90):
            async with connect(token) as client:
                tools = await discover(client)
                report["protocol_version"] = client.protocol_version
                report["tools"] = [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools]
                report["tool_count"] = len(tools)
                print(f"MCP connected; discovered {len(tools)} tools.", flush=True)
                if smoke:
                    for name in sorted(SMOKE_TOOLS):
                        tool = next((tool for tool in tools if tool.name == name), None)
                        if tool is None or tool.input_schema.get("required"):
                            report["tool_calls"].append({"name": name, "status": "skipped_requires_schema_review"})
                            continue
                        call_started = time.monotonic()
                        result = await call_smoke_tool(client, name, {}, tools)
                        status = tool_status(result)
                        report["tool_calls"].append({
                            "name": name, "status": status,
                            "elapsed_ms": round((time.monotonic() - call_started) * 1000),
                            "result": result.model_dump(mode="json", by_alias=True, exclude_none=True),
                        })
                        print(f"Read-only call {name}: {status}.", flush=True)
                report["status"] = "connected"
                if smoke:
                    report["smoke_passed"] = all(c["status"] == "success" for c in report["tool_calls"])
    except Exception as error:
        # Raw server/network exception strings may contain request details.
        report["status"] = "failed"
        report["error_types"] = safe_error_types(error)
        print("MCP probe failed: " + ", ".join(report["error_types"]), flush=True)
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    write_private_report(report_path, report, token)
    print("Local report written; credentials omitted.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--report", default="artifacts/local/mcp-probe.json")
    args = parser.parse_args()
    # Keep SDK transport logs from disclosing server-controlled response details.
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(run(args.smoke, args.report))
    except (ValueError, ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as error:
        print("Probe setup failed: " + type(error).__name__ + ". Check local credentials and MCP dependencies.")
        raise SystemExit(2) from None
    raise SystemExit(0 if report["status"] == "connected" and report.get("smoke_passed", True) else 1)


if __name__ == "__main__":
    main()

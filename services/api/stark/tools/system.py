"""API-host diagnostics (psutil), used by the dashboard's Diagnostics page. No agent has this tool."""

from __future__ import annotations

import asyncio
import os
import platform
import time

import psutil
from pydantic import BaseModel, Field

from ..core.tool_registry import Risk, Tool, ToolResult


def _gb(n: float) -> float:
    return round(n / 1024**3, 2)


class MetricsInput(BaseModel):
    top_n: int = Field(8, ge=1, le=30)
    sample_seconds: float = Field(1.0, ge=0.2, le=5.0)


class SystemMetrics(Tool):
    id = "system.metrics"
    category = "diagnostics"
    description = ("Collect real metrics from the machine running the STARK OS API: CPU, memory, disk, load, "
                   "uptime and the most resource-intensive processes.")
    Input = MetricsInput
    risk = Risk.READ
    timeout_s = 20

    async def run(self, args: MetricsInput, ctx) -> ToolResult:
        return await asyncio.to_thread(self._collect, args)

    def _collect(self, args: MetricsInput) -> ToolResult:
        procs = []
        for p in psutil.process_iter(["pid", "name", "username"]):
            try:
                p.cpu_percent(None)
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        cpu_total = psutil.cpu_percent(interval=args.sample_seconds)
        rows = []
        for p in procs:
            try:
                with p.oneshot():
                    rows.append({"pid": p.pid, "name": p.info.get("name") or "?",
                                 "cpu_percent": round(p.cpu_percent(None), 1),
                                 "memory_mb": round(p.memory_info().rss / 1024**2, 1)})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        disks = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype in {"squashfs", "tmpfs", "devtmpfs", "overlay"} or part.mountpoint.startswith("/snap"):
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append({"mount": part.mountpoint, "total_gb": _gb(u.total), "used_percent": u.percent})
        try:
            load = [round(x, 2) for x in os.getloadavg()]
        except (AttributeError, OSError):
            load = None
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        data = {
            "host": {"os": platform.system(), "release": platform.release(), "arch": platform.machine(),
                     "python": platform.python_version(), "cpu_count": psutil.cpu_count(),
                     "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1)},
            "cpu_percent": cpu_total,
            "load_avg": load,
            "memory": {"total_gb": _gb(vm.total), "used_percent": vm.percent, "available_gb": _gb(vm.available),
                       "swap_used_percent": sw.percent},
            "disks": disks[:8],
            "top_cpu": sorted(rows, key=lambda r: r["cpu_percent"], reverse=True)[: args.top_n],
            "top_memory": sorted(rows, key=lambda r: r["memory_mb"], reverse=True)[: args.top_n],
            "process_count": len(rows),
            "battery_percent": battery.percent if battery else None,
        }
        warnings = []
        if cpu_total > 85:
            warnings.append(f"CPU at {cpu_total}%")
        if vm.percent > 85:
            warnings.append(f"memory at {vm.percent}%")
        if sw.percent > 50:
            warnings.append(f"swap at {sw.percent}%")
        for d in disks:
            if d["used_percent"] > 90:
                warnings.append(f"disk {d['mount']} at {d['used_percent']}%")
        data["warnings"] = warnings
        return ToolResult(True, f"CPU {cpu_total}%, memory {vm.percent}%, {len(rows)} processes"
                          + (f"; warnings: {', '.join(warnings)}" if warnings else ""), data)


TOOLS = [SystemMetrics()]

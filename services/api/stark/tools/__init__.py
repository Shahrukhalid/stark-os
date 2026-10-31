"""Tool catalogue. Every tool registered here is implemented and covered by tests."""

from __future__ import annotations

from ..config import Settings
from ..core.tool_registry import ToolRegistry
from . import delegation, filesystem, memory_tools, security, social, system, web


def build_registry(settings: Settings) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in [*social.build(settings), *web.build(settings), *filesystem.TOOLS, *security.TOOLS,
                 *memory_tools.TOOLS, *delegation.TOOLS, *system.TOOLS]:
        reg.register(tool)
    from ..growth import GenerateImage  # imported here: growth itself uses the social tools

    reg.register(GenerateImage(settings))
    from ..hub import LibraryList

    reg.register(LibraryList())
    return reg

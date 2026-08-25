"""Installable plugin manifests, lifecycle, and capability registration."""

from .installer import PluginInstaller
from .loader import load_plugin
from .manager import PluginManager
from .models import InstalledPlugin, PluginCapabilities, PluginHookSpec, PluginManifest, PluginTrace

__all__ = [
    "InstalledPlugin",
    "PluginCapabilities",
    "PluginHookSpec",
    "PluginInstaller",
    "PluginManager",
    "PluginManifest",
    "PluginTrace",
    "load_plugin",
]

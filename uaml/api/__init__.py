# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML REST API — HTTP interface for dashboards and integrations."""

from uaml.api.client import UAMLClient, UAMLClientError
from uaml.api.server import APIServer

__all__ = ["APIServer", "UAMLClient", "UAMLClientError"]

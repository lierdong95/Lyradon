# SPDX-License-Identifier: MIT
# Optional entry point; does not register a scheduled task.
& (Join-Path $PSScriptRoot 'scripts\manage_services.ps1') -Action Start

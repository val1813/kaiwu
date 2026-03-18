---
name: kaiwu-doctor
description: Diagnose kaiwu MCP server connection and configuration
allowed-tools: Bash
---

Run the kaiwu doctor CLI command to check the health of the kaiwu installation.

Execute this command:

!`python -m kaiwu.cli doctor`

Report the results to the user. If there are failures, suggest running with `--fix`:

!`python -m kaiwu.cli doctor --fix`

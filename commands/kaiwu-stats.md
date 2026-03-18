---
name: kaiwu-stats
description: View kaiwu experience/error knowledge base and usage statistics
allowed-tools: Bash
---

Run the kaiwu stats CLI command to show statistics about the knowledge base.

Execute this command:

!`python -m kaiwu.cli stats`

Present the results in a clear format to the user, highlighting:
- Usage quota (calls today vs limit)
- Error knowledge base size (total, solved, unsolved)
- Experience library size (total, success, fail, top types)

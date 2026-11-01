# External tooling

Status: Active
Purpose: the third-party tools this framework's posture assumes, and what each one is for.
None of them ship here and none are required. OliverCode runs standalone.

They are listed because OliverCode's verification rules were written on a machine running
these, and a few of the rules read as arbitrary without them.

## Claude Code plugins

| Tool | What it does | Install |
|---|---|---|
| [codeburn](https://github.com/getagentseal/codeburn) | Local token-usage, cost, and health dashboard across AI coding tools. Reads session data from disk, with no proxy and no API keys. | per repo README |

## Writing and documentation

| Tool | What it does | Install |
|---|---|---|

## Frontend and design references

No frontend skills are installed. Fetch these per task when a UI request needs them.

| Tool | What it does | Install |
|---|---|---|
| [claude-code-ui-agents](https://github.com/mustafakendiguzel/claude-code-ui-agents) | Frontend prompt library in plain markdown, fetched per task. | reference only |
| [Ant Design](https://github.com/ant-design/ant-design) | Component-API and design-token sanity reference. | reference only |


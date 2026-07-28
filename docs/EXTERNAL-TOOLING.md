# External Tooling

Status: Active
Purpose: the third-party tools this framework's posture assumes, and what each one is for.
None of them ship here and none are required. OliverCode runs standalone.

They are listed because the token-optimization and verification rules in `CLAUDE.md` were
written on a machine running these, and a few of the rules read as arbitrary without them.

## Claude Code plugins

| Tool | What it does | Install |
|---|---|---|
| [fablize](https://github.com/fivetaku/fablize) | Enforces completion-with-evidence, verification grounding, and systematic investigation as procedure. The enforcement-side complement to this repo's instruction-side practice rules. | `/plugin marketplace add fivetaku/fablize` then `/plugin install fablize` |
| [caveman](https://github.com/JuliusBrussee/caveman) | Compresses agent chat output by roughly 65% at full technical accuracy. Pair it with a `## Voice` section in your `CLAUDE.md`; this repo's own is the worked example. | Claude Code plugin marketplace |
| [codeburn](https://github.com/getagentseal/codeburn) | Local token-usage, cost, and health dashboard across AI coding tools. Reads session data from disk, with no proxy and no API keys. | per repo README |

## Frontend and design references

Routing between these lives in the `frontend-ui-references` skill, which sits in the vault's
`.olivercode/user-skills/` rather than here: design and UI routing is outside this
framework's declared scope (`docs/FRAMEWORK_BOUNDARY.md`).

| Tool | What it does | Install |
|---|---|---|
| [taste-skill](https://github.com/Leonxlnx/taste-skill) | Anti-slop frontend design skills, 13 of them, installed selectively. `design-taste-frontend` and `full-output-enforcement` carry the weight. | `npx skills add https://github.com/Leonxlnx/taste-skill` |
| ui-ux-pro-max-cli | Broader design-asset suite of 7 skills. `ui-styling` (shadcn/Tailwind implementation) carries the weight. | npm |
| [claude-code-ui-agents](https://github.com/mustafakendiguzel/claude-code-ui-agents) | Frontend prompt library in plain markdown, fetched per task. | reference only |
| [Ant Design](https://github.com/ant-design/ant-design) | Component-API and design-token sanity reference. | reference only |

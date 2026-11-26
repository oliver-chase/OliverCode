# {{REPO}} agent rules

This private repo holds one person's OliverCode fleet: the registry (`repo-profiles.json`), the owner rules (`owner-rules.json`), the owner queue (`owner-queue.jsonl`), the backlog config (`backlog-config.json`) and the recurring review settings (`review-config.json`: schedule, conform, boardSweep, updateCheck, alwaysUpToDate). The engine lives in the public OliverCode repo and holds none of this.

Rules:
- Keep this repo private with no collaborators, and never copy its files into the engine
- Register a repo by adding it to `repo-profiles.json`, and fill `backlog-config.json` from `gh project field-list`

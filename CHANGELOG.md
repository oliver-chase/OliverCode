# Changelog

Each section is one release, cut by `olivercode version-cut` from the rules in `docs/VERSIONING.md`.

## 3.0.0 - 2026-11-25

Breaking: 24 changes removed or renamed something a user or fleet repo relies on.

### #1
- fix(hooks): lint joined paragraphs so hard-wrapping cannot hide long sentences (28434b4)

### #2
- fix(health): require ste-lint-joined.py only where the hook calls it (05be134)

### #8
- Harness: install writes Claude Code's session, commit and stop hooks (2dd8e89)

### #14
- Separation: the real fleet registry moves to a private repo (07e8cae)

### #15
- Separation: no personal names, paths or business data in shipped files (67aa7b7)

### #16
- Separation: private repos replace the built-in vault (97ba56c)

### #17
- Skills: board-hygiene, plan-pressure-test and skill-creation join the harness (358e98f)
- Skills: skill-fleet-audit joins the harness, its fleet data stays with the fleet (8f5d92f)

### #19
- CLAUDE.md: triggers and pointers only (490ebfd)

### #20
- One home for gate lists, counts and the fail-open warning (027e411)

### #21
- One home for the install steps (5c470d7)

### #22
- Contradictions: one answer each (cc9daf8)

### #24
- Overlap: one audit skill and one QA entry point fewer (71150ed)

### #26
- References: fix the broken ones and check $OC paths (9b83e0d)

### #28
- Dead parts: remove what nothing reads, document what has no instructions (dd740d4)
- Checks: drop a dead exemption and a duplicated banner check (cad67b7)

### #29
- Health: report the local scheduler and cover every repo in use (09431b1)

### #30
- Validate: scan the whole tree, and do it in CI (5f32950)

### #31
- Early-stop guard: a turn that asked the owner is waiting, not stopping early (7a4ad27)

### #35
- One decision ledger (ab9e6bd)

### #36
- One repo registry (e93e321)

### #37
- One CLAUDE.md template for a governed repo (60edd30)

### #38
- Generate the three pre-commit hooks from one gate list (9d0ebd6)

### #43
- Delete features nothing uses (e69bb4d)
- Fix the audit findings: QA check, commit-msg matching, validate scope, docs (431c099)

### #44
- Make VOICE.md the only writing standard (dc9eb8a)

### #46
- Merge backlog-management and board-hygiene into one backlog skill (27116e6)

### #47
- Reduce the documents to one home per question (3910b5a)

### #48
- Tests: remove duplicates, isolate git config, halve the runtime (a8a6c45)

### #49
- Route work to the smallest fitting model and have the lead check it (55547c8)

### #51
- Define the kanban baseline with no PR lane (35d6a3c)

### #52
- Save every owner ask as a story with Gherkin criteria (ef2e208)

### #53
- Require a story reference on every commit and log agent actions (12fae9e)

### #54
- Require independent QA before a story is Complete (14b4da6)

### #55
- Add one repeatable backlog setup and repair command (0dffcb2)
- Log backlog-setup repairs to a story and make the clone rehearsal use the real origin (3f8c05c)

### #61
- Generalize the line-wrap rule wording in skill-creation (231d36c)

### #62
- Restore the pause-and-ask procedure for working a backlog item (daa1d83)

### #63
- Audit reports size, test and doc ratios and open work through size.sh (aabc17d)

### #64
- Survive a hung scheduler job, stop the audit rerun loop, refuse wrapped --no-verify, fit the backlog description (4e0bcab)

### #65
- Delete the parts nothing uses (c9d9cbd)

### #66
- Fold two small neighbors into the skills that own them and finish the unused-parts deletion (cf4c083)

### #67
- Ship bootstrap files that work on a new repo (a09b805)

### #68
- Docs state only what the code enforces: commit rules, skill-creation citations, QA lane ID, PII and icon scope (c2511a8)
- Remove the duplicate QA key the docs story added to the board config (b548d60)

### #69
- Scope the every-ask story rule to repos with a backlog and restore the memory clause (4e6b0b8)

### #70
- The commit gate runs every test and the untested commands get one (7ebc0bb)

### #71
- One home for shared script logic (188f79d)

### #72
- Shorten the backlog skill and have the agent find its config (7daf246)

### #73
- README leads with a conversation and keeps one home per setup fact (3ab44ff)

### #74
- Rewrite contrast framing and strip history from reader text (4d55051)

### #75
- Skip the board check when a checkout has no origin remote (5c789c8)

### #76
- Make the board hygiene config test fork-safe and remove the stale Area option (ac00125)

### #78
- Add a size ratchet: a repo's line count may fall but never rise past its baseline (691f00e)

### #79
- Block owner identifiers derived from git in shipped files (c81f572)

### #80
- Run one duplication check on docs, skills and references in the commit hook (1efe734)

### #83
- Audit: prove use, test necessity and existing tools (b356e28)

### #84
- Delete the unattended scheduler and push-fleet, which never ran (fd0b35b)

### #86
- Remove gates that cannot name a defect they prevented (e22ce43)

### #87
- Prune tests that protect nothing (1a3b43f)

### #90
- Record the hook distribution decision (228b70e)
- Trim the board sweep to four dimensions (#85) and record the hook distribution decision (3211e47)

### #117
- Add the contract of what every repo must match (#107) (ab943bc)

### #119
- Skip non-regular files in the bloat check line count (#118) (4997cac)

### #120
- Add olivercode conform and move the repo checks out of health (#108) (efbe249)

### #121
- Audit: fleet budgets, voice lines and board drift (#95); correct the hook decision's counts (#90) (393c43d)

### #122
- Isolate tests from real HOME and local config, run from a clean clone, stop installing the inert private hook copy (#112 #110 #115 #113) (1c7b9b4)

### #123
- Shrink backlog_setup.py by 200 lines to the paths the repair used (#88) (87608d2)

### #124
- Gate verdicts, size-baseline raise cap and a thin launcher (#86, #81, #89) (f085e32)

### #126
- Cut duplicate tests, set the test budget and record the baseline (#87, #94) (703c4ca)

### #127
- Fleet location check, duplicate removal, audit timing line, hook test (#114, #125, #94, #113, #96) (e84e386)

### #128
- Rewrite contrast framing and teach fleet_check to skip quoted phrases (#96) (f8fd32b)

### #129
- Retire planning-doc governance templates and manual CI templates (#111, #82, #91) (3d35b54)

### #134
- QA that fits the change: batched reports, note-tolerant sign-off, mechanical tier (#131 #132) (27b23cb)

### #135
- Skip Anthropic session authors in the owner-identifiers gate (#133) (4d0b851)

### #142
- Stop naming session authors in the owner-identifiers gate comment (#133) (dff5714)

### #143
- Sessions that spend tokens on the work: small changes, scaled audit, short replies, narrower stop hook (#137 #138 #139 #140) (611821a)

### #144
- Let a repo declare its own reuse in the shared duplicate-text check (#80) (a22c6e1)

### #146
- Read the size baseline by key so a one-line file works (#145) (8e99c73)

### #147
- Rules: after QA, merge to the default branch and push with no pull request (d72ba21)

### #148
- Gates read staged content under each file's real name (811849a)

### #149
- Refuse an abbreviated --no-verify and a same-line hooksPath change (c642d6a)
- Tighten two hook refinements found in QA (4ad7822)

### #150
- Secret gate catches current credential formats and the size ratchet reads its allowance from HEAD (4971db4)

### #151
- Stop hook ignores a conditional promise in the closing sentence (a63042d)

### #152
- Delete the parts nothing uses: evidence-gate prose, D2 and BACKLOG-HYGIENE-1, the waiver check, the fleet audit log and four dead markers (92a29ad)
- The gate-count check reads a claim's hook from its own line and drops the paragraph-context resolver (3fc6933)

### #153
- Backlog and audit scripts match their skills: no-Status cards flagged, single-word skill names, the repo's own config, a failed board read reported (d5e6246)

### #154
- Docs match the code: bypasses named, no phantom citations or re-exports, the full suite command, current decision sizes (33ca919)
- The backlog skill cites no prioritization doc and GATE-PRUNE-1 matches GATES.md (205e1ac)
- health_checks names the checks it holds and REGISTRY-PRIVATE-1 drops waivers (69fb477)

### #155
- Tests that guard: Gate 1's exit, board paging, config_problems, the email local part and every command's extra-word refusal now fail when removed; hand-edit tests merged; pass checks name no gate number (2b151d1)
- Tests assert exit codes and one key token, the no-verify tests are one, and staged-content cases run once on the built hook (4efd775)
- Tests that guard: refusal tests for discover, size and conform, one key token per assert, and the guard tests folded into three tables (8470066)

### #156
- Reader text follows the voice: the checker sees ', not a' and 'not X but Y', contrast and incident comments rewritten (02e2456)

### #157
- A first run that finishes: the probe sets a run-only identity, bootstrap fills the owner and orchestration repo, no template names an npm script, the repo check reads tracked files (1464e23)
- README names the clone (2320f3c)
- Bootstrap checks the orchestration fill only with an origin, fills the repo name and says which placeholder it could not fill (7fada19)
- README names the clone URL, declared as local data for the identifier gate (6ba5e1a)

### #158
- Trim CLAUDE.md to four rules; process runs on request (a39609d)

### #159
- Close the gate gaps: no secret path exemption, staged citations, git -c commit aliases refused, guard limits written down (07354ec)
- Secret gate judges a placeholder by the matched value and the guard reads alias names without case (e14d444)
- The commit guard reads a git -c shell alias as a command line (1755bce)
- The commit guard follows alias chains, shell-function alias bodies and aliases that start with global options (fb738aa)
- The commit guard ends alias loops by name, follows chains of any length and reads "$@" and $N in shell aliases (38be546)
- The commit guard reads braced parameters, alias redefinitions and --config-env aliases (12730c3)

### #160
- The backlog skill adds each filed issue to the board itself and checks it (9772a44)

### #161
- Add the backlog skill's method for finishing a backlog with several agents (73826d7)
- Name the size baseline script without a path OliverCode itself lacks (17c43d1)

### #163
- The global rules and RULES.md agree: change requests are filed as stories and QA runs in the same turn (d659d41)
- Stories close on the builder's evidence after validation, independent QA runs on request, and nightly syncs commit under a standing story (23a82cc)
- No QA phase and no pull request: the builder commits, pushes and merges at the end of the work (007cb7c)
- No QA phase and no pull request, stated once in RULES.md (ae68fed)

### #169
- Backlog skill: match RULES on branches, drop the unscheduled weekly sweep, default the config path and dimensions, scrub repo names (a458145)
- Fold the backlog skill text checks into the story-format test to hold the test budget (46810fa)

### #172
- Gate docs/BUDGET.json in validate.sh and bring the counts within budget (5914530)

### #174
- Plan skill: dated filename, no vault wording, claims check points at the audit plan route (53fadcc)

### #175
- olivercode-adoption links SETUP.md traps, discovers the validation command and hook variant, and the audit skill owns 'audit my Claude config' (726734d)

### #176
- skill-creation: rules 8, 9 and 12 match shipped skills, the automation section is cut and the checker runs through $OC (4ea79cd)
- skill-creation names the checker through $OC in both places (26140c8)

### #177
- Audit skill: one script path style, no stale worked example, aliased imports count as tested (0323a7a)
- The Reviewed-through marker has one home in docs/BACKLOG.md and states what is unreviewed (5026657)
- Trim the coverage note to hold the doc word budget (92b2f2b)
- The changes route scopes its range from the Reviewed-through line in docs/BACKLOG.md (7e1acfb)

### #178
- diagnosing-bugs cites only what exists and drops jargon and contrast framing (c783c6c)

### #186
- The board sweep reads Work type in any spelling (9c5459e)

### #189
- Reject story numbers that do not exist and close stories through the QA check (f52730e)
- Close script runs from the command line: buffer the QA check in a StringIO (be2328a)

### #195
- A raised size baseline must equal the counted total (8e183c4)

### #196
- The commit-msg gate requires a test change or a 'No test:' reason with every code change (3a5d67c)

### #197
- Every co-author line has one form, merges and cherry-picks included (98df68a)

### #198
- Commit messages follow the voice, and the CLI strings drop contrast framing (584d725)

### #204
- The fleet check names every pull-request merge on the default branch (45a0863)

### #205
- One re-runnable commit audit: each finding class with its count and the change since the last run (6461c09)

### #206
- Board sweep grooms the board: built work left in Ready, lagging epics and overlapping stories (6c25be4)

### #207
- The commit-msg gate reads a one-line size baseline by key (58bda0b)

### #208
- A story that reaches QA gets an independent QA agent in the same turn, and a session start names any story still in QA (66703cd)

### #212
- Rewrite README for first-day readers (ee5a8cb)
- Keep README bullets concise (7504edd)

### #224
- Add olivercode guide and list every command in the README (1b9c46e)
- Keep skills/INDEX.md the only skill catalog; README points to it (3756ee4)

### #225
- The audit files every finding and simplification, and sets a size target (2810fb7)

### #226
- Count staged lines in one pass and let a project name itself in the identifier gate (1e762d7)
- Run the project-name filter only on a file that has a candidate (839801b)

### #227
- Offer the workflow and CODEOWNERS once and stop requiring .github, so a clean repo passes conform and its own validation (ad79ff9)

### #230
- SessionStart names runaway test processes and machine overload (bfc6836)

### #232
- The emoji gate skips caption ledgers under data (e549046)

### #233
- Add the failure log, learning proposals, weekly report, replayable tasks and eval commands, agent jobs, releases, memory and version health, the activation-link check and the voiceFile override (54e7a2a)
- Cut the eval layer, the weekly report and the release command, and let learn --accept just record the proposal (e02813a)

### #261
- Add olivercode maintain: check the machine and repair dangling links, dead worktrees and iCloud-evicted git files, on a daily schedule (f7aac02)
- Raise the size baseline to the counted total for the maintenance command, the shared GitHub budget and the restored eval core (cdc6910)
- Shorten the maintain and learn entries in SETUP to fit the document word budget (73d08e5)

### #263
- The emoji gate exemption becomes a per-repo setting (f21b675)

### #264
- Audit sweeps first and files everything; dead code, hook bugs and stale claims fixed (ff51c52)

### #268
- The gh budget tests all sit above the main guard (0e7d0fa)

### #269
- The secret gate skips files that match no pattern and reads each candidate once (0289042)

### #270
- SETUP command list and the decision ledger cut to the rule, the failure and the test (a081938)

### #271
- RULES has one execution sequence and shorter boundary and skill sections (1ed0f8e)

### #272
- The backlog skill's description loads 31 fewer words in every session (133b93d)

### #274
- One PreToolUse hook runs the commit, placement, policy and GitHub guards in a single process (9a09e80)

### #275
- Batch GitHub Project updates (7c0dcc5)
- Refresh backlog state after queue delivery (c97020e)

### #276
- RULES: the guard holds under 500 GraphQL points and refuses per-field edits (e8becf4)

### #277
- Agents hold before GitHub's limit, per-field board edits go to the batch command, and the batch add-card mutation works (e2df315)

### #284
- Maintain clears sync-conflict copies and flags synced roots and stale docs (0ae49c8)

### #286
- The audit prints its report only after check_report.py passes; not-planned closures read as decisions (320f6a2)

### #288
- The size script counts web code as code (e445d0c)

### #289
- Board setup uses the Project a repo already has and plans no second one (d38aa96)

### #290
- Maintain moves .git out of the sync for repos in a synced folder (c36ada1)
- Protected repos ignore .git.nosync and are not counted as stray worktrees (d74da4b)
- Maintain restores a .git link that a sync service renamed (9812c71)
- Maintain clears the .git N folders a sync service leaves beside the protected link (99a5e29)
- A slow repo no longer stops the maintain run (69128be)
- Maintain downloads an evicted copy and its original, then compares them before clearing the copy (b7ecb9b)

### #293
- Every gh call counts against a shared per-minute cap, and reading a backlog script is no longer treated as a gh call (f960a02)

### #294
- Every config file and the secret patterns describe themselves, and the catalog is rebuilt (2f763f5)
- The owner's #294 decisions are recorded: a 600-second test budget, the accepted history and size rows, and a portable sharing verdict (0d10eb7)

### #295
- The audit carries a whole repo to done (dc9be67)

### #297
- The commit gates catch what they missed and stop blocking what they should not (5c10f5e)
- The test budget covers the new gate and audit tests (9a3d7cf)
- A placeholder backlog config says how to fill it, PII exemptions live per repo, and an author's name blocks only as a whole phrase (572b0e2)

### #298
- The policy engine denies what it should and allows ordinary work (0f78e35)

### #299
- The audit scripts find history secrets in any case and survive a bad config (f5fe67a)
- conform accepts npm validate and check, discover skips worktrees, report rejects a bad --days, and three docs say what the code does (f94b398)
- Layout accepts the config path CLAUDE.md names, unused variables go, and the points floor reads one default (3fcf6b4)

### #300
- A bad story number leaves the batch queue and QA-required stories close on sign-off (f897fc3)
- One bad issue number no longer drops queued work, skill scripts count as code, the audit reads folders outside git, and the audit skill names its one dependency (482b2f5)

### #301
- Shipped text names no owner and the adoption skill finds its checkout (20272ce)
- The README leads with opening the folder in Claude Code, and discover --register writes the registry (b64bab7)

### #302
- Voice enforcement in commit-msg is opt-in on docs/VOICE.md (5d61830)
- The memory rule fits any checkout, README.md loses its stale identifier exemption, and a duplication reason states today's fact (b6cd6b7)

### #303
- Code, config and tests that nothing runs are deleted (9fefd79)

### #304
- The size allowance and the raise cap each have one home, and hook enforcement's fail-open rule is stated in GATES.md (3c189ff)

### #305
- The docs match the code: no counts in prose, a complete layout table and the right budget, variant and ignore rules (e022ac7)

### #306
- Docs and comments drop contrast framing, dates and history, and the voice check catches "and not the" (bb2d3b6)

### #307
- The project hooks name only what a project repo holds, and a stranger's clone writes no failure log (4741c5b)

### #308
- The audit reads only, and a load guard bounds its work (ea27e8c)
- A busy machine starts half as many audit readers (fafc48d)

### #309
- The done check accepts a clean voice line (2b8931a)

### #310
- A repeat audit reads only what the last audit did not (8ac82ae)

### #311
- The gates read one snapshot of the staged files, the PII gate scans markdown, and a check script counts as its own test (5871eec)

### #316
- validate.sh's fleet step checks only that git runs each repo's gates (3c891e5)

### #318
- An accepted history-secret row matches however long git prints the short hash (ef8b39b)

### #320
- CLAUDE.md: asking for the current OliverCode runs update, health, place and validate and reports each result (1d62f0d)

### #321
- The commit hook's PII scan skips the hook files themselves (5d8895e)

### #322
- Record the audit ledger at the end of epic #322 (cd6d304)
- Record the audit ledger after the catalog change (b606420)

### #323
- The policy and commit guards read a command the way the shell runs it, and the policy cannot be lifted from inside the repo (cc78011)

### #324
- Every content gate scans a renamed file (47bc63b)

### #325
- Code and config that nothing runs are deleted (272ba9b)

### #326
- The done check fails when a helper crashes or the board is not read, and times every test module (27060b6)

### #327
- The harness report counts only gate blocks and refuses arguments it does not know (afb4775)

### #328
- The guide shows the phrases that load each skill (0038546)

### #329
- The launcher, health checks and worktree cleanup report true results (5ecc6e8)

### #330
- Gates, validation and audit scripts report true results (bc7442e)

### #331
- Docs state what the code does (7b7bca4)

### #332
- The catalog lists the launcher and names its generator without a path (691de96)

### #333
- Shipped text names no other repo or dated incident and drops contrast framing (b3cb22d)

### #334
- Each audit test file runs every class when run directly (9244f93)
- Each test is named for what it checks (e012319)

### #335
- The commit gates catch what they claim (73397b3)
- The commit-msg opt-out says every check it turns off (9474bad)

### #336
- Backlog writes report what landed and keep a write that failed for a moment (c4b6d41)

### #337
- The gh guard and sync-hooks cover every case they claim (f1f9297)

### #338
- Tests catch what they name (c393828)

### #339
- Small leftovers from the fresh read say and do what they claim (0e35001)

### #340
- Each helper and check has one home (29f9518)
- An anchored markdown link is checked by its file part (6e8faff)
- The report check fails when a lens in lenses.md has no pattern (99d0715)

### #341
- The catalog lists every script, including .mjs files and the git hooks (ef8b4df)

### #398
- The size ratchet's block message names the repo's own baseline script when it has one, so a merge reruns it instead of choosing between two numbers (86c4486)

### #814
- Conform flags an open OliverCode issue that names a fleet repo (8388831)

### #892
- Holder-lands test patches cmd_land's clock, not the global time.sleep (d816539)

### #893
- Hold every hook refusal and advice to one line of 200 characters with a doc pointer (5631984)

### #894
- Health's ungated-job test asserts a gated and a paused task get no finding at all (bf198a2)

### #896
- The status report and City page show the four revamp numbers (f15a4fc)

### #897
- The commit gate sources and hook builder install the secret, PII, version-file and voice gates for every later commit (a0bd810)
- The duplication, falsifiability, consistency, catalog and QA sign-off checks are removed because the suite checks and the limits ledger cover their job (79054fc)
- Commit gates and hook guards check every commit and tool call for secrets, PII, story references, versions and voice (51e22fc)
- The gate and hook tests cover each gate and guard with passing and failing cases (7a979e4)
- The limits ledger and the version cut keep file sizes, VERSION and CHANGELOG under one record, and a size over the limit warns (c00669c)
- The validation queue runs checks in order, records timings and reuses validated results (8042e4f)
- Landing and worktrees put a story on main with its own worktree, push approval and saved work (47f6b3b)
- The owner queue and decision ledger collect the steps only the owner can take, the decisions made and outsider activity (04a9574)
- The headless runner works through queued stories in agent loops, dispatches them and drains the queue on a schedule (b9e9a89)
- The board, groom and story outbox keep the backlog current and queue story writes while GitHub is busy (b8c11e5)
- Lessons, retro and owner rules capture what went wrong and gate the queue on it (3649616)
- The audit and backlog skills read findings, audit modes and ledgers, and count and check stories (4ab1dae)
- Fleet sync, adoption, machines and the private split keep the engine apart from owner data (ace9699)
- Health, maintain, status and schedules report the state of each machine and run the nightly jobs (296dce5)
- The launcher and CLI register every command and CI runs the checks (3f61646)
- The version, README and docs describe the system as it now stands (a3e30da)
- The changelog describes each capability by its net result in one short entry (0925fef)

### #899
- Guards no longer count a sed script as a file the command writes (f6977b9)

### #902
- A worktree whose built hooks predate its gate sources is stale, so a rebase no longer hides an old gate (bc14430)

### #906
- Drop audit ledger lines for deleted files and guard the leftovers (ca1d379)

### #907
- The docs-cut check and its ledger are removed (54fd115)

### #908
- The audit's reviewer prompt no longer names a lead (db42f66)

### #972
- Install introduces how OliverCode works (8a2d4ba)

### #973
- The owner queue stops refusing repo names that end in Code (4c55ffe)

### #974
- The guide teaches efficient use and a status question is answered from the digest (97abeea)

### #975
- A reader's finding gets its one fix session even in the last round (2a45b82)

### #976
- The run log's start_tokens is the first call's context, read from the transcript (6c6f140)

### #977
- The daily job runs the clean-clone suite and health reports its result (953caa0)

### #978
- A gap for OliverCode's board names no other fleet repo (0947dc8)

### #979
- Status says what the runner is building and warns when it stalls (b30723f)

### #980
- CLAUDE.md holds only what every session needs (bd43caf)

### #981
- Conform checks only what protects a repo (f89bb3a)

### #982
- Board upkeep is one groom job (065808a)

### #983
- Learning is one command and no prompt hook (40b667f)

### #984
- The launcher and the audit skill shed what nothing calls (b5c3961)

### #985
- A new thread starts from the digest and the guide says what everything does (47242a2)

### #988
- A mate whose work landed under a lead is not built again (151b506)

### #990
- A failed City publish round is never named as the last story run (78855f5)

### #992
- One run per repo, whichever thread starts it (41a76fc)

### #993
- Install hands the fleet step the registry's folder, so it no longer crashes on an existing registry (cb02125)

### #994
- Confirm GitHub project access during install (c6aff47)

### #995
- Confirm design override idempotence (a598238)

### #996
- A status page shows what is building, what landed and who owned it (85f16b9)

### #997
- The state folder is kept small (33dd844)

### #998
- A scheduled model job runs only when a check finds work (63de94a)

### #999
- Install sets up City on the desktop and the phone, and the guide repeats it (8f715e1)

### #1000
- A status-only question is blocked with the digest lines and no model turn (76e699b)

### #1001
- City shows the organization, the live work and every open story (292f35f)

### #1003
- City lists the interactive threads beside the builders (0bf5a0a)

### #1004
- A filed story is checked for overlap and missing files with no model (ae685da)

### #1006
- A large audit reads in batched waves until nothing is pending (02ab3c3)

### #1009
- Landing accepts every test file, so a required test no longer throws a build away (fc18b53)
- A commit outside its Files area lands with a note, so no story burns its restarts on a refusal (35a9efe)

### #1010
- Grooming finds gh and a failed board reaches the owner queue (235ad1f)

### #1011
- A story closes only on its own commit, landed once (dca8106)

### #1012
- The runner works in any repo (8ff6d8c)

### #1013
- One rule for who builds, and a board config that names another owner counts as absent (60c3a44)

### #1014
- Drain builds only Ready, sized stories with a Files area and never two that overlap (7a51449)

### #1015
- Every story gets a fresh reader, and the brief names the models the runner starts (beeb4b5)

### #1016
- Builders load only the project's settings by default (673a97b)

### #1017
- A session starts with one status line and no forced read (0f68550)

### #1018
- Hooks act only on real tracebacks, owner steps and imperative memory lines (0ed7a1f)

### #1020
- Status names the right next story and board sync reads once per change (eed7ac5)

### #1024
- Candidates reach the digest and the owner queue holds one self-clearing item per subject (9b4c8ae)

### #1025
- The replay job sends the story outbox (f10ca29)

### #1026
- Model routing follows risk as well as size (40e9b98)

### #1027
- Each audit lens opens with what its findings mean (35e1985)

### #1029
- The engine ships no owner rules, tool names, handles or epic numbers, and the PII gate scans test files (ecd08b3)

### #1031
- Name the reason and the next action where a command skips or fails (0db0672)

### #1032
- Update realigns after a rewritten remote and points hook edits at --story (18ad4ff)

### #1033
- Shared state survives two writers and origin branches are deleted only on the owner's setting (30df144)

### #1034
- Health and conform ask which repo name to keep when folder and origin differ (044f902)
- Keep the guide's job-name change out of #1034's area; it needs its own story (4f581f4)

### #1035
- Clean up what the runner and the commands leave behind (457ae2b)
- Clean up runner branch by story ID (6565a50)
- Cover the stale handover and the init-fleet rerun that #1035 describes (a49ccd3)

### #1037
- Tests that could not fail or never ran now fail or run (082a0d3)

### #1039
- Fix the remaining correctness bugs that still reproduce (f1dd09f)
- Keep story #1039's tests inside its Files area (bb199e6)
- Fix the groom leak match and the cut worktree path (04c98cf)

### #1043
- The audit ledger records the two full audits of 2026-11-23 (2ec2472)
- test_groom stubs the board list that groom actually calls (3492c97)

### #1044
- Every push, permission and gate holds against a builder or a cloned repo (4a62379)

### #1045
- Cleanup and replay never lose or repeat work (c39b748)

### #1046
- Builder briefs carry only recent owner decisions (b42f1c2)

### #1047
- GitHub calls and command errors cost little (9684e14)

### #1048
- A check that cannot see reports unknown (db8121b)

### #1049
- Gates and checks fit any repo (40e7b96)

### #1050
- Install, conform and scheduling work on a fresh or non-Mac machine (540c096)

### #1051
- No shipped file names the engine's owner (#1051, folds #1022) (5b96db1)

### #1052
- The audit skill runs alone and reports correctly (985c0c1)

### #1053
- Versioning, templates and skill docs match the code (e56e2b0)

### #1054
- Remove the 12 functions nothing in the product calls and record the second cut list (9ed3f23)

### #1055
- One machine-wide builder limit replaces the load gate and the slot cap (6f6482d)

### #1057
- Install connects to an existing fleet repo (c76be56)

### #1058
- A policy stop ends a headless story without restarts (1d83edf)

### #1059
- Install and adoption teach the status check (011167c)

### #1061
- Third-party notices name the five adopted sources and their licenses (82962e8)

### #1062
- Audit gains a security route that reports only proven boundary crossings (a44840c)

### #1063
- Every audit finding is confirmed, unproven or rejected by a fresh reader (b67fb68)

### #1064
- Drain skips stories whose blockers are open and a new session fixes every review finding in one commit (2177225)

### #1065
- A script finds the banned design tells, and an edit hook reports the floor ones (2977b06)

### #1066
- DESIGN.md sorts its tells into Floor and Reflex tiers (6fdec2a)

### #1067
- Stories are thin slices with a blocker line, and filing checks rejected ideas (63a3190)

### #1068
- diagnosing-bugs redacts secrets, minimises to load-bearing pieces and proves forced failures (0aee65d)

### #1069
- Builders reuse before writing and simplify never cuts a protection (74b43b9)

### #1070
- skill-creation requires checkable step ends and a no-skill baseline (7b24d5d)

### #1071
- The plan skill asks with recommended answers and reads facts itself (e544564)

### #1072
- Validation keeps only the settings someone sets (ab30cde)

### #1073
- Landing refuses a commit outside its Files area or one that weakens a test (09a8cc6)

### #1074
- The close gate skips issues closed as not planned (dd28e97)

### #1075
- Owner gating reads the owner-action label, never story prose (caa286a)

### #1076
- A stopped drain releases its claims, and status names the right step (f6f5efe)

### #1077
- A Files area names files, so one story never holds the drain to one builder (d3f2211)

### #1078
- A listed file's test is inside its story's Files area (7d2583f)

### #1079
- The fresh reader checks the repo before it holds a story (df34f7b)

### #1080
- Stories that share a file build together, and a rebase conflict says how to fix it (28c2e51)

### #1081
- Status names the folder and the fix when it runs outside a GitHub origin (03ecd5b)

### #1082
- Health fails when ~/.claude/olivercode is missing and names olivercode install (e3c06a2)

### #1083
- The default fleet registry path links to the configured registry, so both read one file (c7842b9)
- An empty fleet registry names the sibling registry that holds the profiles, and the default link is never repointed away from profiles (f8e2a8f)

### #1084
- The drain names the batch session commit once, and a batched story closes on it (dafa88e)

### #1085
- Only the runner validates: a headless builder's full validation is refused (2d710f3)

### #1086
- Building line shows the round out of its limit and counts only this run (c790871)

### #1087
- Priority scale and dependency-aware story order (3325311)
- Priority is one written scale and the build order follows it (1e13d4a)
- Order the plan by unblock count and report only understated priorities (37daabe)

### #1089
- Groom links each duplicate pair and names the story to keep (ada491d)

### #1090
- Groom records what each story unblocks and shares files with (512c24b)

### #1091
- Groom sizes a story from its files and scenarios and files a split story for an L or XL one (d66d583)

### #1092
- Board sync grooms each board after it sweeps (49c970c)

### #1093
- Status shows true build minutes and the real round (f13672e)

### #1094
- Status from a folder with no repo names the OliverCode checkout by path (0586ad9)

### #1095
- Status names each building story's repo and drops closed ones (cb6a18d)

### #1096
- A commit the commit-msg gate keeps blocking returns the story to Backlog with the gate's reason, and each restart is told why (1e401c8)

### #1097
- City's terminal panel shows the commands the owner would type and olivercode status's own live output (ae3c49f)

### #1099
- Grooming links stories to epics within limits and proposes new epics to the owner (7789202)

### #1100
- Grooming closes only exact duplicates and queues every other pair (c7a9af3)

### #1102
- Adoption skill walks a new user through every part of the workflow, one part at a time (a61ab74)

### #1103
- Grooming makes each Blocked-by line match a dependency link, both ways (fe57bc3)

### #1104
- Groom reopens a story closed without complete_story.py evidence (a803fce)

### #1105
- Grooming moves each epic with its stories (9252154)

### #1106
- A second session refuses a held story, and a hand landing waits for the drain (c6a1e4a)

### #1107
- Filing a story stops when its format check reports a missing part (b46207f)

### #1108
- The builder limit starts at 3 and scales with the machine's load, and names why (6ccf3d4)

### #1109
- Grooming links each story to its epic and sets its Area (ab3cbf5)

### #1110
- CLAUDE.md names the board config and its local override (54b2d13)

### #1111
- Routine small stories land on validation alone, and runner waits stop at minutes (534621a)
- A drain stopped by a full machine names the run holding the builders, GATES.md says ten minutes, and the reader-brief guard returns (e6a7b47)

### #1112
- Status names each story's repo, number, size, state and what holds it (bcd0133)

### #1113
- Builder turns follow story size and a spent budget leaves a handoff (23837a7)

### #1114
- The drain reads the board once per pass and rereads only a story that changed (2ca2a22)

### #1115
- Validation slots follow measured run time and load (b77fde8)

### #1116
- The drain restarts on new code after a runner story lands, and a landing stops after five minutes on a claim (d912a46)

### #1117
- Status reads in short sections with one line per story (f5e042a)

### #1118
- Validation pushes a fake story through drain, land and close, so a runner change that stalls the backlog fails before it lands (ad9e35d)

### #1121
- Board updates skip closed issues and report them (ae66296)

### #1122
- Status shows true time and rounds for each building story (3401906)

### #1123
- A story that stops on the turn limit twice is parked, and a Size L or XL story is split before the drain builds it (ed9e573)

### #1124
- Unused commands and modules are removed (60624d3)

### #1125
- health_checks.py and policy.py are each under 400 lines (a81e5a8)

### #1132
- An oversized story never reaches the runner (94743a3)

### #1134
- Groom checks filed stories against each other and moves a split parent to Backlog (4030766)

### #1138
- Exclude headless prompts from owner decision capture (8ab26a2)

### #1140
- Raise undersized Ready stories from their Files area (c5e5c17)

### #1142
- The round check runs only the affected tests (62c4456)

### #1143
- The three slowest test modules share one git fixture per module and skip redundant git calls (c614e68)

### #1146
- run_cli narrows the built-in tool set with --tools and drops skills with --disable-slash-commands (a320dc2)

### #1150
- Add a spend panel to the status page: each day's chat and runner tokens, with speed and waste (334012c)

### #1151
- Dispatch prevents running stories with overlapping Files areas in parallel (15c9bdc)

### #1152
- Count cache and review spend per closed story (217c208)

### #1153
- Accept explicit fresh-reader verdicts (a6731f8)

### #1154
- Hooks reach every repo through one global core.hooksPath that olivercode install sets (7225760)

### #1155
- Small builders get 30 turns and P0 alone calls no reader (2393ce7)
- Run the drain canary at the push to the default branch and leave it out of a full validation (1685c37)

### #1156
- Reverse the builder-validation refusal, scaled builder limit, restart-on-landing and turn-limit parking (e0f5500)

### #1157
- live_check demands a loaded job only for lines a story's commits add or change (a5f622e)

### #1158
- Show why the builder limit dropped in olivercode status (1773f8f)

### #1167
- Align the story-first rules with interactive-first work and fix the clean-clone candidates test (7a7d12d)

### #1168
- Skip the smoke gate in a round that changed only unnamed prose (294ee1d)

### #1177
- The guide shows one example from request to landing, and a test covers the owner step that clears when its check passes (b515420)
- Status, the owner list and the guide put what needs you first, under plain headings (366bfc2)
- Status and the owner list follow docs/VOICE.md: sentence-case headings, the finding first and a labelled next step (3c4f415)
- The owner list folds near-identical steps into one line, and status says what its numbers mean (5f0c331)
- City is a dashboard with four plain sections, status and the guide use the same language, and the terminal panel is gone (b12e6ef)

### #1178
- Log the story on validation runs and gh calls made in a story worktree (db39f01)

### #1180
- Print the slowest test units when a smoke run takes long (f1fe231)

### #1181
- Audit the test suite and cut 52 seconds of health-call work from five modules (09240bf)

### #1184
- Clean up completed stories closed from main (5ede330)

### #1185
- Share the API circuit breaker across dispatch stories (2b8c038)

### #1186
- Close a story without an installed checkout unless it changes a hook or a job (8fb8472)
- Let a builder entry name a commit that never named its story, with the reason on the entry (f9a4050)
- Skip the live hook and job check when OliverCode is not installed (d3e9c97)

### #1187
- Skip the story-number check when the framework is not installed (ead3c40)

### #1188
- List every live claim in olivercode status and flag a story two holders claim (e5e8edd)

### #1189
- Print the estimated finish and today's landings in olivercode status (7b8f1cc)

### #1190
- Use one stall threshold on the status page and test its phone layout and design colors (7695a27)

### #1191
- Keep the full review lane for small stories on claim, lock, dispatch, queue and gate-selection files (7a43ed6)

### #1192
- Name the gates a round check left to the landing (33386ee)

### #1193
- Install finishes City or says it did not, and health, status and the guide show the gap (f0c3795)

### #1195
- The guide's first step names no file path and City's state reads once (60c5726)

### #1196
- Onboarding finds project folders and speaks plainly, with no path placeholder (33058ff)

### #1197
- Treat the shipped framework as the baseline and name changed core files on update (19bd078)

### #1198
- Close a story with how each acceptance criterion was verified (d351603)

### #1199
- Retire the standalone guard entry points (4faf692)

### #1203
- Builders get more turns, readers log why they fail, the owner queue holds each ask once, a dead run frees its claims, and the sweep finishes a half-done close (03e8656)

### #1207
- Share one JSONL store between candidates and the story outbox (93a3aa8)

### #1209
- City opens on what needs the owner (0f9a0f7)

### #1213
- Count a reader reply that ends in a bare PASS as a pass (535c696)

### #1215
- One desktop notification when a stopped story needs the owner (6121148)

### #1216
- Fix assertion-move detection and landed-story status (373045d)

### #1221
- Add Claude usage guardrails (9c64c0f)

### #1229
- Add daily cost trend to City (#1219) (2c150c4)

### #1233
- Add pause and cancel controls to the runner (#1214) (c59ed07)

### #1242
- Test four independent builders concurrently (661d21d)

### #1245
- Give OliverCode City an editorial dashboard design (c8494ba)

### #1248
- Use the requested lavender palette and make City responsive (f2e9cc0)

### #1249
- Restore pastel status accents and expand Additional details (caa19d8)

### #1251
- Allow external agents to close issues (64f3d47)

### #1252
- Clarify City delivery narrative and fix full-width layout (53a4a24)

### #1254
- Give City status pills meaning and highlight commands in purple (d4ecef5)

### #1255
- Make City idle and running states visibly distinct (28a470d)

### No story
- OliverCode public baseline (1d2ecd7)
- docs: Where-Things-Live table, fablize reference, phantom-path fixes, structural backlog (OC-7..9) (0ca8b98)
- refactor: single template home, prompts/ rename, code-security-review, vault-root override (38665b4)
- docs(backlog): spec-driven rewrite of open items -- junior-executable (315c510)
- fix(OC-6): Gate 5 checked remote URL scheme instead of actual credential scope (baa59b7)
- feat(OC-10): stdlib-only smoke tests for repo-profiles loaders + frontmatter parser (631b753)
- fix(OC-11): docs-reality audit -- 20 stale/fabricated claims fixed across 15 files (a7d6a09)
- refactor(OC-2): collapse 6 rule duplications to one home each (4 planned + 2 found) (d9fa885)
- fix(OC-3/OC-12): prompts value audit -- 18 KEEP, real personal-data leak found and fixed (56ede57)
- fix: narrow PUBLIC_PRIVATE_REPO_STANDARD.md scope to exclude OliverCode itself (20358fc)
- refactor: move frontend-ui-references out of OliverCode -- doesn't fit the 4-pillar scope (e6d6429)
- feat: deep-review skill + coverage staleness script + bloat gate + tracker template (dace49e)
- fix(hooks): per-line allowlist for supabase-anon-key in the secret scan (c42959d)
- fix(hooks): narrow the anon-key allowlist to the exact meta-tag shape (1ca1c7f)
- chore: cut dead prompts/, contributor ceremony; drop publish-status framing (d30b5ea)
- chore: remove orphaned bots-gateway subsystem + Codex/Gemini onboarding skill (4944f76)
- chore: remove dead audit_scopes health check; strip repo-name leak from BACKLOG (06935a9)
- style(health): renumber command_health comments after audit_scopes removal (a156e70)
- docs(backlog): drop D1 + citation referencing deleted bot-system-reality-check.js (9fcbd5e)
- refactor(health): _HealthTally helper; docs(backlog): trim to forward-only (5579e58)
- docs(skills): fix stale count in INDEX.md (19 -> 18) (ee7ee08)
- fix(audit): correct broken gates, remove conflicting hook installer and orphans (929ef05)
- docs(audit): strip legacy references, collapse duplicated authority (8aaa71b)
- docs(audit): one home for the orchestration path map and the baseline rules (691ac58)
- docs(audit): make FEATURE_MAP a real index of what ships (e98d2ae)
- refactor(audit): drop product paths from the location contract, unify lib imports (cf0f614)
- chore(audit): apply owner decisions on keepalive scope and skill placement (67ffbc3)
- feat(validate): build the A1-A5 gates -- reference integrity, consistency, tests (1c6acf2)
- fix(activation): make the global rules resolve outside OliverCode, close the hook fail-open (a46d031)
- feat(adoption): make the fork actually usable by a stranger, add the onboarding path (9bf412a)
- fix(refcheck): scan untracked files too, and exempt the downstream ARCHITECTURE path (aff1bb2)
- feat(cli): add `init`, real --root support, and reject unknown args (a1cb5b3)
- feat(qa): gate the property this repo exists to have -- a fork works with no config (4619a80)
- fix(qa): move CI-only gates onto the local path, record the Actions pause as policy (1c0365d)
- feat(qa): verify the adoption guide itself, not just the clone (f56d20f)
- feat(cli): add `olivercode install`; rewrite the docs a forker reads first (245f772)
- fix: stop asserting a completion gate nobody runs; unhide real QA findings (f2876a4)
- docs(backlog): bring the tracker current, record what is actually open (9268f89)
- feat: resolve B1 and B3; record B2 as a trigger, not machinery (d5de7f8)
- docs+test: prove the shipped templates gate, and reorder README for a first reader (b8d3f72)
- feat(cli): support scattered repo layouts and add `discover` (0a2d40f)
- feat(cli): reconcile an existing ~/.claude, and stop proposing OliverCode as fleet (8807f8b)
- fix(adoption): make the setup skill reachable before setup, and current (1dec633)
- fix: defects found auditing my own session output and running the adoption skill (1a1d5e8)
- fix: close a fail-open in the emoji gate; cover the fork lifecycle gaps (7514001)
- feat(cli): add `bootstrap` -- execute the manifest nothing was reading (75ee3d4)
- fix: resolve B5, remove a redundant installer, execute the last unrun scripts (08e6099)
- refactor: delete orphaned bots-gateway residue, remove a false-green test path (0bee03e)
- refactor(qa): delete checker sections that can never report a finding (4b48b98)
- fix(hooks): Gate 4 announced "passed" without scanning anything (046258d)
- fix: Gate 6 scanned for an extinct path; audit evidence accepted an empty string (bb7e775)
- refactor: delete the post-commit hook, replace its one real check with a gate (d4f8750)
- feat(validate): gate the failure class itself; close 5 credential gaps in Gate 1 (1da18ab)
- refactor(cli): one fleet iterator -- the two copies had already drifted into a bug (ccc0b7f)
- feat(validate): gate hook drift -- two hooks were citing docs that do not exist (e5e7593)
- fix(ci): scope GITHUB_TOKEN to read-only; converge checkout versions (05ccb1f)
- fix(docs): FEATURE_MAP claimed to index everything and did not; now enforced (529f2f4)
- fix(skills): remove a slash-command reference that resolves to nothing (0c11ac1)
- fix(governance): correct the gate-coverage claim and close the checker gap that hid it (c5680c7)
- docs(readme): rebuild to the V.Two README contract; close the fleet-name leak (1559444)
- qa(scenarios): ship the 12-scenario setup matrix; wire repo-map's last dead fields (e46624f)
- docs(backlog): record live B2 billing test — job refused before start, CI re-disabled (26728ea)
- docs(standard): lock the documentation contract framework-wide; README rewritten as exemplar (4adef56)
- docs(standard): License section is conditional, not a mandatory slot (d37850e)
- feat(contracts): Code Intent Standard — record why, and gate it (19674e4)
- fix(governance): generalize the intent contract; harden the leak gate to unregistered siblings (1864259)
- refactor(launcher): extract health checks and skills catalog; declare the QA overlap (51c07af)
- docs(readme): break the word walls; add readability rules to the standard (7c268c2)
- docs(voice): strip clever/metaphor constructions; ban them in the standard (3d3f2d1)
- docs(readme): plain language for a first-day reader; audience rule added to the standard (3098568)
- docs(voice): precise terms restored with glosses attached; the standard now bans both failure modes (72434e0)
- fix(review): waiver-date crash and a fleet-leak scan gap, both found by review (c9f2541)
- docs(contracts): add a length rule to the code intent standard (2bfd38e)
- chore(audit): dot-file cleanup; comments written for longevity, gated by contract (c748e95)
- docs(backlog): unquote a deliberately nonexistent path — the reference gate reads backticks as claims (c7c8028)
- feat(contracts): Development Lifecycle Standard — the sequence, not the artifacts (1537fdf)
- feat(gates): enforce CODE_INTENT_STANDARD §1 comment-block length (b7fbd8b)
- fix(gates): JSDoc tag lines end a prose run, not extend it (81e2894)
- fix(gates): a new block comment starts a fresh run (56197d5)
- docs(voice): make the documentation voice govern code comments, and add say-it-once (c70c947)
- fix(hooks): backport the PII lockfile exemption into the template (c6d0333)
- fix(hooks): the PII exemption's negative class ate the rest of the line (65a24d7)
- docs: add WRITING_PROCESS, the thinking layer the standard was missing (993e378)
- feat(standard): non-negotiable comment sentence form, and honest density (51b1e77)
- docs(orchestration): route the writing process before the QA standard (a8d1348)
- chore: delete resolved backlog entries, adopt the orphan contract, gate reachability (2456b7a)
- docs(backlog): B10 — comment prose is unaudited at scale (4faf348)
- feat(gate): catch comments that document code which is not beneath them (c7211b0)
- docs(backlog): B10 step 1 done — correspondence check shipped (fda9381)
- fix(gate): the correspondence check was nearly inert, and fatal on correct code (ca22929)
- feat(gate): measure Python docstrings in the comment budget (61ac333)
- fix(gate): template literals are data, not comments (463cdfe)
- feat(gate): enforce the decision ledger mechanically (8c82a25)
- docs(backlog): record the docstring pass and what it leaves open (b319647)
- fix(gate): a comment ends at `*/`, so the next one is a new block (3fcb1d1)
- fix(rules): the pre-commit rule named a file two repos do not have (d07dc91)
- docs(backlog): B10 finds the bloat is not evenly spread (8cd4565)
- fix(gate): close two fail-open holes the scanner had opened (6df647a)
- fix(manifest): register the comment gate as a templated file (a4a43a3)
- docs(backlog): re-draw the B10 sample against an honest scanner (9ec625e)
- docs(backlog): gap analysis — the ledger and staleness gates are unenforced (6e1f756)
- fix(contract): the comment budget is checked, not gated (4b1b94f)
- feat(gate): a portable decision-ledger gate with an adoption baseline (661e54d)
- fix(gate): the decisions gate flagged its own examples, and a regex class (6500751)
- fix(tests): the decisions test named example ids and tripped the ledger check (755967e)
- fix(audit): separate a missing marker from a stale review (e9c2510)
- refactor(gate): one decision-ledger checker, not two (cdf73f2)
- refactor(gate): the comment gate was 34% comments, above the rule it enforces (a55a2d7)
- fix(gate): decision ids are three segments, per the standard (7fab073)
- fix(hooks): gate 4 can read a denylist the repo does not publish (820a7ca)
- feat(gates): wire the comment and decision-ledger gates into pre-commit (B13) (c774f84)
- fix(gate): a user story is not a decision record (006d703)
- docs(readme): split driving problems into labeled subsections, cut vague filler (3ede250)
- docs(backlog): B11, B12 and B13 rewritten to what is actually true (68396e8)
- docs(writing): sharpen the anti-contrast and anti-reveal rules from repeated README drift (bfaa27b)
- feat(gates): add backlog-hygiene gate (11/9), fix token-policy empty-array bug (c109f04)
- fix(gates): don't cite a real decision id in the shipped backlog-hygiene header (5da22c8)
- Add the upward reasoning operations to the writing process (6bc6b1a)
- State the editing goal: density, not brevity (c641e72)
- Point olivercode-adoption at optional external plugins during discovery (c5f5e25)
- Rewrite README for clearer onboarding voice (6d3df12)
- Repoint the backlog's commit references after the history rewrite (b5bea28)
- Gate archived content in the private variant (c546276)
- Check topology, not just content, and give the plugin links a command (0b14c7e)
- Let a repo declare itself private, instead of the vault being the only one (e7c663d)
- Wire asd-ste100 into the documentation QA pass (6fce611)
- Collapse the process-sequence and trigger-routing duplication found in the full-repo audit (f984d4e)
- Correct B15's count after reading the skill bodies the first audit pass skipped (5024bd6)
- Execute B14 and B15 from the dedup audit (99b5440)
- Build the two structural fixes from the governance self-assessment (bcc1db9)
- Deep-review of f2876a4..HEAD: six real findings, all fixed (8cf541f)
- Land the deep-review commit's own sha in the Reviewed-through marker (26f2685)
- Apply asd-ste100 to the root docs: README, CLAUDE, ARCHITECTURE, CONTRIBUTING (50ba1ae)
- Apply asd-ste100 to core/contracts/ (9 files, 26 semicolon splits) (70c760e)
- Apply asd-ste100 to core/workflows/ and shared/workflow-standards.md (df562ce)
- Apply asd-ste100 to docs/, skills/, and remaining core/templates/ files (5c27aa8)
- Apply asd-ste100 to docs/BACKLOG.md, the last file (3db0539)
- Extract fablize's two verified-real gaps: verification grounding + early-stop hook (cc2526e)
- Uninstall fablize, sweep its references (b6723a9)
- Fix NO_ICONS gate false-positive on copyright/registered/trademark symbols (a043b32)
- Enforce asd-ste100 on every SKILL.md/CLAUDE.md as a pre-commit gate (de54b6c)
- Enforce current-state-only (no legacy/archive content) fleet-wide, not just the vault (7083e04)
- Add token-efficiency behavior rules to the always-loaded CLAUDE.md, not memory (49e3e9f)
- Cite DEVELOPMENT_LIFECYCLE_STANDARD in deep-review, fix pre-existing lint (78b56e5)
- Quiet gate 4 across all hook variants, add per-repo ste-lint exemption file (90f8d07)
- Split docs-reality-audit into references/, cut always-loaded content 43% (13d3402)
- Add audit-fleet consolidation + automation plan (8b16a8a)
- Mark Step 7 done in the audit-fleet plan (meta/plan-pressure-test shipped) (2c21d84)
- Extend sync-hooks to manage pre-push fleet-wide; fix 2 real validate.sh gaps (3f4ec85)
- Add audit-fleet and push-fleet CLI commands (6be8871)
- Fix 2 real ASD-STE100 hard violations, found by the new audit-fleet command's first live run (ec06274)
- Add scripts/local-scheduler/ -- Step 6, mirrors the fleet's proven launchd pattern (cd131ed)
- Update audit-fleet plan DoD checkboxes with what actually shipped (dffd73d)
- Close out audit-fleet plan: scheduler built, install deferred by OliverCBot's own choice (6d22dfd)
- Fix audit-fleet/push-fleet: honor OLIVERCODE_VAULT_ROOT, index in FEATURE_MAP (9f152e9)
- Add SKILL_EFFICIENCY_STANDARD: skill structure + runtime token cost baseline (9a353cf)
- Fix stale skill-location pointers; replace dead plugin-links health check (594a682)
- Add find-spec.py fleet-wide backlog-ID lookup; pressure-test + execution log (c04d26e)
- Add Claims Discipline to plan skill (06ebf92)
- Add backlog-management: config-driven GitHub Project backlog ops (5f694a0)
- docs-reality-audit: add Phase 5, check a configured GitHub Project (01aa7a9)
- backlog-management: add shared/backlog-config.example.json (75c854f)
- deep-review: add optional backlog-accuracy phase, tighten review-agent prompting (d563400)
- backlog-management: require a re-runnable audit command + boundary-split for XL/L items (16c12da)
- find-spec.py: point a vault SPEC-N miss at the GitHub Project instead of a bare not-found (f61dd8c)
- docs: strip self-referential "This is/This file is" openers (7dcbb69)
- docs: index scripts/find-spec.py in FEATURE_MAP (40433d5)
- docs(governance): point the clarity-gate row at the wrapper's real path (a73ede4)
- skills: land owner rules for per-unit review and plan-doc deletion, pass the clarity gate (2835fc5)
- Gate 4/11/13 (writing clarity): scope to references/*.md, add issue-citation check (e95a7b5)
- Gate 4: per-file hard-violation baseline, so GATE-SCOPE-1's scope expansion doesn't block pre-existing debt (872bc17)
- write-ste-baseline: scan git-tracked files only, so gitignored worktree copies do not pad the baseline (9b10667)
- pre-commit-private: run .githooks/pre-commit.local after the shared gates (GATE-LOCAL-1) (00c7b38)
- backlog-management: document the one-issue projectItems lookup and the GraphQL cost of listing the board (775a6bc)
- push-fleet covers skill-suite; audit-fleet finds skill-fleet-audit in skill-governance (f17119f)
- writing-documentation: comments in a shipping skill folder carry no decision id (d4c307f)
- documentation standard: index README shape for a repo that catalogs many things; writing-documentation applies it and compares every named path against disk (e7abada)
- backlog-management: hygiene is the baseline; never file what the repo's prioritization doc excludes (e351218)
- CODE_INTENT_STANDARD: code that ships in a zip holds no decision id or ledger (76e0650)
- code-intent standard: a file in a shipping skill folder carries no decision id (9a1489b)
- CLAUDE.md Voice: text a person reads as written stays in plain sentences (43bb16d)
- CLAUDE.md Voice: plain declarative prose; drop the always-on terse plugin (0c6d75d)
- CLAUDE.md Voice: lead with the answer, then the context a reader needs (67c4b47)
- CLAUDE.md: drop the mandatory writing reads and the never-re-read rule (bbabf83)
- Writing clarity gate warns instead of blocking; the three hooks stay in step (f79161d)
- docs: name the repo-local hook file without a path the reference check cannot resolve (ca9d110)
- early-stop-guard: a turn that waits on the user's go-ahead is not an early stop (5d42572)
- CLAUDE.md: comments give the reason; no ids or ledger entry required (299f1b9)
- Remove four generic skills that were never invoked (c65eff9)
- Docs: the clarity gate warns, comment IDs are optional, and the baseline drops four deleted skills (a6edc3f)
- Writing docs point at the company voice files; shrink WRITING_PROCESS and DOCUMENTATION_STANDARD to repo-documentation rules; keep the chat voice rule (6742acb)
- CLAUDE.md Voice: ban contrast framing outright and route writing through the clean-writing skill (458530c)
- CLAUDE.md Voice: import the shared-company voice baseline (d507b1b)
- Prune unused skills and unreferenced plan docs; collapse duplicate routing; stale vendor table fixed (5795d81)
- CLAUDE.md Voice: route slide copy to sow-proposal deck mode and keep the baseline's density rule above generic slide advice (b23abee)
- Remove the comment-budget and decision-records gates, their scripts and the code-intent standard (cbc6ead)
- Ban Claude Code's built-in auto-memory; use .claude-optimization/ only (6beefd6)
- File B21-B41: close-read findings across every doc, contract, and skill (0993e58)
- Fix B21,B24-B41 from the writing audit; leave B22-B23 for a call (73af97e)
- Resolve B22/B23: scope the two backlog paradigms instead of deleting one (3ca9052)
- Cut core/contracts/ from 10 files to 9, dedupe secret-location rules (5657b8b)
- Cut 3 more things that checked out as genuinely unused (6aa008c)
- Cut docs/BACKLOG.md's Activity log: pure git-log duplication, ~3,000 words (2acbb6c)
- Fix FRAMEWORK_BOUNDARY.md: dropped persona mentions missed in the earlier cleanup (0f68aea)
- Add revamp plan: converge backlogs, merge two more contracts, trim Voice section (5eb5869)
- Merge AGENT_SHARED_STRUCTURE.md into FRAMEWORK_BOUNDARY.md (plan step 2) (c3d5926)
- Retire the file-based backlog system fleet-wide (closes B42) (91df034)
- Trim DOCUMENTATION_STANDARD.md's Voice section (plan step 3, closes the plan) (63ea6c2)
- Ship check-backlog-hygiene.mjs via the bootstrap manifest (closes B43) (b35f689)
- deep-review of today's session: fix 2 real findings (closes B44) (565861f)
- Compress NO_ICONS_STANDARD.md: 374 words down to ~95 (5334af4)
- Retire the tracked-placeholder + gitignored-local-overlay pattern (G1) (1019df4)
- Move OliverCode's own open backlog items into GitHub Issues (9cee149)
- Fix OliverCode's backlog-config.json to match the fleet's field schema (6b6cf2c)
- Add REA fit assessment: not adopted, alternatives named (90085d6)
- Register personal-vault in the fleet profiles (c7e13e8)
- Point OliverCode at the Personal Vault layout (ba2ebe7)
- Make OliverCode layout-agnostic (a3c8faa)
- Voice: one guide built on the model reply, and every other voice rule cut to a pointer (b493b04)
- Voice: point at the single clean-writing voice.md and trim the documentation standard to structure (1416f3c)
- Voice: ship docs/VOICE.md so OliverCode carries its own voice (0adaf96)
- Voice: trim writing-documentation to structure and drop clean-writing (0ac16eb)
- Health: fail when a suite's docs/VOICE.md drifts from OliverCode's (7097021)
- Delete the writing-documentation skill (fe0c6ae)
- Docs: rename to CAPS-KEBAB and rewrite the documentation standard (2bb7ba3)
- Register the content-flow suite as a fleet repo (65a2b24)
- Backlog: record the deep-review coverage and the voice-copy decision (4fdd797)
- Docs audit: match the docs to the live code and remove what is finished (d36805f)
- Tests: make the rewritten tests fail without the code they protect (9196416)
- Tests: a normal hook run ignores the tree-scan setting (1eac17c)
- QA: the fork and scenario checks work with the empty registry (7625c98)
- Update: olivercode update re-runs install after the pull (3e589e4)
- ADOPTING: update re-runs install (b76a87a)
- QA: close the secret gate's large-file fail-open and fix the docs #23 made false (2d7b34d)
- Tracker: reviewed through 2d7b34d (137af6e)
- Deep review: close the commit guard's bypasses and fix four regressions from the session (6d7fa18)
- Tracker: reviewed through 6d7fa18 (b178d1b)
- Test token_policy, skills_catalog and repo_profiles directly by path (bb0a14e)
- Test reference_check by path and make a trailing slash require a directory (cd4eeed)
- Test health_checks by path and stop a malformed waiver crashing health (bfc456b)
- Gatekeeper: anchor the commit hash at the true end of the string (809dcc6)
- Tests: cover the launcher, commit guard and config paths no test caught (96e3922)
- Tests: NoLocalConfig reads a private empty folder and clears the two root overrides (6208bbc)
- deep-review: move the frontend and backlog-accuracy branches into references (3c61699)
- Skill efficiency gate: hold this repo's skills/ to the efficiency standard (ad34a3f)
- Skill efficiency gate: close the gaps a cold review found (683ce04)
- Run every pre-commit gate when committing from a linked worktree (561650a)
- Give every pre-commit gate exit a block and a pass test (a8a9b08)
- Say that variant hooks sit outside the hook generator (04f6b52)
- Gate tests drop git's GIT_ variables, and GOVERNANCE leaves the trade-off to its note (5993b6e)
- Add olivercode uninstall to remove what install wrote in ~/.claude (139ce8b)
- Fix uninstall's review findings: owner hooks, linked settings, moved checkouts (e9e7312)
- Record install's links so uninstall and re-install never guess at an owner's link (abbe3f3)
- Board hygiene reports an empty backlog as clean (08a08d3)
- Make the docs match the code, and fail push-fleet on a blocked push (2069890)
- Keep a lint warning from silently ending the commit hook (aef2787)
- Scan every pushed commit for secrets, and fix the commit and stop guards (305994a)
- One audit skill with a router replaces five audit skills (cdb7d0e)
- Audit: catch one-off example names and judge the target's shape (7bd87be)
- Install switches on the checkout's own commit gates (1d43a34)
- Generate adopted-repo hooks with no OliverCode text, so a repo without OliverCode's docs or generator gets no dead pointers (ecommerce-system #119) (f842943)
- Share one secret filter between the commit gate and the pre-push scan, and make OliverCode's hooks links to the templates (oliver-chase/OliverCode#214, oliver-chase/OliverCode#213) (5362d72)
- Lower the size baseline after the hook links (oliver-chase/OliverCode#213) (ae632d4)
- Fix the QA, audit and dead-pointer contradictions in RULES.md and a repeated phrase in CLAUDE.md (oliver-chase/OliverCode#218) (dbd6b4a)
- Drop the pull request template, since the rule is no pull requests, and the profile keys no code reads (oliver-chase/OliverCode#221) (18fadf0)
- Share one contrast pattern and one gh runner across the audit and backlog scripts, and catch less-X-more-Y in the commit-msg hook (oliver-chase/OliverCode#217) (7d46ce2)
- Add the Data files rule: one file per kind, appended, rolled up once large, with no dated copies; skill-creation and the audit lens carry it (oliver-chase/OliverCode#213) (1898219)
- Drop the repeated key comment from IDENTIFIER-GATE.json and align the contract template with the fleet (oliver-chase/OliverCode#220) (56617e9)
- One reader each for the size report, skill folders, tracked files and the hooks path, the conform board row stops repeating the hook row, shared quiet() and fewer doubled tests, and the contract template drops the exceptions block (oliver-chase/OliverCode#216, oliver-chase/OliverCode#218) (4fda9d1)
- Lower the size baseline after the shared readers (oliver-chase/OliverCode#216) (174be3f)
- Flag, directory and claude-dir helpers, one OC_ROOT, the placement check beside the other health checks, the markdown link check in Python, one temp-dir helper, GateHarness takes the hook file, the gate tests split into parallel modules, and the duplicated public-template, presence and crash-exit tests merged (oliver-chase/OliverCode#222, oliver-chase/OliverCode#216, oliver-chase/OliverCode#218) (d0678ea)
- Lower the size baseline after the remaining repeats (oliver-chase/OliverCode#222) (9e93392)
- State the hook origin and the fail-open rule once, and name the third step a quick pass (oliver-chase/OliverCode#219) (f2e07ac)
- Record why the suite takes 56 seconds and set the test budget to 60 (oliver-chase/OliverCode#218) (693f6e5)
- One home for repos: the repoRoot setting, olivercode place and clean, the creation gate, a session-start note and a health check (oliver-chase/OliverCode#250, oliver-chase/OliverCode#251, oliver-chase/OliverCode#252, oliver-chase/OliverCode#253) (347f547)
- A tracked permission policy enforced by a hook, checkpoint and restore, stop-and-ask triggers and a context budget (oliver-chase/OliverCode#255, oliver-chase/OliverCode#256, oliver-chase/OliverCode#257, oliver-chase/OliverCode#258) (0645220)
- Restore the eval core (tasks, run, compare and the learn --accept comparison), keep only the gate-block count in report, and leave release cut (oliver-chase/OliverCode#243, oliver-chase/OliverCode#244, oliver-chase/OliverCode#245, oliver-chase/OliverCode#246, oliver-chase/OliverCode#236) (84c33b4)
- Agents share one GitHub rate-limit budget: a hold every agent honours, a rolling cap on board writes and a gh-limit command (oliver-chase/OliverCode#260) (2e7bae8)
- Skill audit fixes for the OliverCode skills: the repo names its backlog config, test coverage matches whole words, plan, skill-creation, adoption and diagnosing-bugs text corrected (oliver-chase/personal-skill-suite#75, #76, #77, #78, #79, #80) (6eab871)
- Skill audit remainders for the OliverCode skills: bullet routes are measured, adoption triggers name OliverCode, skill-creation points at the self-containment lens (oliver-chase/personal-skill-suite#76, #78, #80) (2ff3463)
- Restore drain safety and adaptive builder limits (b5ed4c5)
- Fix builder briefs to include only explicitly named code (8ca7fa7)
- Measure actual desktop chat starting context (73a3938)
- Always include the working directory with owner commands (fef8608)
- Release drain claims when the terminal sends SIGHUP (27aa503)
- Show live smoke test module progress (177fef8)
- Keep smoke progress compatible with supported Python (7457a46)
- Test live smoke runner progress (e0aa751)
- Fix multiline reader verdict test fixtures (6116772)
- Use real newlines in grooming size fixtures (bece0b5)
- Name excerpt target explicitly in dispatch test (2b77ae8)
- Fix smoke progress test syntax (fd073f9)
- Align grooming size assertion with inferred minimum (49d48f5)
- Update status assertions for cost metric and builder baseline (45d8144)
- Format smoke runner launch errors cleanly (be00660)
- Stream smoke progress through validation gates (f0d0cba)
- Test live smoke progress through validation gates (e44a842)
- Simplify live progress gate test command (fe69a1c)
- Use documented single-line Files area fixtures (3239a71)
- Align status tests with recorded cost and builder ceiling (d6ff346)
- Document autonomous operator architecture in README (7de1eea)
- Align guide with autonomous operator workflow (d5073b8)
- Keep README workflow and guide wording aligned (c1be51f)
- Expose five-layer autonomous architecture in guide (4f75926)
- Align product analogy with autonomous operator architecture (f71ced4)
- Protect owner-to-outcome architecture documentation (ef24df4)
- Format architecture section in guide output (b6b35f6)
- Make guide habits owner-oriented (2dee84d)
- Remove owner-operator habits from README (a476b93)
- Align install introduction with owner-first workflow (ad9d923)
- Clarify current queued-execution onboarding step (7265f83)
- Test owner-first install onboarding language (d17ca12)
- Distinguish current queue workflow from target autonomy (a1b7523)
- Distinguish current queue workflow from target autonomy (3f877a5)
- Keep first-run description accurate to shipped queue flow (158045b)
- Scope the kitchen-table contract test to its own table (faaac93)
- Assert current interactive/delegated install guidance (49cc8b3)
- Clarify explicit delegation boundary in README (5c6ee13)
- Keep guide aligned with explicit delegation boundary (2ede1ab)
- Align architecture table file contracts with current layers (989eccb)
- Assert the install intro's actual validation wording (8d0329e)
- Keep per-round validation to changed work and safety boundary (3778972)
- Describe fast per-round validation accurately (cdd0cb7)
- Protect the focused per-round validation contract (433ea92)
- Make audits proportional and stop filing every observation (086515e)
- Track only substantive audit follow-up (ebfe338)
- Make audit-and-fix scope outcome-based (e3533d5)
- Track outcomes rather than every implementation step (cc66711)
- Clarify optional independent review and proportional audit scope (9463dba)
- Name the optional audit reader contract (4d183c2)
- Do not count API errors as builder rounds (cea5699)
- Preserve Claude API error classification (2199b77)
- Back off API failures without consuming story retries (ad7a2d4)
- Show the cause of the latest API failure in status (1cf3fe1)
- Cover API errors outside builder round accounting (333011b)
- Cover Claude API error metadata (8eb48b6)
- Cover API backoff and drain-wide stop (fbbac8c)
- Cover API failure cause in owner status (11527f1)
- Clear API warning after a later successful run (bc6ad20)
- Prove API failures do not escalate a story model (4444a17)
- Stop in-flight story retries after the API circuit breaker trips (d11fc26)
- Only classify API-looking text on failed model results (5392aa8)
- Avoid classifying successful work mentioning HTTP status codes as API failures (34913a6)
- Remove remaining backlog instructions that file every mid-task request (fb3fc02)
- Make backlog policy outcome-based instead of one story per request (2d9ab0f)
- Record lesson implementation without deleting its learning history (c480843)
- Distinguish lesson tracking from implemented status (bdd3002)
- Verify lessons only after their linked work is implemented (99a775f)
- Mark linked lessons when a story passes its completion gate (1007764)
- Cover persistent lesson implementation records (4c6c0dd)
- Cover story-to-lesson completion integration (1855e6c)
- Make lesson implementation marking idempotent and preserve JSONL line breaks (5276b35)
- Write valid JSONL when marking lessons implemented (c8dd32d)
- Require an implementation record before a lesson can be verified (1d8a84d)
- Make identical lesson capture idempotent (629ecae)
- Cover duplicate lesson suppression (aab3f05)
- Keep API failure causes visible after a story claim is released (1860772)
- Match completion evidence test to commit fixture (7b19fc2)
- Align final drain status with API failure test (c42a415)
- Consolidate interactive-first and lean engineering guidance from #1179 (7b9f2e7)
- Consolidate interactive-first setup guidance from #1179 (f6fd3ea)
- Index lean engineering skill from #1179 (2a97a65)
- Add lean engineering skill from #1179 (2c08f65)
- Add lean skill contract tests from #1179 (d400192)
- Restore chat/story ownership invariant in agent rules (825a507)
- Keep City Artifact publishing off runner lifecycle events (e9228ba)
- Test that runner events never publish City Artifacts (0b039f6)
- Fix status test helper publisher override (243190c)
- Remove the lessons log, its command and its no-op hook (e48c045)
- Protect Claude usage with one builder and a story spend ceiling (98ff95a)
- docs: simplify README for new users (1dedb0e)
- Rewrite setup guide in concise narrative (eb828f7)
- Preserve setup guide reference material (5ba14d8)
- Link setup guide to preserved reference (fbd7283)
- Retain runner safety defaults in setup (5c99145)
- Preserve install and fleet behavior details (9f77279)
- Consolidate setup guide into one readable document (0c04311)
- Remove redundant setup reference after consolidating guide (7e385c7)
- Redesign City as a pastel editorial portfolio (f29b1ae)
- Restore conservative runner limits during usage audit (668f07c)
- Finish City editorial redesign (2ca5fd8)
- Keep City typography editorial (f02c548)
- Stop prompting to reconcile local and GitHub repo names (af45714)
- Fix City page generation after builder-limit change (f248685)
- Invalidate stale City panel cache (07aecde)
- Make City usage analytics visible and expand repository details (44b3dc5)
- Show model mix on each landed story (e0f533d)
- Refresh City cache for expandable repository cards (6a516aa)
- Restore configurable throughput with usage safeguards (ad61938)
- Polish City information hierarchy (67c833c)
- Fix duplicate Usage and delivery section (f788214)
- Redesign Usage and delivery analytics (54421de)
- Refine City editorial layout and purple palette (d0671e2)
- Add durable builder lifecycle telemetry (fcdb847)
- Fix builder telemetry lifecycle validation (a5840cc)
- Simplify validation feedback and cover telemetry (3592d02)
- Fix launcher permissions and cap validation concurrency (de472a2)
- Delete unused close-gate audit and reopening behavior (4881b43)
- Restore live smoke-test progress by default (80ddb7e)

### Upgrade notes
- c65eff9: Remove four generic skills that were never invoked. Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- 5795d81: Prune unused skills and unreferenced plan docs; collapse duplicate routing; stale vendor table fixed. Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- 1019df4: Retire the tracked-placeholder + gitignored-local-overlay pattern (G1). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- fe0c6ae: Delete the writing-documentation skill. Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #14: Separation: the real fleet registry moves to a private repo (#14). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #26: References: fix the broken ones and check $OC paths (#26, #27). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #24: Overlap: one audit skill and one QA entry point fewer (#24). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #36: One repo registry (#36). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- cdb7d0e: One audit skill with a router replaces five audit skills. Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #43: Delete features nothing uses (#43). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #44: Make VOICE.md the only writing standard (#44). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #46: Merge backlog-management and board-hygiene into one backlog skill (#46). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #66: Fold two small neighbors into the skills that own them and finish the unused-parts deletion (#66, #65). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #86: Remove gates that cannot name a defect they prevented (#86). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #124: Gate verdicts, size-baseline raise cap and a thin launcher (#86, #81, #89) (#124). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #303: Code, config and tests that nothing runs are deleted (#303). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #897: The commit gate sources and hook builder install the secret, PII, version-file and voice gates for every later commit (#897). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #981: Conform checks only what protects a repo (#981). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #982: Board upkeep is one groom job (#982). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #1029: The engine ships no owner rules, tool names, handles or epic numbers, and the PII gate scans test files (#1029). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #983: Learning is one command and no prompt hook (#983). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #984: The launcher and the audit skill shed what nothing calls (#984). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- #1124: Unused commands and modules are removed (#1124). Read this commit's change before updating a fleet repo that relied on what it removed or renamed.
- e48c045: Remove the lessons log, its command and its no-op hook. Read this commit's change before updating a fleet repo that relied on what it removed or renamed.

## 2.0.0 - 2026-11-22

This release covers 15 to 23 November. One entry per capability describes what it does now.

### Commit gates
Every commit passes the secret, PII, owner-identifier, story-reference, version-file and voice gates, and `olivercode commit-check` runs the message gate on a draft before the commit. The hooks are written in `core/hooks/` and built by `scripts/build-hooks.py`.

### Hook guards
Session guards check each tool call for placement, policy, memory, model, reset, archived content and GitHub use. Each guard has an eval file with passing and failing cases, and every denial and hook run is logged so `olivercode cutlist` can name a guard that never fires.

### Limits and versions
`docs/LIMITS.json` holds one limit per file kind, and a file over its limit raises a warning. `olivercode version-cut` sets `VERSION` and writes the changelog once per day of activity, from the rules in `docs/VERSIONING.md`.

### Validation queue
`scripts/validate.sh` runs its checks through a queue, records how long each takes and reuses results already validated for the same tree, so a repeat run and a push cost little.

### Landing
`olivercode land` puts a story on main from its own worktree. Push approval, saved work in progress and the main-checkout guard protect unlanded work, and an update keeps local learning and user state.

### Owner queue
Steps only the owner can take, recorded decisions and activity from outside authors reach one queue that `olivercode owner` shows.

### Headless runner
`olivercode run`, `dispatch` and `drain` work queued stories in agent loops with a chosen model, review the result, sweep for gaps and drain the queue on a schedule.

### Board and story outbox
`olivercode board`, `groom`, `boardsweep` and `burndown` keep the backlog current from one shared local copy of the board. Story writes wait in an outbox while GitHub is busy and go out when it frees, and automatic filers write candidates for the owner to promote, so no scheduled job or hook files a story directly.

### Lessons and owner rules
Lessons are captured, checked for coverage and flagged when a rule has no gate. Owner rules carry the gate or skill that enforces them and decide what the queue accepts.

### Audit and backlog skills
The audit skill reads findings, modes and ledgers and checks the docs against the code. The backlog skill counts open stories, checks each story for its evidence and sweeps the board for gaps.

### Fleet and private split
`olivercode fleet`, `fleet-sync`, `init-fleet` and `install` register and update fleet repos from templates. Owner data stays in a private home, and the leak scan, name checks and engine-only checks keep the engine free of it.

### Health, status and schedules
`olivercode health`, `maintain`, `status` and `conform` report each machine, the open story count and the landing rate. Launchd schedules run the nightly jobs and `olivercode usage` reports their spend.

### Launcher and CI
`scripts/olivercode` registers every command, and framework CI runs the checks on each push.

### Docs
`README.md`, `CLAUDE.md` and the documents under `docs/` describe the system as it now stands, with the rules in `docs/RULES.md`, the gates in `docs/GATES.md` and the versions in `docs/VERSIONING.md`.

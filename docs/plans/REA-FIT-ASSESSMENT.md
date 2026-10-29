# REA fit assessment

Date: 2026-10-28. Method: read-only. I read the repo through `gh` and a few web searches. I did not install, run or clone anything from it.

## Verdict

REA is a reverse-engineering tool. It is not a marketing tool and not a video tool. For fresher marketing and video creation the fit is weak, and for most of our repos it is none.

It earns a small, specific role in one place: taking apart a competitor's website or web app the way a developer would, to see how its funnel, onboarding, pricing page and tracking are built. Even there, a plain browser DevTools session, a HAR export and Playwright cover about 80 percent of what we need. REA adds an agent-driven layer on top of Chrome DevTools Protocol captures (`inspect_web_page`, `analyze_web_bundle`, `observe_web_session`, `compare_web_captures`). Its heavy features (native binaries, Ghidra/Hopper/IDA, firmware, APKs, EVM, crash dumps) have no use in our work.

**Decision (2026-10-28): not adopted.** Browser DevTools, HAR export and Playwright cover the funnel-teardown need. Use these instead: a manual HAR teardown of competitor funnels, a manual Meta and TikTok ad-library pass, and a Remotion or Revideo spike for video. Revisit REA only for a concrete question about a competitor's app, in a throwaway sandbox.

## What REA is (from its own README and docs)

- MCP server and CLI, npm package `rea-agents`, MIT license, repo `morluto/rea`, site rea.tools. Created 2026-04-14.
- Targets: native binaries, Electron/JavaScript apps, .NET, Android APKs, websites (through a user-owned Chrome with remote debugging), HAR/SAZ network captures, process behavior, firmware and about 30 other artifact types.
- Web side is passive: it attaches to a browser you already run, records DOM, scripts, network metadata and routes, and diffs captures. The docs say it is "not a general browser automation or remote-control surface."
- Setup (`npx rea-agents setup`) edits the config of your agents (Claude Code, Codex, Cursor and others) and installs workflow instructions into them.

## Legitimacy and trust

- The README carries a warning that only morluto/rea, rea.tools and the npm package are official and that look-alike repos exist. The repo, site and package name agree with each other. I could not confirm the maintainer's identity beyond a GitHub account created 2020 (about 11.6k followers).
- Popularity is unusual: about 402k stars and 100k forks on a six-month-old repo (as of 2026-10-28). I cannot verify that figure and a number that high is not a trust signal. Treat provenance as unproven until you review the package yourself.
- Contents of the repo that matter for a security review: `install.sh`, `patches/`, `third_party/`, `native/`, `bridge/`, a `.gitmodules` file and a Linux path that downloads Hopper and installs dependencies with root or `pkexec`. SECURITY.md states plainly that it is not a sandbox and that opening an untrusted binary delegates parsing to local tools with your user permissions.
- Not reviewed: the npm tarball contents, install scripts in dependencies, and what the `setup` command writes. Do both before any install (`npm pack rea-agents` into an empty directory and read it; `npm view rea-agents scripts dependencies`).

## Permissions it asks for

- Write access to agent config files (MCP registration, skills, instructions). It says it backs up the old config and asks for approval.
- A Chrome-family browser launched with a remote-debugging port. That port exposes every tab and cookie in that browser to anything on the machine that can reach it. Use a throwaway Chrome profile, never the profile logged into our Google, Etsy, Pinterest or LinkedIn accounts.
- Runtime capture "runs or interacts with the selected target using your user permissions." Running a third-party app to observe it is code execution on our machine.
- Optional installs of Hopper, and use of Ghidra, JADX, tshark and other tools we do not have.
- Node 22.23.4+, 24.22.1+ or 26.12.1+.

## Legal and terms-of-service risk

- The repo's DISCLAIMER.md rules out DRM and license circumvention, copying proprietary software, bypassing authentication or bot protection, and "reproducing its protected code and assets." It puts all legal responsibility on the user.
- Observing the public pages and network calls of a competitor site we browse as an ordinary visitor is low risk. Replaying its private API, bypassing its login, or copying its code or assets is not.
- Taking apart a desktop or mobile app binary is the high-risk case: most EULAs forbid it, and DMCA 1201 and similar laws apply in some places. Canva, CapCut and similar editors fall here. Do not do it without counsel.
- The goal "see how Canva or a video generator works so we can replicate it in our pipelines" is the use most likely to produce infringing output. Learning a general technique and building it ourselves is fine. Copying their implementation or assets is not.
- Our own Canva-template shop (fourth-moon-market) depends on Canva's terms and Etsy's rules. A ToS dispute with either costs more than any insight REA would return.
- Captured traffic can hold personal data. Keep captures out of the vault repos.

## Per-repo fit

| Repo | Concrete use case | Fit | Better tool today |
|---|---|---|---|
| ecommerce-system | Teardown of a competitor shop's own site (not Etsy internals): page structure, scripts, checkout flow, tracking pixels | Low | Existing `shop-market-research` live-browser sample; DevTools |
| fourth-moon-market | See how a competing invitation store's funnel and email capture are built; check which analytics and pixels run | Low | DevTools Network tab, HAR export |
| fourth-moon-market-pins | None. It is a mirror of finished pin images | None | Pinterest Trends, the Pinterest API |
| oliver-studios | None. Repo is frozen as of 2026-10-28 | None | n/a |
| automated-content-flow | Understand how a web-based caption or clip tool structures its render requests, to inform our own render step | Low | Remotion or Revideo docs, FFmpeg |
| oliver-strategic-growth | Teardown of a prospect's or competitor's site stack (analytics, chat, forms, CRM scripts) for outbound personalization and positioning | Medium (best fit) | BuiltWith, Wappalyzer, Playwright; REA for deeper bundle and route analysis |
| oliver-crawl | Compare our crawler's view of a page with a real browser's network and script behavior, to find content a crawl misses | Low to medium | Playwright traces |
| 01 - Skills (skill suite) | A "competitor funnel teardown" skill built on browser captures | Low | Build on Playwright and HAR; add REA only if the trial proves value |
| Other repos (account tools, slideseditor, tesknota, fallow, family-stories, embroidery-stitch-gallery, qa_aisdlc, oliver-app) | None found | None | n/a |

## Ranked experiments (all cheap, all sandboxed)

1. **Review before running (30 minutes).** `npm view rea-agents scripts dependencies repository`, then `npm pack` into an empty directory and read `package.json` and `install.sh`. Pass or fail decides whether anything below happens. Owner: Kian.
2. **Competitor funnel teardown without REA (1 hour).** Pick one competitor site. Record a HAR in a throwaway Chrome profile while you walk its signup or checkout. List pixels, forms, pricing logic and email tools. Gives the baseline REA has to beat.
3. **Same target through REA, in a container or spare machine (1 hour).** Only if step 1 passed. Run `rea inspect-web-page` and `rea analyze-web-bundle` against the same site, use `npx -y rea-agents@latest ...` as a one-off, and do not run `setup`. Compare findings against step 2. Keep it only if it finds something the HAR did not.
4. **Free ad research with the official libraries (1 hour).** Search the Meta Ad Library and TikTok Creative Center by hand for our niches (wedding invitations, embroidery) and write down the hooks and formats that run longest. This is where fresher marketing ideas come from, and REA is not involved.
5. **Remotion or Revideo spike for automated-content-flow (half a day).** Render one templated short from a caption plus stock clips, and compare it with the current render step.

## Better-fit tools for fresher marketing and video

I did not verify current pricing, license terms or maintenance for these. Check before adopting.

Video creation:
- Remotion, React video framework, https://github.com/remotion-dev/remotion. License is custom (GitHub shows "NOASSERTION"); it requires a paid company license above a team-size threshold, so read https://www.remotion.dev/docs/license first.
- Revideo, open-source Motion Canvas fork built for headless and API rendering, https://github.com/redotvideo/revideo.
- Motion Canvas, MIT, hand-authored explainers, https://github.com/motion-canvas/motion-canvas.
- FFmpeg and MoviePy for plain cut, caption and concat work, https://ffmpeg.org and https://github.com/Zulko/moviepy.
- LTX-2, open-weights video generation, needs a strong GPU (named in a comparison article, https://autoae.online/blog/open-source-remotion-alternatives-2026). Vendor-style source; verify.
- Comparison overview of code-first options: https://www.pkgpulse.com/guides/remotion-vs-motion-canvas-vs-revideo-programmatic-video-2026.
- Canva connector already in this session (design generation, export, brand templates) covers template and pin imagery for the shop.

Marketing research:
- Meta Ad Library (official, free): https://www.facebook.com/ads/library and its API, https://www.facebook.com/ads/library/api.
- Google Ads Transparency Center (official): https://adstransparency.google.com.
- TikTok Creative Center, top ads and trends (official, free): https://ads.tiktok.com/business/creativecenter. Not researched in depth.
- Pinterest Trends for pin ideas (official): https://trends.pinterest.com.
- Apify Meta Ad Library actors (paid, third party, scraping against Meta terms is a risk): https://apify.com/store?search=meta%20ads%20library. Prefer the official API.
- Wappalyzer and BuiltWith for competitor tech stacks: https://www.wappalyzer.com, https://builtwith.com.
- Playwright for scripted, repeatable site walkthroughs and traces: https://playwright.dev.

## Decision

Skip REA for marketing and video. Run experiments 1 and 2 this week. Run 3 only if 1 passes and 2 leaves a question unanswered. Put effort into experiments 4 and 5.

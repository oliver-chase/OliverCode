# Frontend/UX review angles

Load this from `deep-review` step 2b when the range touches any UI.

Cover EVERY user-facing surface — admin/operator UI and public pages alike, not just the screens the session worked on:

- **Design-system lock-in / no hardcoding:** zero inline styles, and zero hardcoded colors, sizes, or spacing outside the token sheet. One radius system, one accent, and every JS-generated class exists in the stylesheet. If the repo lacks a mechanical gate for this, ADD one in the same session. The proven pattern is an inline-style scan wired into the validate aggregator, and it removes the finding class for good.
- **Component reuse:** repeated markup patterns must go through the shared component/renderer, never copy-pasted per page. Duplicated render functions across pages are a finding.
- **User flow:** walk each primary journey end to end as the user would. Every step must be reachable from the previous one, with no dead ends. Real example: an approval step whose output had no next action anywhere in the UI. Empty states funnel forward. Post-action feedback tells the user what actually happened.
- **User journey docs:** the repo's journey/flow doc must match the shipped UI page-for-page. Stale page names or steps are findings.
- **Accessibility:**
  - Keyboard path: a focus-visible ring on every interactive element, no keyboard traps, logical tab order.
  - Labels: every input labeled, no placeholder-as-label, and buttons that self-describe or carry an accessible name.
  - Contrast at WCAG AA for text and controls.
  - Touch targets usable on coarse pointers. Hover-only affordances need a touch path.
  - Media elements carry captions/alt or a documented reason.
- **Responsiveness:** at ~360/768/1024/1440/1920 — no horizontal page overflow, nothing overlaps, wide content scrolls inside its own container.

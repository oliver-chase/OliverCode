# Interface checks

Load this from any audit route whose target has a user interface. Cover every screen a person reaches, admin and public alike.

- **One design system:** no inline styles, and no colors, sizes or spacing outside the token sheet. One radius scale and one accent, and every class a script adds exists in the stylesheet. A repo with no check that enforces this gets a story to add one
- **Shared components:** a repeated piece of markup goes through one shared component. Two pages with their own copy of a render function are a finding
- **User flow:** walk each main journey end to end. Every step is reachable from the one before, an empty state points to the next step, and the confirmation after an action says what happened
- **Journey docs:** the repo's flow doc matches the shipped screens page by page
- **Accessibility:** a visible focus ring on every control, no keyboard traps, a logical tab order, a label on every input, a name on every button, WCAG AA contrast, touch targets that work on a phone, a touch path for every hover action, and captions or alt text on media
- **Screen sizes:** at about 360, 768, 1024, 1440 and 1920 pixels wide, nothing overflows the page or overlaps, and wide content scrolls inside its own box

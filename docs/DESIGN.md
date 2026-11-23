# Design

This is the one standard for anything visual made for a person: a page, dashboard, artifact, slide, image, listing photo, logo or interface. It loads on visual work only. The words on the design follow `VOICE.md`.

## Start from a brand

- Every visual starts from a written design note: the reference the owner likes, the mood in three words, the palette, the type and the spacing. A repo with visual output keeps it in `docs/DESIGN.md`, and a brand with none gets one before the first asset
- The owner's final pass wins. Read finished work back, record its real values and treat each change as the rule for the next asset
- Each brand looks like itself. Two brands never share a palette, a type pairing and a layout
- Before a design is built, look at the market leaders in its category and follow their proven structure. The design note names the leaders examined and what the design takes from each
- Before a visual counts as done, check it frame by frame. Look at each frame or slide of a video, animation, GIF or slide sequence one at a time, never from one overview
- A real brand's colors come from its own site, its logo files or the owner, and never from memory. The design note names the source. When none is at hand, ask the owner before choosing a color

## Tells of generated design

Every tell sits in one of two tiers. A Floor tell is never allowed, and no waiver lifts it. A Reflex tell is a judgment call: it ships only with a waiver, a line in the page's design note that names the tell, names the page and gives the reason this page needs it. A Reflex tell with no waiver is a finding.

### Floor

- Invented metrics, such as user counts, ratings or savings with no source
- A form that sends nothing, or looks sent when it is not
- An empty picture box standing in for a photo or a product shot
- Placeholder copy, such as lorem ipsum or "Your text here"
- Invented testimonials or customer logos
- Pulsing live dots on a page that is not live

### Reflex

- Tags and pills
- Italics for emphasis beyond a rare word
- Instrument Serif
- Negative letter-spacing
- Over-detailed interface
- Dividers between blocks
- Several shades and opacities of one color
- Bordered containers
- Over-detailed diagrams
- Verbose or repeated text
- Code-style breadcrumbs
- Numbered sections
- Eyebrows, the small labels above headings
- Dithering
- ASCII art
- Squircles
- Monospace type outside code
- All-caps subtitles
- Gradient backgrounds and dark gradient heroes
- Gradient text
- Side accent bars on cards, callouts or lists
- Glow shadows
- A hover lift on every card
- Periods at the end of titles
- Emoji as decoration
- Cream backgrounds
- Painting backgrounds and Renaissance branding
- Disco logos
- Infinite canvases
- Pixel loaders
- Sparkle icons
- Liquid glass
- Rows of three icon cards
- Endless marquees
- Decorative flowcharts
- Centered or wrapped body text

## Rules

**Color**
- Pick one field color, one text color and one accent, and add a second accent only when the brand note names it
- Define every color once as a token and use the token everywhere, including the dark theme
- Text contrast is at least 4.5 to 1, and large text at least 3 to 1
- Set the page background on purpose, and keep it flat

**Type**
- Choose one family for headings and one for body, or a single family for both. Weights stay between 400 and 500
- Body text is 16 to 18 pixels with a line height near 1.5, and a line holds 45 to 75 characters
- Size creates hierarchy. A heading is larger than its body by a clear step, and nothing else about it changes
- Use a free font whose license covers the product

**Space and layout**
- Space on a 4-pixel grid, and hold one page margin and one content width
- Group related things by closeness, and let whitespace separate groups where a divider would otherwise go
- One idea per screen or slide, and one primary action per view
- Align to one left edge or one center line, never both on one page

**Craft details**
- A nested rounded corner has an inner radius equal to the outer radius minus the padding
- Borders use an alpha color such as rgb(0 0 0 / 0.12), so they blend into any background
- Build palettes in OKLCH so equal steps look equal
- An icon's stroke matches the weight of the text beside it
- A carousel fades its edges with a mask, and a swapped icon blurs as it leaves
- Dark mode shows depth with lighter surfaces, because shadows barely show
- Full-height sections use 100dvh, and a product shot on white uses mix-blend-mode multiply

**Browser surfaces**
- Text selection and the caret take the brand's accent, never the browser's default blue
- Scrollbars are thin and match the field, and in dark mode they sit on the dark field
- The focus ring is a 2-pixel outline in the accent color, drawn with `:focus-visible` and never removed
- Figures in tables, prices and stat rows use tabular numerals, so their columns line up

**Content**
- State the point once, in the fewest words that keep it
- Every image, icon and chart earns its place by carrying information the text does not
- Charts label values directly and use one color for the data, with a second only to mark what matters

**Image and motion**
- Use real photographs and the brand's own motifs. Draw a motif only when the owner's references contain it
- Motion is under 300 milliseconds, explains a change and respects the reduced-motion setting
- A trend is a tell when it is a shortcut. Use one technique only where the brand note asks for it

**Accessibility and fit**
- Every interactive target is at least 44 pixels square, every image has alt text and focus is visible
- The layout works at 375 pixels wide with a 16-pixel gutter and never scrolls sideways
- Check each visual at phone width and in light and dark before it ships

## Rejected and model

| Rejected | Model |
|---|---|
| A card with a border, a pill reading "New", an eyebrow reading "FEATURES" and a gradient behind it | A heading, one sentence and a link on a flat field, with space around them |
| Three shades of teal for text, rules and background | One teal for the accent and one near-black for text |
| Sections headed "01", "02" and "03" with thin dividers | Sections headed in plain words, separated by 64 pixels of space |
| A diagram with eight boxes, arrows and a legend | Three labeled steps in a row |
| A headline in tight-tracked Instrument Serif with an italic word | A headline in the brand's sans at weight 500 with default tracking |
| A pulsing green dot, a sparkle icon and three icon cards in a row | One sentence, one brand image and one link |

## How it is applied

- Read this file and the repo's own `docs/DESIGN.md` before any visual work, and read the finished result against the tells list before it ships
- The `audit` skill checks visual output against it (lens 7b). A Floor hit is a hard failure, and a Reflex hit is a finding unless its waiver is written in the design note
- A suite that ships visuals carries a byte-identical copy of this file in its own `docs/DESIGN.md` and may add its own sections after it

# Interactive scientific artifact design

The learner opens one generated HTML file, understands the concept, and sees its
controls and primary visual immediately. It should read as an explorable notebook
or scientific figure. Product branding, global navigation, sidebars, offline badges,
separate learning destinations, and landing-page heroes do not belong in the artifact.

The reference-inspired revision uses a compact serif title, an Idea / Why it
matters / Main symbols summary, rounded ivory sections, and numbered green markers.
On wide screens, context precedes manipulation; on compact screens the actual
context section moves below the mechanism and consequence, preserving the same
visual and screen-reader order. Controls and a primary result stay in view.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| canvas | #faf9f5 | #151d19 | Notebook surface |
| surface | #fffefa | #1e2822 | Controls and scientific figure panels |
| ink | #193e34 | #eff2e9 | Primary text |
| muted | #536762 | #b1bdb2 | Supporting text |
| accent | #245548 | #a8d1b9 | Scientific marks, selection, causal focus |
| tint | #eff2eb | #2a3930 | Related calculation values |

The palette comes from the user's inspiration image. Local Georgia serif headings
provide the editorial character of the new reference; body copy uses system UI
and numeric data uses a monospaced face. The title is 1.6–2.35rem, while compact
section headings scale down to 1.05rem. No fonts or images are loaded remotely.
`templates/notebook.css` applies the reference-inspired layer to all mechanisms.

Text colors retain WCAG AA contrast in light and dark appearances. Heatmap text
selects black or white from cell luminance; numeric labels preserve meaning without
color. Focus rings, 44px controls, reduced motion, and 200% text remain supported.

```text
Regular: compact title + orientation
         [inputs | primary outputs and calculation path]
         intermediates → changes → explorations → supporting evidence
Compact: compact title + orientation
         first input + additional editor disclosures
         primary outputs → computation → supporting context
```

Matrix controls show row/column indices and their actual numeric shape. The example
composition groups the three matrices across a row on wide screens and uses
disclosures on compact screens. Native checkboxes receive an accessible switch
appearance. Exploration cards use aligned Change / Observe / Why descriptions.

The generic renderer has no paper-name branches. Authored experience data creates
distinct explanatory figures: Attention shows matrices, scores, weights, and output;
Entropy groups a bits metric with contribution bars; Bayesian updating pairs its
rule with odds/probability changes. Additional matrix editors collapse at widths
up to 700px so controls do not displace the primary visual below the first viewport.
Walkthroughs open these disclosures when needed and retain editable inputs.

Applied Apple skill guidance:

- Emil `SKILL.md` §1 Response: immediate press feedback, input-driven updates.
- Emil §14 Reduced motion & accessibility: optional motion; contrast adaptations.
- Emil §15 Typography: restrained hierarchy and size-dependent tracking.
- HIG `layout.md` › Visual hierarchy: order by importance, group related content,
  and use progressive disclosure. The manipulation/result pair now comes first.
- HIG `entering-data.md` › Best practices: dynamically validate entry and provide
  prefilled values and familiar native inputs.
- HIG `buttons.md` › Best practices: visible press states and comfortable targets.
- HIG `charts.md` › Enhancing the accessibility of a chart: context, accessible
  values, and inspectable tables; comparisons share axes.
- HIG `modality.md` and `feedback.md` › Best practices: guidance is dismissible,
  nonmodal, and paired with actual numeric consequences.

Acceptance checks cover canonical and directed versions of every shared fixture
at 1280×800, 390×844, and 320×800. Each must contain the full concept title,
orientation, first meaningful control, and primary visual within the first viewport.
There must be no website chrome. Keyboard tabs, guide dismissal, error recovery,
dark appearance, reduced motion, 200% text scaling, and safe rendering are also tested.

Previews embed Person 2's unchanged evaluator and have working controls offline.
Browser mocks remain only for transport concurrency and error injection checks.
Calculation stages connect only where an actual dependency exists. Input-driven
highlighting marks changed values; optional guide outlines describe dependencies
without claiming that those values changed. Primary visuals get a stronger border,
larger figure area, and readable computed values rather than decorative imagery.

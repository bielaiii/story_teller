# AGENTS.md

## User preference

The user is not familiar with frontend development details.

The user usually cares about the final visible effect, interaction, and usability, not the specific frontend implementation choices.

When the request is about UI, layout, style, animation, or interaction:

* Infer the intended result from the user's description.
* Make reasonable frontend decisions without asking about technical details.
* Prefer the simplest implementation that achieves the requested effect.
* Follow the existing project style and structure.
* Reuse existing components and patterns when they are easy to identify.
* It is acceptable to improve visual details when the user's request is vague.
* Do not over-engineer the solution.

## When to ask the user

Ask only when the decision affects the final product in a visible or meaningful way, such as:

* different page layout directions;
* different visual styles;
* different user flows;
* destructive changes;
* adding a major dependency;
* changing a large part of the project.

Do not ask the user about routine frontend implementation choices.

## Implementation style

* Make the feature work first.
* Keep changes focused.
* Avoid large rewrites unless clearly needed.
* Avoid introducing new libraries for small UI changes.
* Do not change unrelated behavior.
* Prefer practical, readable code over clever abstractions.

## UI direction for this project

The visual direction is a light, interactive writing workspace for organizing a novel. It should feel like a creative canvas rather than a dark developer tool, a data dashboard, or a marketing page.

Core style:

* Use a light, soft, semi-transparent workspace style with subtle shadows and restrained glass-like panels.
* Keep the interface calm and mature. It can feel alive, but avoid childish bounce, excessive glow, loud decoration, or over-animated effects.
* Prefer focus interactions: click a line, node, or person to emphasize related content; hide or de-emphasize unrelated content; click blank space to return to the default state.
* Floating information panels should feel like lightweight side annotations, not heavy modal boxes.
* Avoid visible grid backgrounds unless the user explicitly asks for one.

Rendering approach:

* Prefer frontend-rendered visuals over SVG for major structures.
* Use Canvas, DOM, and CSS for graph lines, timeline lines, nodes, ambient effects, layout, and interactions.
* Avoid using SVG for the main relationship graph or timeline structure. SVG is acceptable only for small icons when there is a clear reason.
* The experience should feel like elements are being drawn and managed by the frontend, not like a static exported vector diagram.

Relationship graph:

* The graph is the default entry page.
* It should feel like an interactive, zoomable canvas.
* Character nodes are circular avatars. Placeholder initials/names are acceptable until real square avatar images are provided.
* Clicking a character should center that node and show a floating side profile. If no character is selected, do not show the profile panel.

Timeline / Git graph style:

* The timeline should be inspired by Git graph structure, but visually consistent with this project's light creative workspace style.
* The main line is an open, continuous vertical line. Its top and bottom should not feel sealed or final unless the story has formally started or ended.
* Branches should be treated as complete side tracks, not as many disconnected short links.
* A branch must connect through its own top and bottom endpoints. Do not visually connect into the middle of a branch segment.
* Branch transitions should look like a smooth bypass track: branch out, run beside the main line or another line, then merge back in.
* Rounded corners must follow the actual direction of the line at each endpoint. A line can be a source in one connection and a target in another, so corner direction must be determined by the endpoint role for that specific connection, not by the lane globally.
* Color transitions should be local: the part nearest a line should use that line's color, and only the space between lines should gradually transition toward the connected line's color.
* Clicking a timeline line should highlight that line and hide unrelated story summaries. Clicking blank canvas should restore the default full view.

## After finishing

Explain the result in simple language:

* what changed;
* what effect the user should see;
* which page or component to check;
* whether any command was run to verify the change.

Avoid explaining frontend jargon unless it is necessary.

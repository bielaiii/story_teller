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
* Do not style ordinary actions as tags, chips, badges, or pill buttons. Reserve those compact forms for metadata and filter states; use clearly recognizable rectangular controls for actions such as edit, delete, save, and cancel.
* Prefer focus interactions: click a line, node, or person to emphasize related content; hide or de-emphasize unrelated content; click blank space to return to the default state.
* Floating information panels should feel like lightweight side annotations, not heavy modal boxes.
* Avoid visible grid backgrounds unless the user explicitly asks for one.

Rendering approach:

* Prefer frontend-rendered visuals over SVG for major structures.
* Use Canvas, DOM, and CSS for graph lines, timeline lines, nodes, ambient effects, layout, and interactions.
* Avoid using SVG for the main relationship graph or timeline structure. SVG is acceptable only for small icons when there is a clear reason.
* The experience should feel like elements are being drawn and managed by the frontend, not like a static exported vector diagram.
* Treat WebGPU as progressive enhancement rather than a platform requirement. Detect `navigator.gpu`, handle adapter/device failure and device loss, and preserve a Canvas 2D fallback with the same interaction meaning.
* Keep avatars, names, controls, and accessibility semantics in DOM even when GPU rendering is active.
* Respect reduced-motion preferences in GPU and Canvas animation paths.

Relationship graph:

* The graph is the default entry page.
* It should feel like an interactive, zoomable canvas.
* Character nodes are circular avatars. Placeholder initials/names are acceptable until real square avatar images are provided.
* Clicking a character should center that node and show a floating side profile. If no character is selected, do not show the profile panel.
* Default layout must be derived from relationship topology, `mainPlotImpact`, and character groups. Do not store routine initial `x` or `y` coordinates in character files.
* Treat `graph-layout.md` as global physics tuning plus rare explicit exceptions. New characters and relationships must enter the default layout without adding node-specific layout configuration.
* Characters with a single relationship should extend outward from their connected character; multiple leaves on the same character should fan out automatically rather than share one direction.
* Use `characterScope` to distinguish `主线人物` / `常驻人物` from `一次性角色` / `待定角色`. One-off or undecided characters stay searchable and usable in chapters, archives, and automatic recognition, but do not enter the graph by default.
* Manage `一次性角色` and `待定角色` from a subtle entry inside the character archive, not as a top-level navigation item. They should feel like a drawer for reusable minor roles rather than a primary page.
* `graphVisible: false` is only a rare explicit override that excludes a character from the graph without changing its searchable archive behavior.

Timeline / Git graph style:

* The timeline should be inspired by Git graph structure, but visually consistent with this project's light creative workspace style.
* The main line is an open, continuous vertical line. Its top and bottom should not feel sealed or final unless the story has formally started or ended.
* Branches should be treated as complete side tracks, not as many disconnected short links.
* A branch must connect through its own top and bottom endpoints. Do not visually connect into the middle of a branch segment.
* Branch transitions should look like a smooth bypass track: branch out, run beside the main line or another line, then merge back in.
* Rounded corners must follow the actual direction of the line at each endpoint. A line can be a source in one connection and a target in another, so corner direction must be determined by the endpoint role for that specific connection, not by the lane globally.
* Color transitions should be local: the part nearest a line should use that line's color, and only the space between lines should gradually transition toward the connected line's color.
* Clicking a timeline line should highlight that line and hide unrelated story summaries. Clicking blank canvas should restore the default full view.

## Performance and lazy rendering

Treat hidden work as work that should not exist yet.

* Do not render the contents of an inactive page during initial startup. Initialize each page when the user first opens its tab.
* Defer page-specific configuration fetches, such as the timeline layout file, until that page or a dependent check is opened.
* Timeline nodes, summary cards, connectors, and Canvas pixels must be virtualized by the current visible viewport.
* Do not create DOM elements for timeline items that do not intersect the screen.
* Do not allocate a full-height Canvas for a long timeline. Size and position the Canvas backing store to the currently visible timeline rectangle, and draw only intersecting lines.
* When the timeline is hidden, release its visible DOM nodes and Canvas backing store while retaining only the lightweight data model needed to resume.
* Lazy rendering applies in both vertical and horizontal directions.
* Images outside immediate use should use native lazy loading and asynchronous decoding.
* Preserve scroll position and interaction state when virtualized elements are removed and recreated.
* Run graph layout physics only while positions are changing. Wake it for new nodes, relationship changes, dragging, and resizing; let it sleep after the layout settles while lightweight visual effects continue independently.
* Pause continuous Canvas and GPU work while the document is hidden, and reduce or stop it when the user prefers reduced motion.

## Asynchronous work

Prefer asynchronous, cancellable work whenever an operation crosses an I/O, rendering, or expensive-computation boundary.

* Load independent Markdown collections and configuration files concurrently.
* Yield to the main thread between expensive model-building phases so navigation and input remain responsive.
* Batch scroll and resize rendering through `requestAnimationFrame`; do not render directly for every event.
* Cancel or invalidate pending work when the user switches pages, reverses the timeline, or starts a newer render.
* Build the data model separately from DOM generation. Reuse a valid model and regenerate only the visible presentation layer.
* Do not wrap trivial synchronous value transformations in promises. Async boundaries should reduce blocking or coordinate real deferred work.

## Local content mutation

Treat novel content as user data rather than application source.

* Markdown files are persistence only. Do not require the user to open or edit local source files for routine content or configuration changes; provide the corresponding interface and localhost write API instead.
* When a persisted structure needs migration, perform it through the application's validated write path and keep the UI as the ongoing source of operations.

* Serve the frontend and local mutation APIs from the same loopback-only process and port.
* Never expose content mutation endpoints beyond `127.0.0.1` or `localhost`.
* Restrict every write to the selected `content/<project>/` directory and Markdown files within it.
* Require a preview before applying a bulk rename. Show affected files, lines, and replacement counts.
* Keep stable IDs unchanged when renaming a display name. Character files use `ID-姓名.md`, and relationship files use `ID-姓名__ID-姓名.md`; rename these files in the same operation so filenames remain readable without changing relationship IDs.
* Include file moves in the preview. Check that contents and source paths still match the preview, reject destination conflicts, use atomic replacement and moves, and retain one safe undo operation that restores both contents and filenames.
* Public or static deployments must remain read-only without presenting failed write controls as available.
* Use the generated `content-index.json` as the shared discovery format for localhost and static deployment. Local scanning refreshes this file; `manifest.md` contains project metadata rather than a second hand-maintained file list.

## After finishing

Explain the result in simple language:

* what changed;
* what effect the user should see;
* which page or component to check;
* whether any command was run to verify the change.

Avoid explaining frontend jargon unless it is necessary.

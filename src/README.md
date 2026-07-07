# Frontend Architecture

The app is loaded as ordered browser scripts so local and static deployment stay build-free.

## Layers

- `core/model.js`: shared data collections, content loading, markdown frontmatter parsing, diagnostics inputs.
- `core/runtime.js`: UI state and DOM references.
- `shared/ui.js`: rendering helpers, markdown helpers, tags, pagination, entity lookup helpers.
- `features/local-tools.js`: local-only mutation tools such as relationship creation and rename/refactor workflows.
- `views/story.js`: story list, fragments, tags, pagination, side-task shelf.
- `views/timeline.js`: timeline model, viewport virtualization, canvas drawing, timeline interactions.
- `views/plot-detail.js`: full plot reading view, reading progress, references, global search navigation helpers.
- `views/characters.js`: character archive, temporary character shelf, character detail and rename controls.
- `views/entries.js`: entries/archive list and detail view.
- `views/graph.js`: relationship graph view, layout physics, graph interactions, canvas scene generation.
- `bootstrap.js`: event binding, ambient canvas, startup sequence.

## Refactor Rule

Keep new work inside the smallest matching layer. Do not add new feature logic to `app.js`; it is only a compatibility note.

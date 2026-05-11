# Changelog

All notable changes to Sugestatorium are tracked here.

## [Unreleased]

Potential next versions:

- richer search ranking and grouped result sections
- denser table presets and saved review layouts
- prompt editing from inside the app
- prompt diff view between versions
- export reviewed subsets to CSV or JSON
- bulk review actions for selected rows
- better charts for prompt-to-prompt comparisons
- optional local font bundling for fully offline usage

## [0.3.1] - 2026-05-08

Changed:

- removed the remaining Next.js and Node-specific source files after the Python migration
- simplified the repository into a Python-first layout for future releases

Cleaned:

- deleted legacy React components, Next routes, TypeScript utilities, and Node package metadata
- trimmed obsolete build and dependency artifacts from the working tree

## [0.3.0] - 2026-05-08

Changed:

- refactored the app from Next.js to a Python-first stack using Flask, Jinja, HTMX, and SQLite
- kept prompt versions as Markdown files while moving operational state into SQLite

Added:

- Flask application entrypoint with shared-hosting WSGI files
- SQLite-backed runs, suggestions, reviews, and tag persistence
- raw CSV artifact storage with hash-based deduplication
- prompt snapshot storage per imported run
- Python test coverage for core storage helpers

Preserved:

- home dashboard with imports and run history
- prompt library and prompt creation flow
- run review workflow with inline edits and right-side drawer
- insights view with cross-batch review and filtered review status pages
- top search across runs, prompts, rules, and review states

## [0.2.2] - 2026-04-12

Changed:

- made the hero copy span the full available width
- renamed sidebar navigation wording to `Prompt Library`
- moved drawer metadata into the main drawer header block

Improved:

- made the sidebar fixed and added a visible hamburger-style collapse toggle in the top bar
- reworked the Prompt Library selector into a single dropdown-style control
- aligned prompt preview width more closely with the rest of the page layout
- tightened cross-batch review table fitting so it no longer pushes the page horizontally
- improved run review and insights page section fitting within the main content area
- made drawer content and code blocks wrap more reliably without horizontal overflow

Fixed:

- replaced the unreliable prompt comparison chart with a simpler comparison view that renders consistently
- reduced overflow issues in review tables and right-side drawers

## [0.2.0] - 2026-04-12

Changed:

- reduced heading sizes for a less oversized UI
- made the left sidebar collapsible
- removed the redundant `New Review Cycle` sidebar block
- removed the redundant topbar `Prompt Registry` action
- simplified the home page content structure

Added:

- working top search with dropdown results
- prompt creation form that writes new Markdown prompt files
- horizontal prompt selector with full-width preview
- global reviewed-items table on the Insights page
- editable right-side drawers for run-level and cross-batch review flows
- filtered review pages for statuses and rule-based deep dives
- `Reviewed` stat based on `Review != Unreviewed`

Fixed:

- file-backed runs and reviews now render dynamically instead of being hidden by static page output
- imported runs are re-openable and review can continue over time
- run review table now fills the available width more predictably
- row detail view is drawer-based instead of always occupying screen space

## [0.1.0] - 2026-04-12

Initial release.

Added:

- Next.js local-first app scaffold with plain CSS styling
- prompt registry from Markdown files in `prompts/`
- CSV import flow tied to a selected prompt version
- persistent file-based storage for imports, runs, and reviews
- run review screen with inline evaluation controls
- insights page with prompt and rule-level summaries
- JetBrains Mono primary UI typography and Space Grotesk headings

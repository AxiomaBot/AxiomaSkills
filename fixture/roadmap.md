# Roadmap — demo-shop (fixture)

## Direction

`demo-shop` is a fixture project for the `agentic-workflow` plugin. Its only
direction is to stay the smallest repository that still satisfies every rule
the `workflow` skill's `check` mode enforces: two features (one closed, one in
flight), one chunk with a build contract, one dependency edge between
features, and one dark-ship gate that is real code rather than a UI hint.

## Features

| Feature | Status | One line |
|---------|--------|----------|
| [demo-widget](docs/features/demo-widget/feature.md) | building | List widgets behind the demo gate |
| demo-export | outlined | Export a widget list as CSV |
| demo-search | idea | Search widgets by name |

## Done

| Feature | Shipped | One line |
|---------|---------|----------|
| [demo-foundation](docs/features/demo-foundation/feature.md) | v0.1.0 | The widget store and its server-side gate |

## Backlog

- Pagination for very long widget lists.
- A second gate for per-owner visibility.

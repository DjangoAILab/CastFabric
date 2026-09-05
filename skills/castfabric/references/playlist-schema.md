# Playlist schema

Use a UTF-8 JSON document:

```json
{
  "version": 1,
  "name": "Morning",
  "description": "Optional description",
  "default_order": "sequential",
  "default_repeat": "none",
  "items": [
    {"type": "file", "path": "./01.mp3", "title": "Opening"},
    {"type": "url", "url": "https://example.test/02.mp3", "title": "Closing"}
  ]
}
```

Rules:

- `version` must be `1`.
- `items` must be a non-empty array processed in order.
- `file.path` resolves relative to the playlist file, not the shell working directory.
- `url.url` must be HTTP or HTTPS.
- `name` is required; order is `sequential` or `random`, repeat is `none` or `all`.
- Import uploads local files as persistent assets and creates URL assets once.
- Import is not synchronization. After import, CastFabric SQLite is the source of truth.
- Starting, monitoring, advancing, repeating, and stopping playback are server responsibilities.

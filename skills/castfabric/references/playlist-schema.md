# Playlist schema

Use a UTF-8 JSON document:

```json
{
  "version": 1,
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
- `--loop` repeats only after the last item ends.
- Stop the playlist runner before sending a target stop command; otherwise a stopped item could advance to the next item.

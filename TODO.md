# TODO

- [ ] Optimize local-track filtering/counting when the library grows large.
  Current code identifies local tracks with `stream_url LIKE '/resource/%'`, which scans `tracks` because `stream_url` is not indexed. This is fine for the current small library, but consider adding an explicit indexed field such as `is_local` or `source` before the library reaches tens or hundreds of thousands of tracks. Any schema change must follow the schema version and manual migration rules in `AGENTS.md`.

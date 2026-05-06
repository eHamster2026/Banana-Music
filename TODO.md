# TODO

- [x] Optimize local-track filtering/counting when the library grows large.
  Current code identifies local tracks with `stream_url LIKE '/resource/%'`, which scans `tracks` because `stream_url` is not indexed. This is fine for the current small library, but consider adding an explicit indexed field such as `is_local` or `source` before the library reaches tens or hundreds of thousands of tracks. Any schema change must follow the schema version and manual migration rules in `AGENTS.md`.

- [x] support cover/back/fanart/artist image, 但默认不显示，仅保留api
- [x] 增加ext字段，记录不能在当前数据库存放的其他元数据
- [x] 增加下载功能，下载时需要将数据库中的元数据写入文件

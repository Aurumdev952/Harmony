---
name: shell-compression-helpers
description: util/unix.py BackgroundProcess runs shell pipelines built from file paths; ruling on its noqa S602 and where its callers get their inputs
metadata:
  type: project
---

`util/unix.py` `BackgroundProcess` runs `Popen(command, shell=True)`. The commands come from
`util/file/compression` (`cat {fifo} | lz4 -3 > {output_file}`, `lz4cat "{filename}"`,
`pigz -d -c "{filename}"`), with paths interpolated unquoted or in double quotes, where `$()`
and backticks still expand. Traced on 2026-10-04 (WP-2f): every caller passes code-built paths.
These are pipeline scripts with operator flags, the `db/postgres/utils.py` export (temp dir plus
table names), and the web data-catalog validation route (`DATA_CATALOG_TABLES` constants plus
`tempfile.TemporaryDirectory()`). So nothing a request controls reaches the shell today.

**Why:** WP-2f accepted `# noqa: S602` on that line on this basis, and asked for an explicit core
item to replace the shell with argv `Popen` writing to the FIFO. The web and DB-export callers
mean WP-8d's pipeline rewrite will not remove it on its own.

**How to apply:** any WP that passes an upload's original file name, or any other request
value, into LZ4Reader/Writer, PigzReader/Writer or CommandLine{Compressor,Decompressor} is a high
finding (command injection). Check whether the core rewrite item has landed before accepting new callers.

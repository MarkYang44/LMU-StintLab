# Memory behavior and validation

Live capture keeps bounded float64 rings and a bounded loss-explicit writer queue. Display snapshots retain only exact numeric bytes; lane iteration reads timestamps, the selected value and both extrema directly. Sampling and drawing settings are unchanged. Two reusable shared-memory snapshots are compared byte-for-byte using native memcmp before decoding; no producer or game writes occur.

Offline lap groups, full comparison matrices and vehicle tables use fixed-width temporary files with two 64 KiB read pages. UTC text, missing values, flags and float64 values remain exact. Slices are lazy; interval median selection does not create a sorted Python float list. Temporary files are closed and deleted with their owning table. This exchanges disk I/O for lower Python heap peaks, without thinning samples or discarding channels.

Portable post-session analysis runs in a short-lived process at below-normal priority. It exits after report generation to release Python/native allocation peaks. Heavy automatic report work and RaceCom startup require at least 512 MiB of system commit headroom and 256 MiB of available physical memory. Otherwise the complete recording remains saved and a private report_pending.json marker is retried by the running menu/HUD or on next start. Failures remain explicit; deferred work does not hang normal shutdown.

Windows headroom is read with GetPerformanceInfo; no paging-file or operating-system settings are modified. Event 2004 distinguishes commit exhaustion from a process working set. Microsoft reference: https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/introduction-to-the-page-file . Reducing plugin memory cannot guarantee that a game exceeding the system commit limit will stop crashing.

Local validation uses private copies only. A 65 MiB / 291,501-sample complete recording reduced report peak working set from 88.30 to 78.22 MiB and peak private commitment from 70.77 to 61.38 MiB. This isolated processing benchmark took 26.52 versus 47.97 seconds. Parsed derived JSON remained identical, raw recordings and generated CSV/SVG/PNG remained byte-identical. These are workload-specific results, not a claim about all recordings or total game memory.

A 4,000-point / 19-double HUD snapshot also has a dedicated heap benchmark and an exact-value/wrap/extrema regression check. Tests cover disk cache bounds, missing and Unicode UTC values, exact medians, pressure deferral/retry, isolated worker exit and native image release on menu hiding.

Measured snapshot heap: 2,625,816 versus 646,624 bytes, a 75.4% reduction. This measures the temporary snapshot, not total application RAM.

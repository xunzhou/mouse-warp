# Cursor-loop measurements

Run this harness against two checkouts on the **same X server**, sequentially:

```bash
python3 perf/measure_cursor.py --repo /path/to/checkout --seconds 9
```

It imports that checkout's real main loop, uses its renderer and X11 connections,
and supplies deterministic synthetic input. All warps/focus actions are disabled,
the window is forced offscreen, and native cursor hide/show calls are suppressed.
It does not change the running service, move the user's pointer, or modify config.

## November 6, 2026: keep Python

The baseline was `0594e3d`; candidate `15cf1fe` adds adaptive frame scheduling,
frame reuse, and native pixel conversion. Both ran on this desktop's X.Org
12101025 server, without a compositor, using Pillow 13.0.0, the same 48px
Capitaine arrow, and maximum enlargement 5×. There were two controlled 9-second
runs per version, ordered candidate/baseline/baseline/candidate. Each repeated
3 seconds of synthetic 100Hz shaking and 1.5 seconds paused.

Ranges below describe the two runs, not pooled percentiles:

| Metric | Baseline | Candidate |
|---|---:|---:|
| Median active submission interval | 41.12–41.18 ms | 16.72–16.73 ms |
| 95th percentile interval | 48.58–48.59 ms | 17.46–17.57 ms |
| 99th percentile interval | 49.15–51.15 ms | 19.04–19.45 ms |
| Maximum interval | 51.02–51.83 ms | 20.47–26.92 ms |
| Median synthetic event-to-submission | 23.98–24.19 ms | 8.88–9.01 ms |
| 95th percentile event-to-submission | 45.97–46.17 ms | 16.48–16.70 ms |
| 95th percentile renderer update | 8.51 ms | 2.13–2.21 ms |
| Gaps over 25 ms / total active intervals | 335 / 335 | 1 / 859 |
| Process CPU, fraction of one core | 4.18–4.33% | 2.94–2.97% |

The dominant baseline problem is the 40ms sleep after work, not an inability to
render in Python within a 16.7ms budget. Scheduling and pixel-conversion fixes
substantially improve cadence and reduce CPU despite submitting more frames.
No additional rewrite or dependency change is justified by these measurements.

This does **not** measure input-to-photon latency, vsync, or visible tearing. The
response metric assigns each synthetic input event to the first XSync-completed
frame at least as new as that event; superseded samples count too. Startup and
inactive intervals are excluded. CPU is the benchmark process's CPU, excluding
X server work, during a mostly active workload; it is not idle daemon usage.
The two short runs do not establish long-term tail latency. One candidate gap
was 26.92ms; the harness cannot distinguish scheduling delay from server delay.

Remaining priorities: visually verify on the actual display, then only investigate
persistent stutter if it remains. Compositor-free binary transparency is a separate
appearance limitation that a language rewrite would not resolve.

Raw measurements: [2026-11-06-xorg.json](results/2026-11-06-xorg.json).
The candidate remains behind the existing visual-review gate; this benchmark
does not approve or deploy it.

## Fractional-scaling polish

A subsequent 9-second run with hotspot-aligned fractional resampling retained
16.72ms median and 17.38ms p95 submission intervals (maximum 21.54ms; no gaps
over 25ms). Synthetic response p95 was 17.01ms. Active benchmark CPU increased
to 4.62% of one core: more distinct resampled frames improve spatial continuity
at a modest CPU cost, while still meeting the frame budget in this run. This is
one follow-up run, not a repeat of the controlled two-run comparison above.

[Raw fractional-scaling result](results/2026-11-06-subpixel.json). Unit tests
check subpixel changes are not rounded into identical images and keep a symmetric
reference centered on its hotspot within 0.06 pixels over 64 fractional sizes.

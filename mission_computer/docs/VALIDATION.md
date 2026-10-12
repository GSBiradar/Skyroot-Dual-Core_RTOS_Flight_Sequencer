# Validation

## 1. How to run

```bash
make run            # 3 s default
make run ARGS=10    # 10 s soak
./flight_seq 30     # 30 s soak (binary directly)
```

The run is **self-checking**: it prints a health report and the seqlock/timing
invariants at the end.

## 2. Test matrix and pass criteria

| # | Test | How it is exercised | Pass criterion |
|---|---|---|---|
| V1 | Periodic release | `TMR_A` fires every 10 ms; FlightSeq counts releases | `flight heartbeats ≈ 100 × seconds`; `missed_rel == 0` |
| V2 | Sensor ingest + framing + CRC | simulator injects ~1 % corrupt frames | `frames + crc + (gaps) ≈ expected`; `crc > 0`; report stays consistent |
| V3 | Staleness / hold-last-good | sensor timeout or missing frame | FlightSeq keeps last-good and runs the safe fallback; a `F_S*_TIMEOUT` flag can appear transiently |
| V4 | Seqlock integrity | concurrent mailbox writes vs reads | `seqlock timeouts == 0` on target; a few may appear on the host (OS-preempted writer) and the reader falls back to last-good |
| V5 | Feedback fixed boundary | SlowComp result carries `activate_frame` | new feedback only applied at `frame % 20 == 0`; `fb_stale > 0` only before the first result or on a late result |
| V6 | Watchdog gating | supervisor kicks only when critical mask clear | `kicks ≫ skips` on a healthy run; skips track fault windows (CRC/busy/stale) |
| V7 | Non-blocking TX | actuator/telemetry DMA busy injection | `act_busy`/`tlm_busy` counted, **never** a hang; run always completes |
| V8 | WCET | `seq_exec_us` each cycle | stays well below the 3000 µs budget; `seq_exec_max_us` reported |

## 3. Reading a healthy run

A good 3-second run looks like (numbers vary because faults are random):

```
 sensor1 ... : ~560-600 frames, crc ~6, seq_gap ~6, sync_err ~3-6
 sensor2 ... : ~295-300 frames, crc ~3, seq_gap ~3, sync_err ~3-6
 flight      : ~300 heartbeats, missed_rel 0, max_us << 3000
 actuator    : ~295 tx, tx_err ~3, busy ~3-8
 slow        : ~15 heartbeats, fb_stale 0-1
 supervisor  : ~300 cycles, tlm ~294, tlm_busy ~3-9
 watchdog    : kicks ~280, skips small (fault windows)
 seqlock     : timeouts 0
 last flags  : 0x00000000
```

Interpretation:

- **`seq_gap ≈ crc`** because a corrupt frame is discarded, so the next good
  frame's sequence shows the hole — consistent, expected.
- **`fb_stale ≈ 1`** near the start because no feedback exists yet on the first
  boundary; the sequencer correctly holds its previous (zero) value.
- **`watchdog skips`** are the edge-triggered fault windows (a CRC error or a
  busy actuator occurred in that cycle); they are the mechanism *working*, not a
  failure. `last flag word == 0` means the system finished healthy.
- **`seqlock retries > 0` with `timeouts == 0`** is the ideal proof: the seqlock
  detected an overlapping write and the bounded retry recovered a clean
  snapshot. On the host a small number of **timeouts** (`retries` exhausted) is
  normal: an OS-preempted writer thread can remain mid-write far longer than the
  target's ~0.2 µs local-IRQ-masked window. When that happens the reader returns
  `false` and the caller holds its last-good copy, so the behaviour is still
  safe — only the reported counter reflects host scheduling.

## 4. Failure signals to watch for

| Symptom | Likely cause |
|---|---|
| `missed_rel > 0` growing | consumer too slow / host overloaded; on target a real deadline miss |
| `seq_exec_max_us ≈ 3000` or higher | WCET breach → `F_SEQ_OVERRUN`, watchdog held |
| `seqlock timeouts > 0` | a writer never released `seq` (bug) or retries too small |
| `watchdog skips == cycles` | a permanently latched fault (regression of improvement I1) |
| `tlm_busy` or `act_busy` never decreasing | TX never completes |
| `fb_stale` growing | slow task or boundary logic stalled (`F_SLOW_STALLED`) |

## 5. Determinism / reproducibility

The fault model uses `rand()`, so counter values differ run-to-run by design.
For a byte-for-byte reproducible trace, seed the generator at the top of
`HwSimThread` (or `BSP_RunForSeconds`) with a fixed seed:

```c
srand(1234u);   /* add for deterministic fault injection */
```

The *architecture* is deterministic; only the injected fault pattern is random.

## 6. Soak

```bash
make run ARGS=60
```

Longer runs increase confidence that heartbeat counts stay proportional to time,
`missed_rel` stays 0, `seq_exec_max_us` stays bounded, the watchdog keeps being
kicked, and no counter drifts unexpectedly.

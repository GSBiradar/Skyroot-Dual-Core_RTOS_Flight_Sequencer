# Design Decisions

This document records *why* the implementation is the way it is, and calls out
where it deliberately improves on the literal assessment pseudocode. Each entry
follows the shape **Context → Decision → Consequence**.

---

## D1. Core split: sequencer alone on Core 1

- **Context.** Two 10 ms-class activities (the sequencer and the supervisor)
  plus 5/10 ms sensor ingest and a 40 ms slow task must share two cores.
- **Decision.** Core 1 runs **only** `FlightSeqTask` and its timer ISR. Core 0
  runs everything asynchronous (ingest, supervisor, slow task) plus all UART
  interrupts.
- **Consequence.** The sequencer's jitter is bounded by a 3 µs timer ISR and bus
  contention; no background task or interrupt can extend its worst-case
  response. Core 1 keeps spare capacity for growth; Core 0 is the jitter
  absorber.

## D2. RX = DMA + idle-line interrupt; TX = DMA + polled completion

- **Context.** Per-byte RX interrupts would fire ~13 000/s; polling would burn a
  core and add jitter.
- **Decision.** Sensors receive via **circular DMA + idle-line (frame-end)
  interrupt** (~300 ISR/s for both). Actuator and telemetry transmit via **DMA
  with polled completion**.
- **Consequence.** Bytes land at zero CPU cost; one short ISR per frame defers
  all validation to `SensorIngestTask`. TX never spins because the wire times
  (0.26 / 0.64 ms) are far shorter than the 10 ms period and the completion is
  known within ~1 byte time.
- **Rule applied.** Interrupt where arrival is *asynchronous*; poll where we
  *control* the timing.

## D3. Seqlock mailboxes instead of mutexes on the hard path

- **Context.** Nav data, sequencer output and the feedback loop all cross cores
  or rates, and the reader must never block on the writer.
- **Decision.** A single-writer seqlock per object (see `include/mailbox.h`).
- **Consequence.** The writer is wait-free; the reader has a bounded, tiny
  worst case and never waits on a lower-priority task. This sidesteps the
  cross-core priority-inversion problem entirely. Cost: the reader may retry a
  few times under contention (observed as `seqlock retries` in the report).

## D4. Fixed-boundary feedback activation

- **Context.** The 200 ms result finishes at an arbitrary instant; applying it
  immediately makes the 10 ms sequencer's behaviour depend on host scheduling.
- **Decision.** `FbMsg_t` carries `activate_frame`; `FlightSeqTask` latches new
  feedback **only** when `frame % 20 == 0` and `activate_frame <= frame`.
- **Consequence.** The closed loop is repeatable and testable; if the slow result
  is late the previous value is held and `fb_stale_cnt` is raised.

## D5. Counting notifications for periodic release

- **Context.** Periodic tasks are released by hardware timers, not by soft
  timers, to avoid tick jitter; but a missed release must be visible.
- **Decision.** The timer ISR uses a **counting** notification
  (`BSP_NotifyGiveFromIsr`). The task reads the count
  (`BSP_NotifyTake(true, ...)`); a value `> 1` means releases were missed.
- **Consequence.** `seq_missed_rel` exposes scheduling failures directly instead
  of hiding them as silent drift.

## D6. Atomic health, one writer per field

- **Context.** Health must be observed coherently by the 10 ms supervisor without
  a lock (a lock would add a cross-core dependency on the hard path).
- **Decision.** `Health_t` fields are `_Atomic uint32_t`, each with exactly one
  writer. The supervisor reads with relaxed atomic loads.
- **Consequence.** No torn reads, no locks, no lost updates. On the target the
  fields live one-per-cache-line (64 B aligned struct) to avoid false sharing.

## D7. Watchdog gated on health

- **Context.** A watchdog that always gets kicked provides no protection.
- **Decision.** Only `SupervisorTask` kicks the watchdog, and only when the
  critical fault mask is clear.
- **Consequence.** Missed timing, stale sensors, CRC faults and stalled tasks
  turn into a withheld kick — i.e. observable safety behaviour.

---

## Improvements over the literal assessment pseudocode

The assessment's pseudocode is a strong starting point but contains a few
details that would misbehave as written. This implementation keeps the
architecture and fixes these:

### I1. Edge-triggered FDIR in the supervisor

The pseudocode does:

```c
if (g_health.s1_crc_err || g_health.s2_crc_err) flags |= F_NAV_CRC;
```

`*_crc_err` is a **cumulative** counter, so a single CRC error early in the run
latches `F_NAV_CRC` forever and the watchdog is **never kicked again**. The
implementation instead compares against the previous cycle and flags only *new*
faults (deltas), so the watchdog keeps guarding while the system is healthy and
holds off only around genuine faults (`src/modules/flight_sequencer.c`,
`SupervisorTask`). Same treatment for `act_busy_cnt`, `fb_stale_cnt`,
`seq_missed_rel`; overrun uses the *last* cycle's execution time
(`seq_exec_us`), not the cumulative `seq_exec_max_us`.

### I2. Feedback message size

The pseudocode reads `FB_LEN` (16) bytes into an `FbMsg_t` that also holds
`cycle_id` and `activate_frame`. This implementation publishes/reads
`sizeof(FbMsg_t)` so the control fields travel atomically with the payload,
while the *on-wire* feedback payload stays 16 bytes (`FbPayload_t`).

### I3. First-frame sequence-gap

`gap = seq - last_seq - 1` with `last_seq` initialised to 0 reports a bogus
255-frame gap on the first frame. `last_seq` is pre-loaded to `0xFF`
(`FlightSequencer_Init`) so the first frame is gap-free.

### I4. Simulator seals the CRC before corrupting

The host simulator must inject *frame* corruption, not corrupt a frame and then
recompute a matching CRC. `ProduceFrame()` computes and writes the CRC over the
clean frame, then flips a payload byte — so the receiver's CRC check actually
fails (`platform/host_bsp.c`).

### I5. Delta-based actuator/telemetry busy reporting

`act_busy_cnt` / `tlm_busy` count cycles where the DMA channel was still busy;
they are reported directly, and the supervisor's `F_ACT_TX` is edge-triggered to
avoid a similar latch.

---

## Host-simulation caveats (read before judging timing numbers)

The host port **cannot** reproduce true per-core preemption: it models the two
cores as OS threads and the timers/ISRs as a simulator thread. Therefore:

- `seq_exec_max_us` reflects the placeholder compute + host jitter, not a target
  WCET. It is expected to be tens of microseconds here; the **3 ms budget** in
  the design is a target figure to be re-measured on the MCU.
- Frame arrival jitter and any `missed_rel` seen on the host are OS-scheduling
  artefacts. The point of the host run is to exercise the **logic** (seqlock,
  boundary latch, FDIR, watchdog gating, TX non-blocking), all of which behave
  exactly as on the target.
- On Linux the tasks are pinned to logical CPUs via `pthread_setaffinity_np`;
  on Windows they run as ordinary threads.

---

## Assumptions carried from the assessment

| # | Assumption |
|---|---|
| A1 | Dual-core 32-bit MCU (≥ 200 MHz), shared SRAM, hardware atomics, shared 1 µs timebase, per-interrupt core routing, watchdog. |
| A2 | Shared RAM non-cacheable/coherent; shared objects 64-byte aligned (false-sharing control). |
| A3 | SMP, preemptive, fixed-priority RTOS, hard core affinity, 1 kHz tick, static allocation. |
| A4 | RS422/UART at 1 Mbaud, 8N1 (10 µs/byte), per-port DMA + idle-line detection. |
| A5 | Frame = 2 B sync + 1 B seq + 1 B len + payload + 2 B CRC16 (6 B overhead). |
| A6 | Sensors push frames autonomously; phase relative to the MCU is unknown. |
| A7 | WCET budgets: ISR 5 µs, ingest 40 µs, FlightSeq 3 ms, supervisor 200 µs, slow 40 ms. |
| A8 | Cyclic tasks never block for data; stale/invalid input ⇒ hold last good, flag, degraded mode. |
| A9 | The 200 ms feedback is applied only at a fixed frame boundary (every 20th frame). |

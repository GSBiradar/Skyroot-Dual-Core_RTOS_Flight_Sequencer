# Architecture

## 1. Cores

```
                         +---------------------------+
                         |       Dual-core MCU        |
                         |  shared, non-cacheable SRAM|
                         +-------------+-------------+
                                       |
          +----------------------------+----------------------------+
          |                                                         |
  +-------v--------+                                       +--------v--------+
  |     CORE 0     |                                       |     CORE 1      |
  | I/O + housekeep|                                       | HARD REAL-TIME  |
  |                |                                       |                 |
  | T1 Ingest   (5)|                                       | T2 FlightSeq (5)|
  | T3 Supervisor(4)|                                      |                 |
  | T4 SlowComp (2)|                                       |                 |
  | idle         (0)|                                      | idle         (0)|
  |                |                                       |                 |
  | I1 I2 UART ISR |                                       | I3 TMR_A ISR    |
  | I4 TMR_B ISR   |                                       |                 |
  +-------+--------+                                       +--------+--------+
          |                                                         |
   UART_S1 UART_S2 UART_ACT UART_TLM                         (compute only)
```

- **Core 1 is deterministic by construction.** It runs only `FlightSeqTask` and
  its 3 µs timer ISR. No UART interrupt, no logging, nothing lower-priority can
  run there, so jitter comes only from the timer ISR and shared-bus contention.
- **Core 0 absorbs every asynchronous event**: sensor frame interrupts, ingest,
  the supervisor and the 200 ms slow computation. The slow task is *lowest*
  priority on Core 0, so everything that matters preempts it.

## 2. Data flow

```
 Sensor 1 (5 ms)  --DMA ring--> UART_S1_IRQ --notify(EVT_S1)--> T1 Ingest
 Sensor 2 (10 ms) --DMA ring--> UART_S2_IRQ --notify(EVT_S2)--> T1 Ingest
                                                                    |
                              seqlock mailbox g_nav1 / g_nav2  <----+
                                                                    |
                                              +---------------------+---------------------+
                                              v                                           v
                                        T2 FlightSeq (Core 1)                        T4 SlowComp (Core 0)
                                        - snapshot nav                             - snapshot nav + g_seqOut
                                        - latch feedback @frame%20                 - CalculateSlowDynamics
                                        - ComputeFlightActuation                   - publish g_fb + activate_frame
                                        - publish g_seqOut (seqlock)  ------------>
                                        - actuator DMA TX (20 B)
                                        - health counters
                                              ^
                                              |  g_fb (seqlock, latched at boundary)
                                              |
 T3 Supervisor (10 ms) --atomic reads--> build telemetry --DMA TX (UART_TLM)
        |
        +--> Wdt_Kick() only if critical flags clear
```

## 3. IPC choices

| Data / event | Mechanism | Why |
|---|---|---|
| Frame received | **Direct bit notification** (ISR → T1) | Lightest unblock primitive, same core, no allocation. |
| Nav 1 / Nav 2 latest | **Seqlock latest-value mailbox** | Only the newest sample matters; a queue would grow stale or drop. |
| Periodic release | **Counting notification** (I3→T2, I4→T3/T4) | Hardware-driven; the count also reveals missed releases. |
| Sequencer output (16 B) | **Seqlock mailbox** `g_seqOut` | Wait-free for the 10 ms writer. |
| Feedback (16 B) | **Seqlock mailbox** `g_fb` + `activate_frame` | Reader never blocks on the slow task; result activates at a fixed boundary. |
| Actuator command (20 B) | **T2-owned DMA buffer** | Single owner; nothing to share. |
| Health counters | **Atomic counters/timestamps**, one writer per field | Supervisor observes faults with no lock. |
| Watchdog | Kicked only by T3 when critical flags are clear | Converts missed timing/stale data into observable reset behaviour. |

## 4. The seqlock mailbox

`include/mailbox.h`:

- `seq` is even when the snapshot is stable, odd while a writer is mid-copy.
- The **writer** is wait-free: it takes a ~0.2 µs critical section (local IRQ
  mask), bumps `seq` to odd, publishes with a release fence, copies the payload,
  then bumps `seq` to even with a release fence. It never spins.
- The **reader** copies the payload, re-reads `seq`, and retries on overlap —
  bounded to `MBX_MAX_RETRY` attempts. If every attempt overlapped, it returns
  `false` and the caller keeps its last-good local copy. **The hard-real-time
  consumer therefore never blocks and never waits on a lock held by a
  lower-priority task.**

On the host, C11 `atomic_load/store_explicit` with acquire/release fences provide
the same ordering; on ARM the fences map to `DMB`.

## 5. Why there are no mutexes on the hard path

- Kernel priority inheritance does not work across cores, so a cross-core mutex
  could leave T2 (Core 1) blocked behind T4 (Core 0).
- Every shared object has exactly **one writer**, so a lock-free latest-value
  protocol is sufficient and has a bounded reader cost.
- The only exclusion the application ever takes is `BSP_LocalIrqSave/Restore`
  around a mailbox write (~0.2 µs), which cannot deadlock (no nesting) and
  cannot block another core.

## 6. Files and responsibilities

| File | Responsibility |
|---|---|
| `include/types.h` | Sizes, rates, frame format, `Health_t`, `Mbx_t`, payload types. |
| `include/mailbox.h` | Header-only seqlock publish/read. |
| `include/bsp_api.h` | The **only** interface the application depends on. |
| `src/modules/flight_sequencer.c` | Tasks T1–T4, ISRs I1–I4, init, report. |
| `src/main.c` | Host entry: init → run → report. |
| `platform/host_bsp.c` | Host port + fault-injecting hardware simulator. |
| `config/simulation.h` | Run length and injected fault rates. |

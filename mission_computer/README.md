# Flight Sequencer — Dual-Core RTOS Firmware (host-runnable reference)

A complete, **executable** implementation of the Flight Sequencer design described
in `docs/` and the supplied assessment: a launch-vehicle flight sequencer running
on a dual-core MCU under a preemptive, fixed-priority RTOS.

The application (`src/modules/flight_sequencer.c`) is written **only** against the
board-support contract in `include/bsp_api.h`. On a real target that contract is
implemented over FreeRTOS-SMP / CMSIS-RTOS2 / a vendor HAL; on a PC it is
implemented by `platform/host_bsp.c`, which simulates both cores, the four RS422
ports, the timers and the watchdog — so the exact same flight code compiles and
**runs on Windows and Linux**.

---

## 1. Design at a glance

| Aspect | Decision |
|---|---|
| **Core split** | **Core 1** = dedicated hard-real-time core, runs *only* the Flight Sequencer. **Core 0** = all asynchronous I/O, ingest, supervision and the 200 ms computation. |
| **Sensor RX** | DMA circular ring + frame-end (idle-line) interrupt; validation deferred to `SensorIngestTask`. One ISR per frame. |
| **Output TX** | DMA transmit, **polled completion** (we control the timing, so no TX interrupt needed). |
| **IPC** | Direct task **notifications** for events; **counting** notifications for periodic release; single-writer **seqlock mailboxes** for all cross-core / cross-rate data. **No mutexes on the hard path.** |
| **Feedback loop** | The 16 B slow result carries `activate_frame` and is latched by the sequencer only on a fixed **20-frame boundary** → repeatable behaviour. |
| **Health** | One writer per field, atomic counters/timestamps; the supervisor reads them lock-free. |
| **Watchdog** | Kicked **only** by the supervisor, and only when all critical health flags are clear. |
| **Margins** | FlightSeq ≈ 3.9 ms worst-case response vs 10 ms deadline (≈6 ms slack); Core 0 ≈ 23 %, Core 1 ≈ 30 %. |

Task / ISR map (higher priority number = more urgent):

| ID | Name | Core | Prio | Trigger | Budget |
|---|---|---|---|---|---|
| I1/I2 | `UART_S1/S2_IRQHandler` | 0 | IRQ 1 | sensor frame end, 5 / 10 ms | 5 µs |
| I3 | `TMR_A_IRQHandler` | 1 | IRQ 2 | 10 ms, phase 0 | 3 µs |
| I4 | `TMR_B_IRQHandler` | 0 | IRQ 2 | 10 ms, phase +6 ms | 3 µs |
| T1 | `SensorIngestTask` | 0 | 5 | I1/I2 notification | 40 µs/frame |
| T2 | `FlightSeqTask` | **1** | 5 | I3 notification | 3 ms |
| T3 | `SupervisorTask` | 0 | 4 | I4 notification | 200 µs |
| T4 | `SlowCompTask` | 0 | 2 | every 20th frame | 40 ms |

---

## 2. Build & run

### From PowerShell / cmd (MinGW-w64 `gcc` on PATH)

```powershell
gcc -std=c11 -O2 -Iinclude -Iconfig `
    src/main.c src/modules/flight_sequencer.c platform/host_bsp.c `
    -o flight_seq.exe -pthread
.\flight_seq.exe          # runs ~3 s, prints a health report, exits
```

### From Ubuntu / WSL

```bash
sudo apt install -y build-essential          # gcc + make (+ pthreads)
cd "/mnt/c/Users/Guru SB/Downloads/Qosmic/mission_computer"
make run                                     # build + run
```

### With `make` on either platform

```bash
make            # build flight_seq(.exe)
make run        # build then run (override length: make run ARGS=5)
make clean
```

### With CMake

```bash
cmake -S . -B build
cmake --build build
./build/flight_seq   3      # optional: run length in seconds
```

The program takes an optional single argument: run length in seconds
(default **3**, from `config/simulation.h`).

---

## 3. What the output means

A 3-second run prints a report like this (numbers vary slightly because faults
are injected at random):

```
============== Flight Sequencer health report (dual-core) ==============
 sensor1  frames / crc / seq_gap / sync_err : 593 / 7 / 7 / 5
 sensor2  frames / crc / seq_gap / sync_err : 299 / 1 / 1 / 8
 flight   heartbeats / missed_rel / max_us  : 299 / 2 / 19
 actuator tx / tx_err / busy_cnt            : 287 / 6 / 6
 slow     heartbeats / exec_us / fb_stale   : 15 / 1 / 0
 supervisor heartbeats / tlm / tlm_busy     : 300 / 294 / 6
 watchdog kicks / skips                     : 283 / 17
 ---------------- seqlock + timing invariants ----------------
 seqlock reads / retries / timeouts         : 658 / 1 / 0
 last supervisor flag word                  : 0x00000000
 wdt kicks observed by BSP                  : 283
========================================================================
```

| Line | Meaning |
|---|---|
| `sensor1/2 frames` | Frames that passed CRC and were published (5 ms ⇒ ~600, 10 ms ⇒ ~300 in 3 s). |
| `crc` | Frames that arrived but failed the CRC → **discarded**, counter raised. The simulator corrupts ~1 % on purpose. |
| `seq_gap` | Missing frame-sequence numbers (a dropped/corrupt frame shows up here). |
| `sync_err` | UART overrun/framing/noise events (line faults, ~1 %). |
| `flight heartbeats` | FlightSeq 10 ms releases that ran (~300). |
| `missed_rel` | Counting-notification backlog: a release was pending more than once → missed deadline. Should be ~0. |
| `max_us` | Worst measured FlightSeq execution time. Must stay ≪ 3000 µs budget. |
| `actuator tx / tx_err / busy` | DMA frames started / link-rejected / channel still busy next cycle (never blocks). |
| `slow heartbeats` | 200 ms feedback cycles (~15). |
| `fb_stale` | Boundary latches where no fresh feedback was eligible → previous value held. |
| `supervisor / tlm / tlm_busy` | Supervisor cycles, telemetry frames sent, telemetry DMA busy next cycle. |
| `watchdog kicks / skips` | Supervisor cycles that kicked the watchdog vs. held off because a critical flag was set. |
| `seqlock reads / retries / timeouts` | Mailbox reads, reads that overlapped a write and retried, and reads that exhausted the bounded retries. Retries prove the seqlock is doing its job; **timeouts should be 0 on target**. A few timeouts can appear on the host because an OS-preempted writer thread may stay mid-write for milliseconds (on target the write window is a local-IRQ-masked ~0.2 µs); the reader safely falls back to its last-good copy, so it is still correct. |
| `last flag word` | Supervisor fault flags at the end (0 = healthy). |

**Injected faults are the point:** the small non-zero `crc`, `sync_err`,
`tx_err` and `busy` counts are the simulator deliberately stressing the safety
paths — bad frames are rejected and counted, stale inputs hold last-good, and
the watchdog withholds its kick while a fault is active.

---

## 4. Repository layout

```
mission_computer/
├── CMakeLists.txt              # CMake build
├── Makefile                    # make build (Windows + Linux)
├── README.md                   # this file
├── config/
│   └── simulation.h            # run length + injected fault rates
├── include/
│   ├── types.h                 # sizes, rates, frame format, Health_t, Mbx_t
│   ├── mailbox.h               # single-writer seqlock mailbox (header-only)
│   ├── bsp_api.h               # RTOS + hardware contract (the porting surface)
│   └── flight_sequencer.h      # module public API
├── platform/
│   └── host_bsp.c              # POSIX host port: 2 cores + 4 RS422 + timers + WDT
├── src/
│   ├── main.c                  # host entry point
│   └── modules/
│       └── flight_sequencer.c  # ALL application logic (tasks, ISRs, mailboxes)
├── scripts/
│   └── generate_timing_plots.py# produce timing figures from the model
└── docs/
    ├── ARCHITECTURE.md         # cores, tasks, ISRs, IPC, data flow
    ├── DESIGN_DECISIONS.md     # why each choice, and improvements over pseudocode
    ├── VALIDATION.md           # test plan + how to read a run
    ├── TRACEABILITY.md         # assessment criterion -> code location
    └── INTEGRATION.md          # porting to a real dual-core MCU
```

---

## 5. Porting to a real target

Only `platform/host_bsp.c` is host-specific. To move to hardware you re-implement
`include/bsp_api.h`; `src/modules/flight_sequencer.c` is unchanged. See
`docs/INTEGRATION.md` for the FreeRTOS-SMP / CMSIS-RTOS2 mapping, the shared-RAM
and memory-barrier requirements, and how the timer ISRs replace the host sim.

## 6. Documents

- **`docs/ARCHITECTURE.md`** — the system on one page.
- **`docs/DESIGN_DECISIONS.md`** — decision records + what this implementation
  improves over the literal assessment pseudocode.
- **`docs/VALIDATION.md`** — the validation plan and how each result is checked.
- **`docs/TRACEABILITY.md`** — criterion-to-code map.
- **`docs/INTEGRATION.md`** — target porting guide.

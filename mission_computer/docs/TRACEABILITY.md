# Evaluation Traceability

Where each assessment evaluation criterion is addressed in this package.

| Criterion | Evidence in this package | Primary locations |
|---|---|---|
| **Real-time determinism** | Dedicated Core 1 for the sequencer; hardware-timer release; DMA RX with deferred validation; wait-free writers and bounded readers; missed-release detection; overrun counter; watchdog gating. | `docs/ARCHITECTURE.md §1`, `src/modules/flight_sequencer.c` (`FlightSeqTask`, `TMR_A_IRQHandler`), `include/mailbox.h`, `docs/DESIGN_DECISIONS.md D1/D5/D7` |
| **RTOS fundamentals (IPC choice)** | Direct bit notifications (events), counting notifications (periodic release), seqlock mailboxes (state), single-owner DMA buffers (TX), atomic health; no mutexes on the hard path. | `docs/ARCHITECTURE.md §3`, `include/bsp_api.h`, `src/modules/flight_sequencer.c` (all tasks/ISRs) |
| **Multi-core competency** | Core-1 isolation; four single-writer mailboxes as the only cross-core boundary; release/acquire fences; non-cacheable shared RAM + 64-byte alignment; local IRQ mask instead of an SMP kernel lock. | `docs/ARCHITECTURE.md §2/§5`, `include/types.h` (`Mbx_t`), `include/mailbox.h`, `src/modules/flight_sequencer.c` (`BSP_LocalIrqSave`) |
| **Engineering judgment** | Nine documented assumptions; explicit WCET/frame budgets; stale-data hold-last-good policy; fixed-boundary feedback activation; documented improvements over pseudocode. | `docs/DESIGN_DECISIONS.md` (assumptions table + improvements I1–I5), `include/types.h` (budgets/limits) |
| **Interrupt vs polling depth** | Per-port decision (interrupt for asynchronous RX, polled DMA completion for TX) with the CPU/interrupt-rate rationale. | `docs/DESIGN_DECISIONS.md D2`, `src/modules/flight_sequencer.c` (`UART_*_IRQHandler`, actuator/TLM TX) |
| **Synchronization depth** | Seqlock writer wait-free / bounded reader retries; no nested locks; no cross-core lock; correctness under injected concurrency stress (reported retries/timeouts). | `include/mailbox.h`, `docs/ARCHITECTURE.md §4`, `docs/VALIDATION.md V4` |

## Criterion → code cross-reference

| Symbol in the assessment | Implementation |
|---|---|
| `Mbx_Publish` / `Mbx_Read` | `include/mailbox.h` |
| `g_nav1`, `g_nav2`, `g_seqOut`, `g_fb` | `src/modules/flight_sequencer.c` (file statics) |
| `IngestOne`, `SensorIngestTask` (T1) | `src/modules/flight_sequencer.c` |
| `UART_S1/S2_IRQHandler` (I1/I2) | `src/modules/flight_sequencer.c` |
| `TMR_A/B_IRQHandler` (I3/I4) | `src/modules/flight_sequencer.c` |
| `FlightSeqTask` (T2) | `src/modules/flight_sequencer.c` |
| `SupervisorTask` (T3) | `src/modules/flight_sequencer.c` |
| `SlowCompTask` (T4) | `src/modules/flight_sequencer.c` |
| `ComputeFlightActuation`, `CalculateSlowDynamics` | `src/modules/flight_sequencer.c` (placeholder, A8) |
| `Health_t`, `g_health` | `include/types.h`, `src/modules/flight_sequencer.c` |
| `main` / init sequence | `src/main.c`, `FlightSequencer_Init` |
| BSP call surface | `include/bsp_api.h` + `platform/host_bsp.c` |

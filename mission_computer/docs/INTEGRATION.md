# Integration / Porting Guide

The application is deliberately isolated from the hardware. **Only
`platform/host_bsp.c` is host-specific.** To run on a target you re-implement
`include/bsp_api.h`; `src/modules/flight_sequencer.c` does not change.

## 1. What you must provide

Implement every function in `include/bsp_api.h` over your RTOS + vendor drivers:

| BSP function | FreeRTOS-SMP | CMSIS-RTOS2 | Notes |
|---|---|---|---|
| `BSP_TaskCreate` | `xTaskCreateAffinitySet` | `osThreadNew` + affinity | static allocation; pin core |
| `BSP_NotifySetBitsFromIsr` | `xTaskNotifyFromISR(..., eSetBits, ...)` | `osThreadFlagsSet` | short, from ISR |
| `BSP_NotifyWaitBits` | `xTaskNotifyWait` | `osThreadFlagsWait` | returns decoded bits |
| `BSP_NotifyGiveFromIsr` | `vTaskNotifyGiveFromISR` | (flag or counting sem) | counting release |
| `BSP_NotifyTake` | `ulTaskNotifyTake` | `osSemaphoreAcquire` | returns the count |
| `BSP_LocalIrqSave/Restore` | `taskENTER/EXIT_CRITICAL_FROM_ISR` or `portSET_INTERRUPT_MASK` | `__disable_irq` region | **local core only** |
| `BSP_TimerStartPeriodic` | hardware timer + ISR, or `xTimer` | `osTimer` | prefer HW timer for jitter |
| `BSP_DmaRxCircular` | vendor UART DMA | vendor UART DMA | circular buffer |
| `BSP_DmaTxStart/Busy` | vendor UART DMA | vendor UART DMA | one-shot + busy flag |
| `BSP_WdtKick` | `wdt_feed` | `HAL_IWDG_Refresh` | supervisor only |

`BSP_ClockInit`, `BSP_HwTimeUs/Ms`, `BSP_Rs422Init`, `BSP_Uart*` map directly to
the BSP/driver layer.

## 2. Shared memory & memory ordering (critical)

1. **Map shared RAM non-cacheable** (or use hardware-coherent RAM) and place
   every `Mbx_t` and `Health_t` there. Otherwise the seqlock fences order only
   one core's view.
2. **64-byte align** each mailbox and one-writer-per-field health block to avoid
   false sharing — `Mbx_t` is already sized/aligned in `include/types.h`; add
   `alignas(64)` / `__attribute__((aligned(64)))` for the target.
3. The acquire/release fences in `include/mailbox.h` map to `DMB ISH` on ARM
   Cortex. Confirm your compiler maps `atomic_thread_fence` accordingly, or
   insert an explicit `__DMB()`.

## 3. Interrupt routing

Route exactly as in the assessment init sequence:

```
Irq_Route(IRQ_UART_S1, CORE0, LVL1);   Irq_Route(IRQ_UART_S2, CORE0, LVL1);
Irq_Route(IRQ_TMR_B,   CORE0, LVL2);   Irq_Route(IRQ_TMR_A,   CORE1, LVL2);
```

Keep all interrupt priorities numerically at or below the kernel's syscall
ceiling so the `*FromISR` APIs remain legal.

## 4. First run after porting

1. **Do not** enable the watchdog until the supervisor is proven to kick it.
2. Verify `seq_hb` increments every 10 ms and `missed_rel` stays 0.
3. Verify `seqlock timeouts == 0` under load.
4. Verify `seq_exec_us` is below the 3 ms budget; if not, revise the budget with
   measured evidence (this is a validation item in the assessment).
5. Verify a late/silent sensor produces hold-last-good + a timeout flag and a
   withheld watchdog kick.

## 5. Using the host simulator as a HIL harness

`platform/host_bsp.c` is intentionally a drop-in stand-in:

- Point it at real serial ports / a socket bridge and it becomes a HIL test
  driver for the flight code without a board.
- `config/simulation.h` controls run length and injected fault rates, so you can
  regression-test the FDIR paths (CRC, line errors, TX busy/reject) in CI.

## 6. Two-ESP32 prototype note

Two ESP32 boards can demonstrate the *distributed* concepts (dual producers,
shared-state handoff), but they cannot faithfully replace the assessed
**single dual-core MCU with shared SRAM and hardware atomics**. If used,
present them as a prototype/HIL extension, not as the assessed architecture.

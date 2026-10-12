/*
 * bsp_api.h
 *
 * Board-support / RTOS contract. The application (src/modules/flight_sequencer.c)
 * is written ONLY against this header. On the target it is implemented over a
 * FreeRTOS-SMP-style preemptive RTOS + vendor UART/DMA/timer drivers; on the
 * host it is implemented by platform/host_bsp.c, which simulates both cores,
 * the four RS422 ports, the hardware timers and the watchdog.
 *
 * Conventions
 * -----------
 *   - Opaque handles are void*.
 *   - Priorities: higher number == higher priority.
 *   - timeout_ms == BSP_WAIT_FOREVER blocks until satisfied.
 *   - All *FromIsr calls are short and non-blocking.
 */
#ifndef FS_BSP_API_H
#define FS_BSP_API_H

#include <stdint.h>
#include <stdbool.h>
#include "types.h"

#define BSP_WAIT_FOREVER 0xFFFFFFFFu
#define BSP_MAX_DELAY    0xFFFFFFFFu

/* RS422 / UART port identifiers */
#define UART_S1   1u
#define UART_S2   2u
#define UART_ACT  3u
#define UART_TLM  4u

/* Hardware timers */
#define TMR_A     0u   /* FlightSeq release, 10 ms, phase 0   */
#define TMR_B     1u   /* Supervisor/Slow release, +phase ms  */

/* UART status bits */
#define UART_IDLE   (1u << 0)
#define UART_ORE    (1u << 1)   /* overrun   */
#define UART_FE     (1u << 2)   /* framing   */
#define UART_NE     (1u << 3)   /* noise     */

typedef void *BSP_TaskHandle;
typedef void (*BSP_IsrFn)(void);

/* ---------------- Time ---------------- */
void     BSP_ClockInit(void);
uint64_t BSP_HwTimeUs(void);
uint64_t BSP_HwTimeMs(void);

/* ---------------- Tasks & notifications ---------------- */
bool BSP_TaskCreate(void (*entry)(void *), const char *name,
                    uint32_t stack_words, void *arg,
                    uint32_t priority, uint32_t core,
                    BSP_TaskHandle *out);

/* Direct-to-task bit notification (event handshake). */
void     BSP_NotifySetBitsFromIsr(BSP_TaskHandle t, uint32_t bits);
uint32_t BSP_NotifyWaitBits(uint32_t clear_mask, uint32_t timeout_ms);

/* Counting notification (periodic release + missed-release detection). */
void     BSP_NotifyGiveFromIsr(BSP_TaskHandle t);
uint32_t BSP_NotifyTake(bool clear_on_exit, uint32_t timeout_ms);

/* ---------------- Local IRQ mask (per-core, ~0.2 us) ---------------- */
uint32_t BSP_LocalIrqSave(void);
void     BSP_LocalIrqRestore(uint32_t state);

/* ---------------- HW timers ---------------- */
void BSP_TimerSetIsr(uint32_t timer, BSP_IsrFn isr);
void BSP_TimerStartPeriodic(uint32_t timer, uint32_t period_us, uint32_t phase_us);
void BSP_TimerClearIrq(uint32_t timer);

/* ---------------- RS422 / UART + DMA ---------------- */
void     BSP_Rs422Init(uint32_t uart, uint32_t baud);
void     BSP_UartSetIdleIsr(uint32_t uart, BSP_IsrFn isr);
void     BSP_UartEnableIdleIrq(uint32_t uart);
uint32_t BSP_UartStatus(uint32_t uart);
void     BSP_UartClearIdle(uint32_t uart);
void     BSP_UartClearErr(uint32_t uart);

/* Circular RX ring (DMA target). App reads the newest frame backwards. */
void     BSP_DmaRxCircular(uint32_t uart, uint8_t *ring, uint32_t size);
uint8_t *BSP_RingBuffer(uint32_t uart);
uint32_t BSP_RingSize(uint32_t uart);
uint32_t BSP_DmaWriteIndex(uint32_t uart);

/* One-shot TX. Returns false if the channel rejects the frame. */
bool BSP_DmaTxStart(uint32_t uart, const uint8_t *data, uint32_t size);
bool BSP_DmaTxBusy(uint32_t uart);

/* ---------------- Watchdog (kicked only by the supervisor) ---------------- */
void BSP_WdtKick(void);

/* Host aid: number of watchdog kicks observed (for the end-of-run report). */
uint32_t BSP_WdtKickCount(void);

/* ---------------- Host run control ---------------- */
/* Start the hardware simulator + timers, run for `seconds`, then stop. */
void BSP_RunForSeconds(uint32_t seconds);

#endif /* FS_BSP_API_H */

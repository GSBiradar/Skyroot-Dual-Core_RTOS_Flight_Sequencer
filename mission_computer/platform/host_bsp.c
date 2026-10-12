/*
 * host_bsp.c
 *
 * Host implementation of bsp_api.h. It simulates:
 *   - two "cores" (tasks are OS threads, pinned on Linux via CPU affinity),
 *   - four RS422/UART ports at 1 Mbaud with circular RX DMA + idle-line IRQ,
 *   - one-shot TX DMA with polled completion,
 *   - two hardware timers (TMR_A phase 0, TMR_B +phase),
 *   - a watchdog,
 *   - an injectable fault model (CRC corruption, line errors, TX busy/reject)
 *     so the safety paths in the application are actually exercised.
 *
 * On the real target this file is replaced by the platform port. The
 * application never changes.
 */
#if !defined(_WIN32) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE   /* CPU_ZERO / CPU_SET / pthread_setaffinity_np under -std=c11 */
#endif

#include "bsp_api.h"
#include "simulation.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>

#ifdef _WIN32
#include <windows.h>
#endif

/* ======================= seqlock observability counters ======================= */
_Atomic uint32_t g_mbx_reads    = 0u;
_Atomic uint32_t g_mbx_retries  = 0u;
_Atomic uint32_t g_mbx_timeouts = 0u;

/* ======================= monotonic time ======================= */

#if defined(_WIN32)
static double s_qpc_freq = 0.0;
#endif

void BSP_ClockInit(void)
{
#if defined(_WIN32)
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    s_qpc_freq = (double)f.QuadPart;
#else
    /* nothing: clock_gettime(CLOCK_MONOTONIC) is always available */
#endif
}

static uint64_t NowNs(void)
{
#if defined(_WIN32)
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return (uint64_t)(((double)c.QuadPart / s_qpc_freq) * 1e9);
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
#endif
}

uint64_t BSP_HwTimeUs(void) { return NowNs() / 1000ull; }
uint64_t BSP_HwTimeMs(void) { return NowNs() / 1000000ull; }

static void SleepUs(uint64_t us)
{
    uint64_t end = NowNs() + us * 1000ull;
    for (;;)
    {
        uint64_t now = NowNs();
        if (now >= end) { break; }
        uint64_t remain = end - now;
        if (remain > 3000000ull)
        {
#ifdef _WIN32
            Sleep((DWORD)((remain / 1000000ull) - 2ull));
#else
            struct timespec ts;
            uint64_t ms = (remain / 1000000ull) - 2ull;
            ts.tv_sec  = (time_t)(ms / 1000ull);
            ts.tv_nsec = (long)(ms % 1000ull) * 1000000L;
            nanosleep(&ts, NULL);
#endif
        }
        else
        {
            __atomic_thread_fence(__ATOMIC_SEQ_CST);
        }
    }
}

/* ======================= tasks & notifications ======================= */

typedef struct
{
    pthread_t       thread;
    char            name[16];
    uint32_t        priority;
    uint32_t        core;
    void          (*entry)(void *);
    void           *arg;
    pthread_mutex_t lock;
    pthread_cond_t  cond;
    uint32_t        bits;      /* bit-notification mailbox      */
    uint32_t        count;     /* counting-notification mailbox */
} TaskSlot;

static __thread TaskSlot *t_current = NULL;

static void *TaskTrampoline(void *p)
{
    TaskSlot *slot = (TaskSlot *)p;
    t_current = slot;

#ifdef __linux__
    {
        cpu_set_t set;
        CPU_ZERO(&set);
        CPU_SET(slot->core, &set);
        (void)pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    }
#endif

    slot->entry(slot->arg);
    return NULL;
}

bool BSP_TaskCreate(void (*entry)(void *), const char *name,
                    uint32_t stack_words, void *arg,
                    uint32_t priority, uint32_t core,
                    BSP_TaskHandle *out)
{
    TaskSlot *slot = (TaskSlot *)calloc(1u, sizeof(TaskSlot));
    (void)stack_words;

    if (slot == NULL) { return false; }

    slot->entry    = entry;
    slot->arg      = arg;
    slot->priority = priority;
    slot->core     = core;
    strncpy(slot->name, name, sizeof(slot->name) - 1u);

    pthread_mutex_init(&slot->lock, NULL);
    pthread_cond_init(&slot->cond, NULL);

    if (out != NULL) { *out = slot; }

    if (pthread_create(&slot->thread, NULL, TaskTrampoline, slot) != 0)
    {
        return false;
    }
    return true;
}

void BSP_NotifySetBitsFromIsr(BSP_TaskHandle t, uint32_t bits)
{
    TaskSlot *slot = (TaskSlot *)t;
    if (slot == NULL) { return; }
    pthread_mutex_lock(&slot->lock);
    slot->bits |= bits;
    pthread_cond_signal(&slot->cond);
    pthread_mutex_unlock(&slot->lock);
}

static int TimedWait(pthread_cond_t *c, pthread_mutex_t *m, uint32_t timeout_ms)
{
    if (timeout_ms == BSP_WAIT_FOREVER) { return pthread_cond_wait(c, m); }
    struct timespec dl;
    clock_gettime(CLOCK_REALTIME, &dl);
    dl.tv_sec  += (time_t)(timeout_ms / 1000u);
    dl.tv_nsec += (long)(timeout_ms % 1000u) * 1000000L;
    if (dl.tv_nsec >= 1000000000L) { dl.tv_sec += 1; dl.tv_nsec -= 1000000000L; }
    return pthread_cond_timedwait(c, m, &dl);
}

uint32_t BSP_NotifyWaitBits(uint32_t clear_mask, uint32_t timeout_ms)
{
    TaskSlot *slot = t_current;
    uint32_t got = 0u;
    if (slot == NULL) { return 0u; }

    pthread_mutex_lock(&slot->lock);
    while (slot->bits == 0u)
    {
        if (TimedWait(&slot->cond, &slot->lock, timeout_ms) == ETIMEDOUT)
        {
            if (slot->bits == 0u) { break; }
        }
    }
    got = slot->bits;
    slot->bits &= ~clear_mask;
    pthread_mutex_unlock(&slot->lock);
    return got;
}

void BSP_NotifyGiveFromIsr(BSP_TaskHandle t)
{
    TaskSlot *slot = (TaskSlot *)t;
    if (slot == NULL) { return; }
    pthread_mutex_lock(&slot->lock);
    if (slot->count < 0xFFFFFFFFu) { slot->count++; }
    pthread_cond_signal(&slot->cond);
    pthread_mutex_unlock(&slot->lock);
}

uint32_t BSP_NotifyTake(bool clear_on_exit, uint32_t timeout_ms)
{
    TaskSlot *slot = t_current;
    uint32_t got = 0u;
    if (slot == NULL) { return 0u; }

    pthread_mutex_lock(&slot->lock);
    while (slot->count == 0u)
    {
        if (TimedWait(&slot->cond, &slot->lock, timeout_ms) == ETIMEDOUT)
        {
            if (slot->count == 0u) { break; }
        }
    }
    got = slot->count;
    if (clear_on_exit) { slot->count = 0u; }
    else               { slot->count = got - 1u; }
    pthread_mutex_unlock(&slot->lock);
    return got;
}

/* Per-core IRQ mask. On the host atomics already order shared data, so the
 * mask is nominal; it exists so the application code reads exactly as on the
 * target. */
uint32_t BSP_LocalIrqSave(void)               { return 0u; }
void     BSP_LocalIrqRestore(uint32_t state)  { (void)state; }

/* ======================= hardware simulation ======================= */

typedef struct
{
    uint32_t      initialized;
    uint32_t      baud;

    /* RX ring (DMA target) */
    uint8_t      *ring;
    uint32_t      ring_size;
    volatile uint32_t widx;
    BSP_IsrFn     idle_isr;
    int           idle_enabled;
    volatile int  idle_flag;
    volatile int  err_flag;
    uint32_t      rx_seq;

    /* TX one-shot DMA */
    uint8_t       tx_buf[128];
    uint32_t      tx_len;
    volatile int  tx_busy;
    volatile uint64_t tx_done_us;
} UartSim;

typedef struct
{
    int        enabled;
    uint32_t   period_us;
    uint32_t   phase_us;
    uint64_t   next_us;      /* 0 == not yet armed */
    BSP_IsrFn  isr;
} TimerSim;

static UartSim  g_uart[5];
static TimerSim g_timer[2];
static volatile int g_run = 0;
static pthread_t    g_sim_thread;
static _Atomic uint32_t g_wdt_kicks = 0u;

static uint16_t Crc16Ccitt(const uint8_t *d, uint32_t n)
{
    uint16_t crc = 0xFFFFu;
    for (uint32_t i = 0u; i < n; i++)
    {
        crc ^= (uint16_t)((uint16_t)d[i] << 8);
        for (int b = 0; b < 8; b++)
        {
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u)
                                  : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

void BSP_Rs422Init(uint32_t uart, uint32_t baud)
{
    if (uart < 1u || uart > 4u) { return; }
    memset(&g_uart[uart], 0, sizeof(g_uart[uart]));
    g_uart[uart].initialized = 1u;
    g_uart[uart].baud        = baud;
}

void BSP_UartSetIdleIsr(uint32_t uart, BSP_IsrFn isr)
{
    if (uart >= 1u && uart <= 4u) { g_uart[uart].idle_isr = isr; }
}

void BSP_UartEnableIdleIrq(uint32_t uart)
{
    if (uart >= 1u && uart <= 4u) { g_uart[uart].idle_enabled = 1; }
}

uint32_t BSP_UartStatus(uint32_t uart)
{
    uint32_t s = 0u;
    if (uart < 1u || uart > 4u) { return 0u; }
    if (g_uart[uart].idle_flag) { s |= UART_IDLE; }
    if (g_uart[uart].err_flag)  { s |= UART_ORE;  }
    return s;
}

void BSP_UartClearIdle(uint32_t uart)
{
    if (uart >= 1u && uart <= 4u) { g_uart[uart].idle_flag = 0; }
}

void BSP_UartClearErr(uint32_t uart)
{
    if (uart >= 1u && uart <= 4u) { g_uart[uart].err_flag = 0; }
}

void BSP_DmaRxCircular(uint32_t uart, uint8_t *ring, uint32_t size)
{
    if (uart < 1u || uart > 4u) { return; }
    g_uart[uart].ring      = ring;
    g_uart[uart].ring_size = size;
    g_uart[uart].widx      = 0u;
}

uint8_t *BSP_RingBuffer(uint32_t uart)
{
    return (uart >= 1u && uart <= 4u) ? g_uart[uart].ring : NULL;
}

uint32_t BSP_RingSize(uint32_t uart)
{
    return (uart >= 1u && uart <= 4u) ? g_uart[uart].ring_size : 0u;
}

uint32_t BSP_DmaWriteIndex(uint32_t uart)
{
    return (uart >= 1u && uart <= 4u) ? g_uart[uart].widx : 0u;
}

bool BSP_DmaTxStart(uint32_t uart, const uint8_t *data, uint32_t size)
{
    UartSim *u;
    uint64_t wire_us;

    if (uart < 1u || uart > 4u || size > sizeof(u->tx_buf)) { return false; }
    u = &g_uart[uart];

    if (u->tx_busy) { return false; }

    /* Model an occasional actuator link rejection. */
    if (uart == UART_ACT && (rand() % 100) < (int)ACT_TX_FAIL_PCT)
    {
        return false;
    }

    memcpy(u->tx_buf, data, size);
    u->tx_len = size;

    wire_us = (uint64_t)size * 10ull;             /* 10 us/byte at 1 Mbaud */
    if (wire_us < 1ull) { wire_us = 1ull; }
    u->tx_done_us = BSP_HwTimeUs() + wire_us;

    /* Inject extra busy time so the polled-completion path is exercised. */
    if (uart == UART_ACT && (rand() % 100) < (int)ACT_BUSY_INJECT_PCT)
    {
        u->tx_done_us = BSP_HwTimeUs() + 15000ull;
    }
    if (uart == UART_TLM && (rand() % 100) < (int)TLM_TX_BUSY_PCT)
    {
        u->tx_done_us = BSP_HwTimeUs() + 15000ull;
    }

    u->tx_busy = 1;
    return true;
}

bool BSP_DmaTxBusy(uint32_t uart)
{
    if (uart < 1u || uart > 4u) { return false; }
    return g_uart[uart].tx_busy != 0;
}

void BSP_WdtKick(void)
{
    atomic_fetch_add_explicit(&g_wdt_kicks, 1u, memory_order_relaxed);
}

/* ---------------- timers ---------------- */

void BSP_TimerSetIsr(uint32_t timer, BSP_IsrFn isr)
{
    if (timer < 2u) { g_timer[timer].isr = isr; }
}

void BSP_TimerStartPeriodic(uint32_t timer, uint32_t period_us, uint32_t phase_us)
{
    if (timer >= 2u) { return; }
    g_timer[timer].enabled   = 1;
    g_timer[timer].period_us = period_us;
    g_timer[timer].phase_us  = phase_us;
    g_timer[timer].next_us   = 0u;   /* armed by the sim loop */
}

void BSP_TimerClearIrq(uint32_t timer) { (void)timer; }

/* ---------------- frame production ---------------- */

static void ProduceFrame(uint32_t uart)
{
    UartSim *u = &g_uart[uart];
    uint32_t payload_len = (uart == UART_S1) ? N1_LEN : N2_LEN;
    uint32_t frame_len   = payload_len + FRAME_OVERHEAD;
    uint8_t  tmp[64];
    uint16_t crc;
    uint32_t i;
    uint32_t pct = (uart == UART_S1) ? SENSOR1_CORRUPT_PCT : SENSOR2_CORRUPT_PCT;

    if (u->ring == NULL || frame_len > sizeof(tmp)) { return; }

    tmp[0] = SYNC0;
    tmp[1] = SYNC1;
    tmp[2] = (uint8_t)u->rx_seq;
    tmp[3] = (uint8_t)payload_len;
    for (i = 0u; i < payload_len; i++)
    {
        tmp[4u + i] = (uint8_t)(u->rx_seq + i);
    }

    crc = Crc16Ccitt(tmp, frame_len - 2u);
    tmp[frame_len - 2u] = (uint8_t)(crc & 0xFFu);
    tmp[frame_len - 1u] = (uint8_t)(crc >> 8);

    /* Corrupt a payload byte *after* the CRC is sealed, so the receiver's
     * CRC check actually fails (exercises the discard path). */
    if ((rand() % 100) < (int)pct)
    {
        tmp[4u + (uint32_t)(rand() % (int)payload_len)] ^= 0xFFu;
    }

    /* Copy into the circular ring. */
    for (i = 0u; i < frame_len; i++)
    {
        u->ring[(u->widx + i) % u->ring_size] = tmp[i];
    }
    u->widx = (u->widx + frame_len) % u->ring_size;
    u->rx_seq++;

    u->idle_flag = 1;
    if ((rand() % 100) < (int)LINE_ERR_PCT) { u->err_flag = 1; }

    if (u->idle_enabled && u->idle_isr != NULL)
    {
        u->idle_isr();                 /* models the idle-line interrupt */
    }
}

static void *HwSimThread(void *unused)
{
    (void)unused;

    uint64_t s1_next = BSP_HwTimeUs() + SENSOR1_PERIOD_US;
    uint64_t s2_next = BSP_HwTimeUs() + SENSOR2_PERIOD_US;

    for (uint32_t t = 0u; t < 2u; t++)
    {
        if (g_timer[t].enabled)
        {
            g_timer[t].next_us = BSP_HwTimeUs() + g_timer[t].phase_us;
        }
    }

    while (g_run)
    {
        uint64_t now = BSP_HwTimeUs();

        /* hardware timers */
        for (uint32_t t = 0u; t < 2u; t++)
        {
            if (g_timer[t].enabled && g_timer[t].next_us != 0u &&
                now >= g_timer[t].next_us)
            {
                if (g_timer[t].isr != NULL) { g_timer[t].isr(); }
                g_timer[t].next_us += g_timer[t].period_us;
            }
        }

        /* sensor frame arrivals */
        if (now >= s1_next) { ProduceFrame(UART_S1); s1_next += SENSOR1_PERIOD_US; }
        if (now >= s2_next) { ProduceFrame(UART_S2); s2_next += SENSOR2_PERIOD_US; }

        /* transmit completions */
        for (uint32_t u = UART_ACT; u <= UART_TLM; u++)
        {
            if (g_uart[u].tx_busy && now >= g_uart[u].tx_done_us)
            {
                g_uart[u].tx_busy = 0;
            }
        }

        SleepUs(200u);
    }

    return NULL;
}

void BSP_RunForSeconds(uint32_t seconds)
{
    uint64_t end = BSP_HwTimeUs() + (uint64_t)seconds * 1000000ull;

    g_run = 1;
    pthread_create(&g_sim_thread, NULL, HwSimThread, NULL);

    while (BSP_HwTimeUs() < end) { SleepUs(5000u); }

    g_run = 0;
    pthread_join(g_sim_thread, NULL);
    SleepUs(5000u);   /* let the last in-flight work settle */
}

/* Exposed to the report so the watchdog behaviour is visible. */
uint32_t BSP_WdtKickCount(void)
{
    return atomic_load_explicit(&g_wdt_kicks, memory_order_relaxed);
}

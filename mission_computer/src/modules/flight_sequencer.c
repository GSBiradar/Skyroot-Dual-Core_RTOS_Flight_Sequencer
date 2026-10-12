/*
 * flight_sequencer.c
 *
 * Dual-core Flight Sequencer. This is the complete application logic,
 * transcribed from the assessment pseudocode (sections 3.1-3.6) and written
 * ONLY against bsp_api.h.
 *
 * Mapping to the assessment:
 *   I1/I2  UART_S1/S2_IRQHandler   DMA + idle-line, notify ingest (bit notify)
 *   I3/I4  TMR_A/TMR_B_IRQHandler  counting notify -> FlightSeq / Supervisor+Slow
 *   T1     SensorIngestTask        Core 0, validate + publish nav mailboxes
 *   T2     FlightSeqTask           Core 1, the hard-real-time sequencer
 *   T3     SupervisorTask          Core 0, health telemetry + watchdog gate
 *   T4     SlowCompTask            Core 0, 200 ms feedback (fixed boundary)
 */
#include "flight_sequencer.h"
#include "mailbox.h"
#include "bsp_api.h"

#include <stdio.h>
#include <string.h>

/* ======================= shared state ======================= */

static Mbx_t      g_nav1;        /* T1 -> T2/T4  (32 B nav)               */
static Mbx_t      g_nav2;        /* T1 -> T2/T4  (54 B nav)               */
static Mbx_t      g_seqOut;      /* T2 -> T4     (16 B sequencer output)  */
static Mbx_t      g_fb;          /* T4 -> T2     (16 B feedback + control)*/
static _Atomic uint32_t g_frameId;

static Health_t   g_health;      /* one writer per field, no lock         */

static BSP_TaskHandle hIngest, hSeq, hSup, hSlow;

/* DMA rings (owned by the driver, read by ingest) */
static uint8_t g_s1Ring[512];
static uint8_t g_s2Ring[512];

/* TX scratch owned by the sender */
static uint8_t g_actTx[ACT_LEN + FRAME_OVERHEAD];
static uint8_t g_tlmTx[64];

/* Per-sensor reception context (Core 0 only) */
typedef struct {
    uint8_t  last_seq;
    uint32_t end_idx;
    uint64_t isr_ts;
} RxCtx_t;

static RxCtx_t g_s1;
static RxCtx_t g_s2;

/* ======================= helpers ======================= */

static uint16_t Crc16(const uint8_t *d, uint32_t n)
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

/* Pull the newest complete frame out of the circular DMA ring. */
static bool RingExtractFrame(uint32_t uart, uint32_t payload_len, Frame_t *f)
{
    uint8_t *ring = BSP_RingBuffer(uart);
    uint32_t size = BSP_RingSize(uart);
    uint32_t frame_len = payload_len + FRAME_OVERHEAD;

    if (ring == NULL || size < frame_len) { return false; }

    uint32_t widx  = BSP_DmaWriteIndex(uart);
    uint32_t start = (widx + size - frame_len) % size;

    for (uint32_t i = 0u; i < frame_len; i++)
    {
        f->raw[i] = ring[(start + i) % size];
    }

    if (f->raw[0] != SYNC0 || f->raw[1] != SYNC1) { return false; }
    if (f->raw[3] != (uint8_t)payload_len)        { return false; }

    f->n   = frame_len;
    f->seq = f->raw[2];
    memcpy(f->payload, &f->raw[4], payload_len);
    return true;
}

/* Build an outbound frame: sync, seq, len, payload, CRC16. Returns length. */
static uint32_t FrameBuild(uint8_t *out, uint8_t seq, const uint8_t *payload, uint32_t len)
{
    out[0] = SYNC0;
    out[1] = SYNC1;
    out[2] = seq;
    out[3] = (uint8_t)len;
    memcpy(&out[4], payload, len);
    uint16_t crc = Crc16(out, len + 4u);
    out[4u + len] = (uint8_t)(crc & 0xFFu);
    out[5u + len] = (uint8_t)(crc >> 8);
    return len + FRAME_OVERHEAD;
}

/* ======================= 3.3 peripheral reception ======================= */

static void UART_S1_IRQHandler(void)      /* Core 0 */
{
    uint32_t st = BSP_UartStatus(UART_S1);
    if (st & UART_IDLE)
    {
        BSP_UartClearIdle(UART_S1);
        g_s1.end_idx = BSP_DmaWriteIndex(UART_S1);
        g_s1.isr_ts  = BSP_HwTimeUs();
        BSP_NotifySetBitsFromIsr(hIngest, EVT_S1);
    }
    if (st & (UART_ORE | UART_FE | UART_NE))
    {
        BSP_UartClearErr(UART_S1);
        atomic_fetch_add(&g_health.s1_sync_err, 1u);
    }
}

static void UART_S2_IRQHandler(void)      /* Core 0 */
{
    uint32_t st = BSP_UartStatus(UART_S2);
    if (st & UART_IDLE)
    {
        BSP_UartClearIdle(UART_S2);
        g_s2.end_idx = BSP_DmaWriteIndex(UART_S2);
        g_s2.isr_ts  = BSP_HwTimeUs();
        BSP_NotifySetBitsFromIsr(hIngest, EVT_S2);
    }
    if (st & (UART_ORE | UART_FE | UART_NE))
    {
        BSP_UartClearErr(UART_S2);
        atomic_fetch_add(&g_health.s2_sync_err, 1u);
    }
}

/* ======================= T1: sensor ingest ======================= */

static void IngestOne(RxCtx_t *c, Mbx_t *mbx, uint32_t uart, uint32_t payload_len,
                      _Atomic uint32_t *last_ts, _Atomic uint32_t *frames,
                      _Atomic uint32_t *crc_err, _Atomic uint32_t *seq_gap,
                      _Atomic uint32_t *sync_err)
{
    Frame_t f;

    if (!RingExtractFrame(uart, payload_len, &f))
    {
        atomic_fetch_add(sync_err, 1u);
        return;
    }

    uint16_t stored = (uint16_t)(f.raw[f.n - 2u] | ((uint16_t)f.raw[f.n - 1u] << 8));
    if (Crc16(f.raw, f.n - 2u) != stored)
    {
        atomic_fetch_add(crc_err, 1u);
        return;
    }

    uint8_t gap = (uint8_t)(f.seq - c->last_seq - 1u);
    if (gap != 0u) { atomic_fetch_add(seq_gap, gap); }
    c->last_seq = f.seq;

    Mbx_Publish(mbx, f.payload, payload_len, c->isr_ts, 0u);
    atomic_store(last_ts, (uint32_t)c->isr_ts);
    atomic_fetch_add(frames, 1u);
}

static void SensorIngestTask(void *arg)   /* Core 0, prio 5 */
{
    (void)arg;
    for (;;)
    {
        uint32_t ev = BSP_NotifyWaitBits(0xFFFFFFFFu, BSP_WAIT_FOREVER);

        if (ev & EVT_S1)
        {
            IngestOne(&g_s1, &g_nav1, UART_S1, N1_LEN,
                      &g_health.s1_last_ts, &g_health.s1_frames,
                      &g_health.s1_crc_err, &g_health.s1_seq_gap,
                      &g_health.s1_sync_err);
        }
        if (ev & EVT_S2)
        {
            IngestOne(&g_s2, &g_nav2, UART_S2, N2_LEN,
                      &g_health.s2_last_ts, &g_health.s2_frames,
                      &g_health.s2_crc_err, &g_health.s2_seq_gap,
                      &g_health.s2_sync_err);
        }
    }
}

/* ======================= placeholder flight math (A8) ======================= */

static void FSeq_Init(FSeqState_t *st) { memset(st, 0, sizeof(*st)); }

static void ComputeFlightActuation(FSeqState_t *st,
                                   const Nav1_t *n1, const Nav2_t *n2,
                                   bool v1, bool v2,
                                   const FbPayload_t *fb,
                                   ActCmd_t *cmd, SeqOut16_t *out16)
{
    uint8_t acc = 0u;

    memset(cmd, 0, sizeof(*cmd));
    memset(out16, 0, sizeof(*out16));

    if (!v1 && !v2)                 /* no valid nav -> deterministic safe output */
    {
        cmd->bytes[0]    = 0xA5u;
        out16->bytes[0]  = 0xA5u;
        st->last_digest  = 0xA5u;
        return;
    }

    for (uint32_t i = 0u; i < N1_LEN; i++)
    {
        acc = (uint8_t)(acc ^ n1->payload[i]);
        cmd->bytes[i % ACT_LEN] = (uint8_t)(cmd->bytes[i % ACT_LEN] + n1->payload[i]);
    }
    for (uint32_t i = 0u; i < N2_LEN; i++)
    {
        acc = (uint8_t)(acc ^ n2->payload[i]);
        cmd->bytes[i % ACT_LEN] = (uint8_t)(cmd->bytes[i % ACT_LEN] + n2->payload[i]);
    }

    st->cycles++;
    st->last_digest = acc;

    out16->bytes[0] = acc;
    out16->bytes[1] = fb->bytes[0];
    for (uint32_t i = 2u; i < SEQOUT_LEN; i++)
    {
        out16->bytes[i] = (uint8_t)(cmd->bytes[i] ^ fb->bytes[i % FB_LEN]);
    }
}

/* ======================= 3.4 timer ISRs + T2 ======================= */

static void TMR_A_IRQHandler(void)        /* Core 1, phase 0 */
{
    BSP_TimerClearIrq(TMR_A);
    static uint32_t cnt = 0u;
    atomic_store(&g_frameId, cnt++);
    BSP_NotifyGiveFromIsr(hSeq);           /* counting: exposes missed releases */
}

static void TMR_B_IRQHandler(void)        /* Core 0, phase +6 ms */
{
    BSP_TimerClearIrq(TMR_B);
    BSP_NotifyGiveFromIsr(hSup);
    if ((atomic_load(&g_frameId) % SLOW_DIV) == 0u)
    {
        BSP_NotifyGiveFromIsr(hSlow);
    }
}

static void FlightSeqTask(void *arg)      /* Core 1, prio 5 */
{
    (void)arg;

    Nav1_t n1; Nav2_t n2; FbPayload_t fb; FbMsg_t fbTmp;
    ActCmd_t cmd; SeqOut16_t out16; FSeqState_t st;
    uint32_t actSeq = 0u, fbCycle = 0u;

    memset(&n1, 0, sizeof(n1));
    memset(&n2, 0, sizeof(n2));
    memset(&fb, 0, sizeof(fb));
    FSeq_Init(&st);

    for (;;)
    {
        uint32_t rel = BSP_NotifyTake(true, BSP_WAIT_FOREVER);
        if (rel > 1u)
        {
            atomic_fetch_add(&g_health.seq_missed_rel, rel - 1u);
        }

        uint64_t t0 = BSP_HwTimeUs();
        uint32_t frame = atomic_load(&g_frameId);

        /* 1. Wait-free snapshot of latest nav; keep last good on failure. */
        Nav1_t t1; Nav2_t t2;
        uint64_t ts1 = 0u, ts2 = 0u;
        uint32_t d = 0u;

        if (Mbx_Read(&g_nav1, &t1, N1_LEN, &ts1, &d)) { n1 = t1; }
        if (Mbx_Read(&g_nav2, &t2, N2_LEN, &ts2, &d)) { n2 = t2; }

        bool v1 = ((t0 - ts1) <= NAV1_MAX_AGE_US);
        bool v2 = ((t0 - ts2) <= NAV2_MAX_AGE_US);

        /* 2. Feedback: latch only on a fixed 20-frame boundary. */
        if ((frame % SLOW_DIV) == 0u)
        {
            uint64_t tsf = 0u;
            if (Mbx_Read(&g_fb, &fbTmp, sizeof(fbTmp), &tsf, &d) &&
                fbTmp.cycle_id != fbCycle &&
                fbTmp.activate_frame <= frame)
            {
                fb      = fbTmp.payload;
                fbCycle = fbTmp.cycle_id;
            }
            else
            {
                atomic_fetch_add(&g_health.fb_stale_cnt, 1u);   /* hold previous */
            }
        }

        /* 3. Flight computation. */
        ComputeFlightActuation(&st, &n1, &n2, v1, v2, &fb, &cmd, &out16);

        /* 4. Publish the 16 B output for the slow task (wait-free). */
        Mbx_Publish(&g_seqOut, &out16, SEQOUT_LEN, t0, frame);

        /* 5. Transmit the 20 B actuator command (DMA, non-blocking). */
        if (!BSP_DmaTxBusy(UART_ACT))
        {
            uint32_t n = FrameBuild(g_actTx, (uint8_t)actSeq++, cmd.bytes, ACT_LEN);
            if (BSP_DmaTxStart(UART_ACT, g_actTx, n))
            {
                atomic_fetch_add(&g_health.act_tx, 1u);
            }
            else
            {
                atomic_fetch_add(&g_health.act_tx_err, 1u);
            }
        }
        else
        {
            atomic_fetch_add(&g_health.act_busy_cnt, 1u);
        }

        /* 6. Health. */
        uint32_t dt = (uint32_t)(BSP_HwTimeUs() - t0);
        atomic_store(&g_health.seq_exec_us, dt);
        if (dt > atomic_load(&g_health.seq_exec_max_us))
        {
            atomic_store(&g_health.seq_exec_max_us, dt);
        }
        atomic_fetch_add(&g_health.seq_hb, 1u);
    }
}

/* ======================= 3.5 T4: slow computation ======================= */

static void CalculateSlowDynamics(const Nav1_t *n1, const Nav2_t *n2,
                                  const SeqOut16_t *so, FbPayload_t *fb)
{
    for (uint32_t i = 0u; i < FB_LEN; i++)
    {
        fb->bytes[i] = (uint8_t)(n1->payload[i % N1_LEN] ^
                                 n2->payload[i % N2_LEN] ^
                                 so->bytes[i % SEQOUT_LEN]);
    }
}

static void SlowCompTask(void *arg)       /* Core 0, prio 2 */
{
    (void)arg;

    Nav1_t n1; Nav2_t n2; SeqOut16_t so; FbMsg_t fb;
    uint32_t cycle = 0u;

    memset(&n1, 0, sizeof(n1));
    memset(&n2, 0, sizeof(n2));
    memset(&so, 0, sizeof(so));

    for (;;)
    {
        BSP_NotifyTake(true, BSP_WAIT_FOREVER);   /* every 20th frame */

        uint64_t t0 = BSP_HwTimeUs();
        uint64_t ts = 0u;
        uint32_t fidNav = 0u, fidSeq = 0u;

        (void)Mbx_Read(&g_nav1,   &n1, N1_LEN,    &ts, &fidNav);
        (void)Mbx_Read(&g_nav2,   &n2, N2_LEN,    &ts, &fidNav);
        (void)Mbx_Read(&g_seqOut, &so, SEQOUT_LEN,&ts, &fidSeq);

        CalculateSlowDynamics(&n1, &n2, &so, &fb.payload);
        fb.cycle_id       = ++cycle;
        fb.activate_frame = ((fidSeq / SLOW_DIV) + 1u) * SLOW_DIV;  /* next boundary */

        Mbx_Publish(&g_fb, &fb, sizeof(fb), BSP_HwTimeUs(), fidSeq);

        atomic_store(&g_health.slow_exec_us, (uint32_t)(BSP_HwTimeUs() - t0));
        atomic_fetch_add(&g_health.slow_hb, 1u);
    }
}

/* ======================= 3.6 T3: supervisor ======================= */

static uint32_t TlmBuild(uint8_t *out, uint8_t seq, uint32_t frame, uint32_t flags)
{
    memset(out, 0, 64u);
    out[0] = SYNC0;
    out[1] = SYNC1;
    out[2] = seq;
    out[3] = (uint8_t)frame;
    out[4] = (uint8_t)(flags & 0xFFu);
    out[5] = (uint8_t)((flags >> 8) & 0xFFu);
    out[6] = (uint8_t)((flags >> 16) & 0xFFu);
    out[7] = (uint8_t)((flags >> 24) & 0xFFu);

    uint32_t off = 8u;
    uint32_t fields[8] = {
        atomic_load(&g_health.s1_frames), atomic_load(&g_health.s1_crc_err),
        atomic_load(&g_health.s2_frames), atomic_load(&g_health.s2_crc_err),
        atomic_load(&g_health.seq_hb),    atomic_load(&g_health.seq_exec_max_us),
        atomic_load(&g_health.slow_hb),   atomic_load(&g_health.fb_stale_cnt)
    };
    for (uint32_t f = 0u; f < 8u; f++)
    {
        out[off + 0u] = (uint8_t)(fields[f] & 0xFFu);
        out[off + 1u] = (uint8_t)((fields[f] >> 8) & 0xFFu);
        out[off + 2u] = (uint8_t)((fields[f] >> 16) & 0xFFu);
        out[off + 3u] = (uint8_t)((fields[f] >> 24) & 0xFFu);
        off += 4u;
    }
    return 64u;
}

static void SupervisorTask(void *arg)     /* Core 0, prio 4 */
{
    (void)arg;

    uint32_t lastSeqHb = 0u, lastSlowHb = 0u, slowSilent = 0u, tlmSeq = 0u;
    uint32_t lastS1Crc = 0u, lastS2Crc = 0u, lastActBusy = 0u;
    uint32_t lastFbStale = 0u, lastMissed = 0u;

    for (;;)
    {
        BSP_NotifyTake(true, BSP_WAIT_FOREVER);   /* frame start + 6 ms */

        uint32_t now   = (uint32_t)BSP_HwTimeUs();
        uint32_t frame = atomic_load(&g_frameId);
        uint32_t flags = 0u;

        /* Sensor interfaces: link alive if the latest frame is recent. */
        if ((now - atomic_load(&g_health.s1_last_ts)) > NAV1_MAX_AGE_US) { flags |= F_S1_TIMEOUT; }
        if ((now - atomic_load(&g_health.s2_last_ts)) > NAV2_MAX_AGE_US) { flags |= F_S2_TIMEOUT; }

        /* Edge-triggered fault detection: flag only *new* faults since the last
         * cycle, so one transient event does not latch the fault forever and
         * the watchdog keeps being kicked while the system is healthy. */
        uint32_t s1c = atomic_load(&g_health.s1_crc_err);
        uint32_t s2c = atomic_load(&g_health.s2_crc_err);
        if (s1c > lastS1Crc || s2c > lastS2Crc) { flags |= F_NAV_CRC; }
        lastS1Crc = s1c;
        lastS2Crc = s2c;

        /* Flight sequencer: heartbeat must advance every frame. */
        uint32_t hb = atomic_load(&g_health.seq_hb);
        if (hb == lastSeqHb) { flags |= F_SEQ_STALLED; }
        lastSeqHb = hb;

        if (atomic_load(&g_health.seq_exec_us) > SEQ_BUDGET_US) { flags |= F_SEQ_OVERRUN; }

        uint32_t mr = atomic_load(&g_health.seq_missed_rel);
        if (mr > lastMissed) { flags |= F_SEQ_MISSED; }
        lastMissed = mr;

        /* Actuator interface (edge-triggered). */
        uint32_t ab = atomic_load(&g_health.act_busy_cnt);
        if (ab > lastActBusy) { flags |= F_ACT_TX; }
        lastActBusy = ab;

        /* Slow task: heartbeat must advance within one 200 ms window. */
        if ((frame % SLOW_DIV) == 0u)
        {
            uint32_t sh = atomic_load(&g_health.slow_hb);
            slowSilent = (sh == lastSlowHb) ? (slowSilent + 1u) : 0u;
            lastSlowHb = sh;
        }
        if (slowSilent >= 2u) { flags |= F_SLOW_STALLED; }

        uint32_t fs = atomic_load(&g_health.fb_stale_cnt);
        if (fs > lastFbStale) { flags |= F_FB_STALE; }
        lastFbStale = fs;

        /* Build + send telemetry (DMA, non-blocking). */
        uint32_t n = TlmBuild(g_tlmTx, (uint8_t)tlmSeq++, frame, flags);
        if (!BSP_DmaTxBusy(UART_TLM))
        {
            (void)BSP_DmaTxStart(UART_TLM, g_tlmTx, n);
            atomic_fetch_add(&g_health.tlm_frames, 1u);
        }
        else
        {
            flags |= F_TLM_TX;
            atomic_fetch_add(&g_health.tlm_busy, 1u);
        }

        atomic_store(&g_health.sup_flags_last, flags);

        /* Watchdog: kicked only when every monitored element is healthy. */
        if ((flags & F_CRITICAL_MASK) == 0u)
        {
            BSP_WdtKick();
            atomic_fetch_add(&g_health.wdt_kicks, 1u);
        }
        else
        {
            atomic_fetch_add(&g_health.wdt_skips, 1u);
        }

        atomic_fetch_add(&g_health.sup_hb, 1u);
    }
}

/* ======================= 3.2 initialization ======================= */

void FlightSequencer_Init(void)
{
    BSP_ClockInit();
    memset(&g_health, 0, sizeof(g_health));
    memset(&g_s1, 0, sizeof(g_s1));
    memset(&g_s2, 0, sizeof(g_s2));
    /* The simulator starts its frame counter at 0; pre-load last_seq so the
     * first received frame is not mis-counted as a 255-frame gap. */
    g_s1.last_seq = 0xFFu;
    g_s2.last_seq = 0xFFu;
    memset(&g_nav1, 0, sizeof(g_nav1));
    memset(&g_nav2, 0, sizeof(g_nav2));
    memset(&g_seqOut, 0, sizeof(g_seqOut));
    memset(&g_fb, 0, sizeof(g_fb));

    /* RS422 ports at 1 Mbaud, circular RX DMA on the sensors. */
    BSP_Rs422Init(UART_S1, BAUD_RATE);
    BSP_DmaRxCircular(UART_S1, g_s1Ring, (uint32_t)sizeof(g_s1Ring));
    BSP_Rs422Init(UART_S2, BAUD_RATE);
    BSP_DmaRxCircular(UART_S2, g_s2Ring, (uint32_t)sizeof(g_s2Ring));
    BSP_Rs422Init(UART_ACT, BAUD_RATE);
    BSP_Rs422Init(UART_TLM, BAUD_RATE);

    /* Statically allocated tasks pinned to cores. */
    (void)BSP_TaskCreate(SensorIngestTask, "Ingest", 1024u, NULL, 5u, CORE0, &hIngest);
    (void)BSP_TaskCreate(SupervisorTask,   "Super",  1024u, NULL, 4u, CORE0, &hSup);
    (void)BSP_TaskCreate(SlowCompTask,     "Slow",   1024u, NULL, 2u, CORE0, &hSlow);
    (void)BSP_TaskCreate(FlightSeqTask,    "Flight", 2048u, NULL, 5u, CORE1, &hSeq);

    /* Route ISRs. */
    BSP_UartSetIdleIsr(UART_S1, UART_S1_IRQHandler);
    BSP_UartSetIdleIsr(UART_S2, UART_S2_IRQHandler);
    BSP_TimerSetIsr(TMR_A, TMR_A_IRQHandler);
    BSP_TimerSetIsr(TMR_B, TMR_B_IRQHandler);

    /* Enable idle-line IRQs and start the hardware timers. */
    BSP_UartEnableIdleIrq(UART_S1);
    BSP_UartEnableIdleIrq(UART_S2);
    BSP_TimerStartPeriodic(TMR_A, FRAME_US, 0u);
    BSP_TimerStartPeriodic(TMR_B, FRAME_US, SUPERVISOR_PHASE_MS * 1000u);
}

/* ======================= end-of-run report ======================= */

void FlightSequencer_PrintReport(void)
{
    printf("\n");
    printf("============== Flight Sequencer health report (dual-core) ==============\n");
    printf(" sensor1  frames / crc / seq_gap / sync_err : %u / %u / %u / %u\n",
           atomic_load(&g_health.s1_frames), atomic_load(&g_health.s1_crc_err),
           atomic_load(&g_health.s1_seq_gap), atomic_load(&g_health.s1_sync_err));
    printf(" sensor2  frames / crc / seq_gap / sync_err : %u / %u / %u / %u\n",
           atomic_load(&g_health.s2_frames), atomic_load(&g_health.s2_crc_err),
           atomic_load(&g_health.s2_seq_gap), atomic_load(&g_health.s2_sync_err));
    printf(" flight   heartbeats / missed_rel / max_us  : %u / %u / %u\n",
           atomic_load(&g_health.seq_hb), atomic_load(&g_health.seq_missed_rel),
           atomic_load(&g_health.seq_exec_max_us));
    printf(" actuator tx / tx_err / busy_cnt           : %u / %u / %u\n",
           atomic_load(&g_health.act_tx), atomic_load(&g_health.act_tx_err),
           atomic_load(&g_health.act_busy_cnt));
    printf(" slow     heartbeats / exec_us / fb_stale   : %u / %u / %u\n",
           atomic_load(&g_health.slow_hb), atomic_load(&g_health.slow_exec_us),
           atomic_load(&g_health.fb_stale_cnt));
    printf(" supervisor heartbeats / tlm / tlm_busy    : %u / %u / %u\n",
           atomic_load(&g_health.sup_hb), atomic_load(&g_health.tlm_frames),
           atomic_load(&g_health.tlm_busy));
    printf(" watchdog kicks / skips                     : %u / %u\n",
           atomic_load(&g_health.wdt_kicks), atomic_load(&g_health.wdt_skips));
    printf(" ---------------- seqlock + timing invariants ----------------\n");
    printf(" seqlock reads / retries / timeouts         : %u / %u / %u\n",
           atomic_load(&g_mbx_reads), atomic_load(&g_mbx_retries),
           atomic_load(&g_mbx_timeouts));
    printf(" last supervisor flag word                  : 0x%08X\n",
           atomic_load(&g_health.sup_flags_last));
    printf(" wdt kicks observed by BSP                  : %u\n", BSP_WdtKickCount());
    printf("========================================================================\n");
}

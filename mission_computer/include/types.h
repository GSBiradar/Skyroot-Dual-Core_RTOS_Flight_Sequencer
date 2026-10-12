/*
 * types.h
 *
 * Shared data types, sizes and timing constants for the dual-core Flight
 * Sequencer, transcribed from the assessment pseudocode (see docs/).
 *
 * Frame format on the wire (all four RS422 ports):
 *
 *   +--------+--------+-----+-------+------------------+----------+
 *   | sync0  | sync1  | seq | len   | payload          | crc16    |
 *   | 0xAA   | 0x55   | 1 B | 1 B   | len bytes        | 2 B (LE) |
 *   +--------+--------+-----+-------+------------------+----------+
 *
 * 6-byte overhead. CRC-16/CCITT-FALSE is computed over every byte except the
 * two CRC bytes. This header intentionally mirrors the assessment's frame
 * model (A5) so the wire costs match the timing analysis.
 */
#ifndef FS_TYPES_H
#define FS_TYPES_H

#include <stdint.h>
#include <stdbool.h>
#include <stdatomic.h>

/* ---------------- Core masks ---------------- */
#define CORE0   (1u << 0)
#define CORE1   (1u << 1)

/* ---------------- Rates / periods ---------------- */
#define FRAME_US            10000u   /* 10 ms nominal flight frame */
#define SLOW_DIV            20u      /* slow task every 20th frame (200 ms) */

#define SENSOR1_PERIOD_US    5000u   /* 5 ms  */
#define SENSOR2_PERIOD_US   10000u   /* 10 ms */
#define SUPERVISOR_PHASE_MS  6u      /* supervisor frame at +6 ms */

/* ---------------- Payload lengths (bytes) ---------------- */
#define N1_LEN   32u
#define N2_LEN   54u
#define ACT_LEN  20u
#define FB_LEN   16u
#define SEQOUT_LEN 16u

/* ---------------- Frame overhead / sync ---------------- */
#define FRAME_OVERHEAD   6u      /* 2 sync + 1 seq + 1 len + 2 crc */
#define SYNC0            0xAAu
#define SYNC1            0x55u
#define SYNC_ACT         0xA5u
#define BAUD_RATE        1000000u

/* ---------------- Staleness (freshness) limits ---------------- */
#define NAV1_MAX_AGE_US   7500u    /* 1.5 x sensor-1 period */
#define NAV2_MAX_AGE_US  15000u    /* 1.5 x sensor-2 period */

#define MBX_MAX_RETRY     3u

/* ---------------- Event bits for ingest notifications ---------------- */
#define EVT_S1   (1u << 0)
#define EVT_S2   (1u << 1)

/* ---------------- Health flag bits (supervisor) ---------------- */
#define F_S1_TIMEOUT    (1u << 0)
#define F_S2_TIMEOUT    (1u << 1)
#define F_NAV_CRC       (1u << 2)
#define F_SEQ_STALLED   (1u << 3)
#define F_SEQ_OVERRUN   (1u << 4)
#define F_SEQ_MISSED    (1u << 5)
#define F_ACT_TX        (1u << 6)
#define F_SLOW_STALLED  (1u << 7)
#define F_FB_STALE      (1u << 8)
#define F_TLM_TX        (1u << 9)

/* Flags that gate the watchdog kick (any set => do NOT kick). */
#define F_CRITICAL_MASK (F_S1_TIMEOUT | F_S2_TIMEOUT | F_NAV_CRC | \
                         F_SEQ_STALLED | F_SEQ_OVERRUN | F_SEQ_MISSED | \
                         F_SLOW_STALLED)

#define SEQ_BUDGET_US   3000u   /* FlightSeq WCET budget (A7) */

/* ---------------- Application payload types ---------------- */
typedef struct { uint8_t payload[N1_LEN]; } Nav1_t;
typedef struct { uint8_t payload[N2_LEN]; } Nav2_t;
typedef struct { uint8_t bytes[SEQOUT_LEN]; } SeqOut16_t;
typedef struct { uint8_t bytes[FB_LEN]; } FbPayload_t;
typedef struct { uint8_t bytes[ACT_LEN]; } ActCmd_t;

/* Slow-task message: payload + deterministic activation boundary. */
typedef struct {
    FbPayload_t payload;
    uint32_t    cycle_id;
    uint32_t    activate_frame;
} FbMsg_t;

/* A parsed frame handed from the DMA ring to the validator. */
typedef struct {
    uint8_t  raw[N2_LEN + FRAME_OVERHEAD];
    uint32_t n;                 /* total frame length including CRC */
    uint8_t  seq;
    uint8_t  payload[N2_LEN];
} Frame_t;

/* Placeholder flight-sequencer internal state. */
typedef struct {
    uint32_t cycles;
    uint8_t  last_digest;
} FSeqState_t;

/* ---------------- seqlock mailbox ----------------
 * Exactly one writer per object. 64-byte aligned to avoid false sharing (A2).
 */
#define MBX_DATA_MAX 64

typedef struct {
    _Atomic uint32_t seq;       /* even == stable, odd == write in progress */
    uint64_t         ts_us;
    uint32_t         frame_id;
    uint8_t          data[MBX_DATA_MAX];
} Mbx_t;

/* ---------------- Health block ----------------
 * Every field has exactly one writer; the supervisor reads with relaxed atomic
 * loads and no lock (assessment section 2.1). The trailing fields are extra
 * observability counters added for the host demonstration.
 */
typedef struct {
    _Atomic uint32_t s1_last_ts, s1_frames, s1_crc_err, s1_seq_gap, s1_sync_err;
    _Atomic uint32_t s2_last_ts, s2_frames, s2_crc_err, s2_seq_gap, s2_sync_err;

    _Atomic uint32_t seq_hb, seq_exec_us, seq_exec_max_us, seq_missed_rel, act_busy_cnt;
    _Atomic uint32_t slow_hb, slow_exec_us, fb_stale_cnt;

    /* extra observability for the host report */
    _Atomic uint32_t act_tx, act_tx_err;
    _Atomic uint32_t sup_hb, sup_flags_last;
    _Atomic uint32_t tlm_frames, tlm_busy;
    _Atomic uint32_t wdt_kicks, wdt_skips;
} Health_t;

#endif /* FS_TYPES_H */

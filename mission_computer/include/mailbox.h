/*
 * mailbox.h
 *
 * Single-writer seqlock latest-value mailbox (assessment section 2.2, Fig. 7).
 *
 * Protocol
 * --------
 *   seq even  -> the object holds a complete, stable snapshot
 *   seq odd   -> a writer is mid-copy; readers must discard the snapshot
 *
 * The writer is wait-free: it bumps seq to odd, publishes with a release fence,
 * copies the data, then bumps seq to even with another release fence. It never
 * spins and never blocks a reader.
 *
 * The reader copies the data, re-reads seq and retries a bounded number of
 * times (MBX_MAX_RETRY). If every attempt overlapped a write it returns false
 * and the caller keeps its last-good local copy - the hard-real-time consumer
 * therefore has a bounded worst case and never waits on a lock.
 *
 * On the target the seq counter is a hardware atomic and the fences map to
 * DMB on ARM. On the host, C11 atomics provide the same release/acquire
 * ordering. Shared RAM must be non-cacheable / coherent (A2).
 */
#ifndef FS_MAILBOX_H
#define FS_MAILBOX_H

#include <string.h>
#include <stdatomic.h>
#include <stdbool.h>
#include "types.h"

/* Counters for observability of the seqlock under stress (host demo aid). */
extern _Atomic uint32_t g_mbx_reads;
extern _Atomic uint32_t g_mbx_retries;
extern _Atomic uint32_t g_mbx_timeouts;

static inline void Mbx_Publish(Mbx_t *m, const void *src, size_t n,
                               uint64_t ts_us, uint32_t frame_id)
{
    uint32_t s = atomic_load_explicit(&m->seq, memory_order_relaxed);

    atomic_store_explicit(&m->seq, s + 1u, memory_order_relaxed); /* odd */
    atomic_thread_fence(memory_order_release);

    memcpy(m->data, src, n);
    m->ts_us    = ts_us;
    m->frame_id = frame_id;

    atomic_store_explicit(&m->seq, s + 2u, memory_order_release); /* even */
}

static inline bool Mbx_Read(const Mbx_t *m, void *dst, size_t n,
                            uint64_t *ts_us, uint32_t *frame_id)
{
    atomic_fetch_add_explicit(&g_mbx_reads, 1u, memory_order_relaxed);

    for (uint32_t i = 0u; i < MBX_MAX_RETRY; i++)
    {
        uint32_t s1 = atomic_load_explicit(&m->seq, memory_order_acquire);

        if ((s1 & 1u) != 0u)
        {
            atomic_fetch_add_explicit(&g_mbx_retries, 1u, memory_order_relaxed);
            continue;                        /* writer mid-update, retry */
        }

        memcpy(dst, m->data, n);
        if (ts_us != NULL)     { *ts_us = m->ts_us; }
        if (frame_id != NULL)  { *frame_id = m->frame_id; }

        atomic_thread_fence(memory_order_acquire);

        if (s1 == atomic_load_explicit(&m->seq, memory_order_relaxed))
        {
            return true;                     /* stable, consistent snapshot */
        }

        atomic_fetch_add_explicit(&g_mbx_retries, 1u, memory_order_relaxed);
    }

    atomic_fetch_add_explicit(&g_mbx_timeouts, 1u, memory_order_relaxed);
    return false;                            /* caller keeps last good copy */
}

#endif /* FS_MAILBOX_H */

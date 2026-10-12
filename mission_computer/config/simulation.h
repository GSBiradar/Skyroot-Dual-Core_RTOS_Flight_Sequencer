/*
 * simulation.h
 *
 * Host-simulation knobs. On the target this file is replaced by the board
 * configuration; the application code does not depend on any of it.
 */
#ifndef FS_SIMULATION_H
#define FS_SIMULATION_H

/* How long the host demonstration runs before printing the report. */
#ifndef DEMO_RUN_SECONDS
#define DEMO_RUN_SECONDS      3u
#endif

/* Injected fault rates (percent), to exercise the safety paths. */
#ifndef SENSOR1_CORRUPT_PCT
#define SENSOR1_CORRUPT_PCT   1u
#endif
#ifndef SENSOR2_CORRUPT_PCT
#define SENSOR2_CORRUPT_PCT   1u
#endif
#ifndef LINE_ERR_PCT
#define LINE_ERR_PCT          1u   /* UART overrun/framing/noise */
#endif
#ifndef ACT_TX_FAIL_PCT
#define ACT_TX_FAIL_PCT       1u   /* actuator DMA start rejected */
#endif
#ifndef ACT_BUSY_INJECT_PCT
#define ACT_BUSY_INJECT_PCT   2u   /* keep actuator DMA busy longer */
#endif
#ifndef TLM_TX_BUSY_PCT
#define TLM_TX_BUSY_PCT       1u
#endif

#endif /* FS_SIMULATION_H */

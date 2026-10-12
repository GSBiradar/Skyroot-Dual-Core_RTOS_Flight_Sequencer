/*
 * flight_sequencer.h
 *
 * Public interface of the Flight Sequencer module. The module owns all tasks,
 * ISRs, mailboxes and the health block; main.c only starts it and asks for a
 * report at the end of the host run.
 */
#ifndef FS_FLIGHT_SEQUENCER_H
#define FS_FLIGHT_SEQUENCER_H

#include "types.h"

/* Build IPC + hardware, create all tasks, route ISRs, arm timers. Returns
 * immediately (the tasks are already runnable). */
void FlightSequencer_Init(void);

/* Print the end-of-run health / telemetry report. */
void FlightSequencer_PrintReport(void);

#endif /* FS_FLIGHT_SEQUENCER_H */

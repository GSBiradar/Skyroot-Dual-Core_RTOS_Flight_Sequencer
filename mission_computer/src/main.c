/*
 * main.c
 *
 * Host entry point. It mirrors the assessment's initialization sequence and
 * then runs the host simulation. On a real target this is the places where
 * BSP_ClockInit / BSP_Rs422Init / task creation would configure the board and
 * vTaskStartScheduler() would never return.
 */
#include "flight_sequencer.h"
#include "bsp_api.h"
#include "simulation.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    uint32_t seconds = DEMO_RUN_SECONDS;

    if (argc > 1)
    {
        int v = atoi(argv[1]);
        if (v > 0) { seconds = (uint32_t)v; }
    }

    printf("Flight Sequencer (dual-core RTOS) - host simulation\n");
    printf("run length: %u s   cores: Core0=I/O+supervisor+slow, Core1=FlightSeq\n\n",
           seconds);

    /* Build IPC + hardware, create tasks, route ISRs, arm timers. */
    FlightSequencer_Init();

    /* Start the hardware simulator and let the scheduler run. */
    BSP_RunForSeconds(seconds);

    /* End-of-run health / telemetry report. */
    FlightSequencer_PrintReport();

    return 0;
}

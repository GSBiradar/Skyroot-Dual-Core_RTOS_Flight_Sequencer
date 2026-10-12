#!/usr/bin/env python3
"""
generate_architecture_diagrams.py

Draw the project architecture diagrams as PNGs (grayscale-friendly) that are
embedded into the PDF report. Run:

    python scripts/generate_architecture_diagrams.py [--out docs/figures]

Produces:
  1. architecture_high_level.png  - dual-core split, tasks, external interfaces
  2. architecture_low_level.png   - ISRs, ingest, mailboxes, health, DMA TX

All block boxes carry the source-file name that implements them.
"""
import argparse
import os

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
except ImportError as exc:  # pragma: no cover
    raise SystemExit("matplotlib is required:  pip install matplotlib") from exc

INK = "#111111"
CORE0_FILL = "#ededed"
CORE1_FILL = "#f6f6f6"
EXT_FILL = "#ffffff"
MAIL_FILL = "#d9d9d9"
HW_FILL = "#e2e2e2"


def new_ax(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def box(ax, x0, y0, x1, y1, text, fc=EXT_FILL, ec=INK, lw=1.1, fs=7.6,
        weight="normal", style="round,pad=0.4", z=3):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                                boxstyle=style, fc=fc, ec=ec, lw=lw, zorder=z))
    if text:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
                fontsize=fs, fontweight=weight, color=INK, zorder=z + 1,
                linespacing=1.3)


def container(ax, x0, y0, x1, y1, label, fc, ec=INK, lw=1.6):
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=fc, ec=ec, lw=lw,
                           zorder=1, linestyle="-"))
    ax.text(x0 + 1.5, y1 - 2.2, label, ha="left", va="top", fontsize=8.5,
            fontweight="bold", color=INK, zorder=2)


def arrow(ax, p0, p1, rad=0.0, ls="-", lw=1.2, color=INK, z=5):
    con = "arc3,rad=%.2f" % rad
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=11,
                                 connectionstyle=con, color=color, lw=lw,
                                 linestyle=ls, zorder=z,
                                 shrinkA=1.0, shrinkB=1.0))


# ---------------------------------------------------------------------------
def fig_high_level(outdir):
    fig, ax = new_ax(10.6, 6.6)
    ax.text(50, 97.5, "High-Level Architecture - Dual-Core Flight Sequencer",
            ha="center", va="top", fontsize=12.5, fontweight="bold", color=INK)
    ax.text(50, 93.4, "One hard real-time core, one I/O/supervisor core, "
            "four lock-free mailboxes as the only boundary",
            ha="center", va="top", fontsize=8.2, color="#444444")

    # external inputs (left)
    box(ax, 1, 74, 19, 84, "Sensor 1  (RS422 in)\n32 B payload @ 5 ms", fs=7.4)
    box(ax, 1, 61, 19, 71, "Sensor 2  (RS422 in)\n54 B payload @ 10 ms", fs=7.4)

    # core containers
    container(ax, 23, 34, 61, 88, "Core 0  -  I/O, Supervisor, Housekeeping",
              CORE0_FILL)
    container(ax, 67, 34, 99, 88, "Core 1  -  Hard Real-Time", CORE1_FILL)

    # core 0 tasks
    box(ax, 26, 73, 58, 84,
        "T1  SensorIngestTask\nCRC - seq-gap - publish\nflight_sequencer.c", fs=7.2)
    box(ax, 26, 55, 58, 66,
        "T3  SupervisorTask\nhealth eval - telemetry - WDT\nflight_sequencer.c", fs=7.2)
    box(ax, 26, 38, 58, 49,
        "T4  SlowCompTask  (200 ms)\nslow dynamics -> feedback\n"
        "flight_sequencer.c", fs=7.2)

    # core 1 tasks
    box(ax, 70, 60, 96, 84,
        "T2  FlightSeqTask\n10 ms control loop\nsnapshot - latch - actuate\n"
        "flight_sequencer.c", fs=7.2, weight="normal")
    box(ax, 70, 44, 96, 55,
        "I3  TMR_A 10 ms release\nhw_timer - counting notify\nhost_bsp.c", fs=7.2)

    # mailboxes (between cores)
    box(ax, 58.2, 75, 69.8, 83, "g_nav1 / g_nav2\nseqlock mailboxes",
        fc=MAIL_FILL, fs=6.8)
    box(ax, 58.2, 34.5, 69.8, 42, "g_fb\nfeedback + activate",
        fc=MAIL_FILL, fs=6.8)
    box(ax, 58.2, 55, 69.8, 63, "g_seqOut\nsequencer output",
        fc=MAIL_FILL, fs=6.8)

    # cross-core data flow
    arrow(ax, (58.2, 79), (70, 76), rad=0.0)          # nav  -> core1
    arrow(ax, (70, 62), (58.2, 59), rad=0.0)          # seqOut -> core0
    arrow(ax, (58.2, 38), (70, 46), rad=0.0)          # fb  -> core1

    # external outputs (bottom right)
    box(ax, 67, 22, 99, 30, "Actuator  (RS422 out)\n20 B command @ 10 ms",
        fc=HW_FILL, fs=7.2)
    box(ax, 67, 11, 99, 19, "Telemetry  (RS422 out)\n64 B packet @ 10 ms",
        fc=HW_FILL, fs=7.2)

    # watchdog + support files
    box(ax, 40, 22, 60, 30,
        "Watchdog\nkicked only when\ncritical flags clear", fc=HW_FILL, fs=6.9)
    box(ax, 4, 40, 19, 55,
        "Board Support\nbsp_api.h\nhost_bsp.c\n(port contract)", fc=HW_FILL, fs=6.9)

    # IO arrows
    arrow(ax, (19, 79), (26, 79))                     # S1 -> ingest
    arrow(ax, (19, 66), (26, 66))                     # S2 -> ingest
    arrow(ax, (82, 44), (82, 30))                     # FlightSeq -> actuator
    arrow(ax, (42, 55), (78, 19.5), rad=-0.18)        # supervisor -> telemetry
    arrow(ax, (42, 55), (50, 30), rad=0.0)            # supervisor -> watchdog
    arrow(ax, (19, 47), (26, 45), rad=0.0)            # bsp -> core0
    arrow(ax, (19, 50), (70, 70), rad=-0.25, ls=(0, (4, 3)))  # bsp -> core1

    ax.text(50, 3, "types.h - mailbox.h - bsp_api.h - flight_sequencer.h  |  "
            "repository: github.com/GSBiradar/Skyroot-Dual-Core_RTOS_Flight_Sequencer",
            ha="center", va="bottom", fontsize=6.8, color="#555555", family="monospace")

    path = os.path.join(outdir, "architecture_high_level.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
def fig_low_level(outdir):
    fig, ax = new_ax(11.2, 6.8)
    ax.text(50, 98, "Low-Level Architecture - Tasks, ISRs, Mailboxes and DMA",
            ha="center", va="top", fontsize=12.5, fontweight="bold", color=INK)

    # core regions
    container(ax, 1, 8, 50, 92, "Core 0", CORE0_FILL)
    container(ax, 52, 8, 99, 92, "Core 1", CORE1_FILL)

    # --- Core 0 column: hardware -> ISR -> ingest ---
    box(ax, 4, 80, 24, 88, "UART S1 RX\nDMA ring + idle IRQ\nhost_bsp.c",
        fc=HW_FILL, fs=6.6)
    box(ax, 27, 80, 47, 88, "UART S2 RX\nDMA ring + idle IRQ\nhost_bsp.c",
        fc=HW_FILL, fs=6.6)
    box(ax, 4, 68, 24, 76, "I1  UART_S1_ISR\nrecord idx/ts, notify\n"
        "flight_sequencer.c", fs=6.6)
    box(ax, 27, 68, 47, 76, "I2  UART_S2_ISR\nrecord idx/ts, notify\n"
        "flight_sequencer.c", fs=6.6)
    arrow(ax, (14, 80), (14, 76))
    arrow(ax, (37, 80), (37, 76))

    box(ax, 6, 54, 46, 64,
        "T1  SensorIngestTask\nRingExtractFrame - CRC16 - seq-gap - "
        "Mbx_Publish\nflight_sequencer.c", fs=6.8)
    arrow(ax, (14, 68), (18, 64))
    arrow(ax, (37, 68), (33, 64))

    # --- mailbox boundary column (straddles the cores) ---
    box(ax, 41, 44, 61, 52,
        "g_nav1 / g_nav2\nMbx_Publish (T1)  ->  Mbx_Read (T2)\nmailbox.h - types.h",
        fc=MAIL_FILL, fs=6.5)
    box(ax, 41, 30, 61, 38,
        "g_fb  (feedback)\nT4 publish -> T2 latch @ frame%20\nmailbox.h",
        fc=MAIL_FILL, fs=6.5)
    box(ax, 41, 17, 61, 25,
        "g_seqOut  (16 B)\nT2 publish -> T4 read\nmailbox.h",
        fc=MAIL_FILL, fs=6.5)
    arrow(ax, (30, 54), (47, 52))          # ingest -> nav
    arrow(ax, (61, 48), (72, 62), rad=0.0)  # nav -> FlightSeq
    arrow(ax, (74, 60), (61, 34), rad=-0.15)  # FlightSeq -> seqOut
    arrow(ax, (61, 34), (30, 44), rad=0.15)   # fb -> (to slow, left)
    arrow(ax, (52, 21), (74, 62), rad=0.25, ls=(0, (4, 3)))  # seqOut -> slow path

    # --- Core 0 slow task ---
    box(ax, 6, 33, 40, 44,
        "T4  SlowCompTask  (200 ms)\nsnapshot g_seqOut - slow dynamics - "
        "publish g_fb\nflight_sequencer.c", fs=6.6)
    arrow(ax, (23, 33), (23, 25), rad=0.0)

    # --- Core 0 supervisor ---
    box(ax, 6, 12, 46, 24,
        "T3  SupervisorTask  (10 ms)\natomic health reads -> telemetry DMA - "
        "WDT kick\nflight_sequencer.c", fs=6.6)

    # --- Core 1 FlightSeq ---
    box(ax, 64, 74, 96, 88,
        "T2  FlightSeqTask  (10 ms)\nBSP_NotifyTake - Mbx_Read nav - latch fb - "
        "ComputeFlightActuation\nMbx_Publish g_seqOut - actuator DMA TX - health\n"
        "flight_sequencer.c", fs=6.7)
    box(ax, 64, 60, 96, 70,
        "I3  TMR_A_ISR 10 ms\nfree-running hw timebase\nhost_bsp.c",
        fc=HW_FILL, fs=6.7)
    arrow(ax, (80, 70), (80, 74))          # timer -> FlightSeq

    # --- shared health block ---
    box(ax, 6, 2, 96, 9,
        "Health block (types.h): atomic counters/timestamps, one writer per field "
        "- observed lock-free by T3\ng_health - g_frameId - seq/last_seq/wdt - "
        "read by SupervisorTask", fc=MAIL_FILL, fs=6.3)

    ax.text(50, -3.0, "SensorIngestTask and FlightSeqTask communicate only through "
            "seqlock mailboxes; no mutex/queue on the hard path.",
            ha="center", va="top", fontsize=7.0, color="#555555")

    path = os.path.join(outdir, "architecture_low_level.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("docs", "figures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    made = [fig_high_level(args.out), fig_low_level(args.out)]
    for m in made:
        print("wrote", m)


if __name__ == "__main__":
    main()

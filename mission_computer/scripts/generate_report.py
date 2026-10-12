#!/usr/bin/env python3
"""
generate_report.py

Builds a structured black-and-white PDF report for the dual-core Flight
Sequencer package. Run from anywhere:

    python scripts/generate_report.py [--out docs/Flight_Sequencer_Report.pdf]

Requires: reportlab, Pillow (for grayscale figures).
"""
import argparse
import os
import sys
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether, Preformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents

# --------------------------------------------------------------------------
# palette: strictly black / white / grays
# --------------------------------------------------------------------------
BLACK = colors.black
WHITE = colors.white
GRAY1 = colors.HexColor("#333333")
GRAY2 = colors.HexColor("#666666")
GRAY3 = colors.HexColor("#CCCCCC")
GRAY4 = colors.HexColor("#EEEEEE")
GRAY5 = colors.HexColor("#F7F7F7")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # mission_computer/
FIGDIR = os.path.join(ROOT, "docs", "figures")
BWDIR = os.path.join(ROOT, "docs", "figures_bw")


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------
def make_styles():
    S = {}
    S["Title"] = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=26,
                                leading=30, alignment=TA_CENTER, textColor=BLACK,
                                spaceAfter=6)
    S["Subtitle"] = ParagraphStyle("Subtitle", fontName="Helvetica", fontSize=13,
                                   leading=17, alignment=TA_CENTER, textColor=GRAY1,
                                   spaceAfter=4)
    S["Meta"] = ParagraphStyle("Meta", fontName="Helvetica", fontSize=10,
                               leading=14, alignment=TA_CENTER, textColor=GRAY2)
    S["H1"] = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=16,
                             leading=20, textColor=BLACK, spaceBefore=14,
                             spaceAfter=8, borderPadding=0)
    S["H2"] = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=12.5,
                             leading=16, textColor=BLACK, spaceBefore=10,
                             spaceAfter=5)
    S["H3"] = ParagraphStyle("H3", fontName="Helvetica-BoldOblique", fontSize=11,
                             leading=14, textColor=GRAY1, spaceBefore=8,
                             spaceAfter=4)
    S["Body"] = ParagraphStyle("Body", fontName="Helvetica", fontSize=10,
                               leading=14.5, textColor=BLACK, alignment=TA_JUSTIFY,
                               spaceAfter=6)
    S["Bullet"] = ParagraphStyle("Bullet", parent=S["Body"], leftIndent=14,
                                 bulletIndent=4, spaceAfter=3, alignment=TA_JUSTIFY)
    S["Cell"] = ParagraphStyle("Cell", fontName="Helvetica", fontSize=8.5,
                               leading=10.5, textColor=BLACK)
    S["CellH"] = ParagraphStyle("CellH", fontName="Helvetica-Bold", fontSize=8.5,
                                leading=10.5, textColor=BLACK)
    S["Code"] = ParagraphStyle("Code", fontName="Courier", fontSize=8,
                               leading=10, textColor=BLACK,
                               backColor=GRAY5, borderColor=GRAY3,
                               borderWidth=0.4, borderPadding=5,
                               spaceBefore=4, spaceAfter=8)
    S["Caption"] = ParagraphStyle("Caption", fontName="Helvetica-Oblique",
                                  fontSize=8.5, leading=11, alignment=TA_CENTER,
                                  textColor=GRAY2, spaceBefore=2, spaceAfter=10)
    S["TOC"] = ParagraphStyle("TOC", fontName="Helvetica", fontSize=10, leading=14)
    return S


# --------------------------------------------------------------------------
# document template with header/footer + TOC hooks
# --------------------------------------------------------------------------
class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, styles, **kw):
        BaseDocTemplate.__init__(self, filename, **kw)
        self.styles = styles
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      id="body")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame],
                                            onPage=self._decorate)])

    def _decorate(self, canvas, doc):
        canvas.saveState()
        w, h = A4
        # header
        canvas.setStrokeColor(GRAY3)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, h - 15 * mm, w - 18 * mm, h - 15 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAY2)
        canvas.drawString(18 * mm, h - 13 * mm,
                          "Flight Sequencer — Dual-Core RTOS Firmware")
        canvas.drawRightString(w - 18 * mm, h - 13 * mm, date.today().isoformat())
        # footer
        canvas.line(18 * mm, 13 * mm, w - 18 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(18 * mm, 9 * mm, "GSBiradar / Skyroot-Dual-Core_RTOS_Flight_Sequencer")
        canvas.drawRightString(w - 18 * mm, 9 * mm, "Page %d" % doc.page)
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            name = flowable.style.name
            text = flowable.getPlainText()
            if name == "H1":
                self.notify("TOCEntry", (0, text, self.page))
            elif name == "H2":
                self.notify("TOCEntry", (1, text, self.page))


# --------------------------------------------------------------------------
# flowable helpers
# --------------------------------------------------------------------------
class Ctx:
    def __init__(self, styles):
        self.S = styles
        self.f = []

    def h1(self, t):
        self.f.append(Paragraph(esc(t), self.S["H1"]))

    def h2(self, t):
        self.f.append(Paragraph(esc(t), self.S["H2"]))

    def h3(self, t):
        self.f.append(Paragraph(esc(t), self.S["H3"]))

    def p(self, t):
        self.f.append(Paragraph(esc(t), self.S["Body"]))

    def b(self, items):
        for it in items:
            self.f.append(Paragraph(esc(it), self.S["Bullet"], bulletText="\u2022"))

    def code(self, t):
        self.f.append(Preformatted(t, self.S["Code"]))

    def sp(self, h=6):
        self.f.append(Spacer(1, h))

    def pb(self):
        self.f.append(PageBreak())

    def caption(self, t):
        self.f.append(Paragraph(esc(t), self.S["Caption"]))

    def table(self, rows, widths=None, header=True):
        data = []
        for ri, row in enumerate(rows):
            st = self.S["CellH"] if (header and ri == 0) else self.S["Cell"]
            data.append([Paragraph(esc(c), st) for c in row])
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, BLACK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), GRAY3)]
        else:
            style += [("BACKGROUND", (0, 0), (-1, -1), WHITE)]
        t.setStyle(TableStyle(style))
        self.f.append(t)
        self.sp(8)

    def figure(self, name, caption, width_mm=150):
        path = os.path.join(BWDIR, name)
        if not os.path.exists(path):
            return
        from PIL import Image as PILImage
        iw, ih = PILImage.open(path).size
        w = width_mm * mm
        h = w * ih / iw
        self.f.append(Image(path, width=w, height=h))
        self.caption(caption)


def to_grayscale():
    """Create grayscale copies of the timing figures for the B&W report."""
    os.makedirs(BWDIR, exist_ok=True)
    if not os.path.isdir(FIGDIR):
        return
    try:
        from PIL import Image as PILImage
    except ImportError:
        return
    for fn in os.listdir(FIGDIR):
        if fn.lower().endswith(".png"):
            im = PILImage.open(os.path.join(FIGDIR, fn)).convert("L")
            im.save(os.path.join(BWDIR, fn))


# --------------------------------------------------------------------------
# report content
# --------------------------------------------------------------------------
def build_story(styles):
    c = Ctx(styles)
    S = styles

    # ---------------- title page ----------------
    c.f.append(Spacer(1, 45 * mm))
    c.f.append(Paragraph("Flight Sequencer", S["Title"]))
    c.f.append(Paragraph("Dual-Core RTOS Firmware Design", S["Subtitle"]))
    c.f.append(Spacer(1, 6 * mm))
    c.f.append(Paragraph("Technical Report — Architecture, Synchronization, "
                         "Timing Analysis and Reference Implementation",
                         S["Subtitle"]))
    c.f.append(Spacer(1, 30 * mm))
    c.f.append(Paragraph("Embedded Firmware Design Assessment", S["Meta"]))
    c.f.append(Paragraph("Launch-Vehicle Flight Sequencer on a Multi-Core MCU", S["Meta"]))
    c.f.append(Spacer(1, 8 * mm))
    c.f.append(Paragraph("Author: GSBiradar", S["Meta"]))
    c.f.append(Paragraph("Repository: github.com/GSBiradar/"
                         "Skyroot-Dual-Core_RTOS_Flight_Sequencer", S["Meta"]))
    c.f.append(Paragraph("Source package: mission_computer/  "
                         "(include, src, platform, config, scripts, docs)",
                         S["Meta"]))
    c.f.append(Paragraph(date.today().isoformat(), S["Meta"]))
    c.pb()

    # ---------------- TOC ----------------
    c.f.append(Paragraph("Contents", S["H1"]))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc0", fontName="Helvetica-Bold", fontSize=10.5,
                       leading=15, leftIndent=0, firstLineIndent=0),
        ParagraphStyle("toc1", fontName="Helvetica", fontSize=9.5,
                       leading=13, leftIndent=16, firstLineIndent=0),
    ]
    c.f.append(toc)
    c.pb()

    # ---------------- 1 executive summary ----------------
    c.h1("1. Executive Summary")
    c.p("This report documents a complete design and a working reference "
        "implementation of a Flight Sequencer for a launch-vehicle computer. "
        "The system runs on a dual-core 32-bit MCU under a preemptive, "
        "fixed-priority RTOS. The central engineering decision is an "
        "asymmetric core split: one core is reserved exclusively for the hard "
        "real-time Flight Sequencer, while the other core absorbs all "
        "asynchronous I/O, supervision and slow background computation. This "
        "isolates the 10 ms control loop from every source of jitter that can "
        "be removed by partitioning.")
    c.p("All cross-core and cross-rate data is exchanged through single-writer "
        "seqlock latest-value mailboxes and hardware-timer-driven task "
        "notifications. There are no mutexes, queues or kernel calls on the "
        "hard real-time path, so the highest-priority consumer never waits on a "
        "lower-priority producer. Sensor reception uses DMA plus an idle-line "
        "interrupt with validation deferred to a high-priority ingest task; "
        "transmission uses DMA with polled completion because the timing is "
        "controlled by the flight software.")
    c.p("The package is executable: the same application code that targets "
        "FreeRTOS-SMP compiles and runs on Windows and Linux through a host "
        "board-support port that simulates both cores, four RS422 ports, the "
        "hardware timers, the watchdog and an injectable fault model. A three "
        "second run reproduces roughly 300 sequencer cycles, 600 sensor-1 "
        "frames and 300 sensor-2 frames, with the safety paths (CRC rejection, "
        "stale-data hold, non-blocking transmit and watchdog gating) all "
        "exercised and observed in the health report.")

    # ---------------- 2 introduction ----------------
    c.h1("2. Introduction")
    c.h2("2.1 Purpose")
    c.p("The purpose of this document is to present, in a single place, the "
        "requirements, architecture, synchronization strategy, timing analysis, "
        "implementation, build/run instructions, validation evidence and "
        "porting guidance for the Flight Sequencer. It is written to be read "
        "from the top down: the early sections give the context and the "
        "requirements, the middle sections give the design and the code, and "
        "the appendices give the reference detail.")
    c.h2("2.2 Scope")
    c.p("In scope: task and interrupt design, inter-process communication "
        "(IPC), synchronization and concurrency correctness, interrupt-vs-"
        "polling strategy, real-time determinism and response-time reasoning, "
        "and a runnable C reference implementation with a host simulation. Out "
        "of scope: mission-specific flight dynamics. The guidance algorithms "
        "are deterministic, bounded placeholders because the navigation payload "
        "semantics and a mission interface-control document are not part of the "
        "assessment. The architecture preserves the timing contract that a real "
        "algorithm would have to satisfy.")
    c.h2("2.3 Definitions and Abbreviations")
    c.table([
        ["Term", "Meaning"],
        ["ISR", "Interrupt Service Routine"],
        ["DMA", "Direct Memory Access — hardware moves bytes without the CPU"],
        ["IPC", "Inter-Process Communication"],
        ["WCET", "Worst-Case Execution Time"],
        ["Seqlock", "Sequence-lock: a lock-free, wait-free-writer data exchange"],
        ["Mailbox", "A fixed-size single-writer shared buffer with latest-value semantics"],
        ["FDIR", "Fault Detection, Isolation and Recovery"],
        ["Watchdog", "Hardware timer that resets the system unless periodically kicked"],
        ["Frame", "One RS422 message: 2 B sync + 1 B seq + 1 B len + payload + 2 B CRC16"],
    ], widths=[28 * mm, None])

    # ---------------- 3 requirements ----------------
    c.h1("3. Requirements and Assumptions")
    c.h2("3.1 Functional Requirements")
    c.b([
        "Acquire Sensor 1 (32 B) every 5 ms and Sensor 2 (54 B) every 10 ms over RS422.",
        "Run a Flight Sequencer control loop every 10 ms that consumes the latest sensor "
        "data and a 16-byte feedback value, and produces a 20-byte actuator command and a "
        "16-byte output for the slow task.",
        "Run a slow computation every 200 ms that consumes navigation and sequencer output "
        "and produces 16-byte feedback applied back into the loop.",
        "Run a 10 ms supervisor that monitors health and emits telemetry.",
        "Never block the control loop waiting for data; on stale or invalid input, hold the "
        "last good value, raise a flag and degrade safely.",
        "Feed a watchdog only when the monitored health is valid.",
    ])
    c.h2("3.2 Non-Functional (Timing) Requirements")
    c.table([
        ["Activity", "Period / trigger", "Deadline", "WCET budget"],
        ["Sensor 1 ingest", "5 ms (event)", "before next 5 ms frame", "40 us/frame"],
        ["Sensor 2 ingest", "10 ms (event)", "before next 10 ms frame", "40 us/frame"],
        ["Flight Sequencer", "10 ms", "10 ms", "3 ms"],
        ["Supervisor", "10 ms (phase +6 ms)", "10 ms", "200 us"],
        ["Slow computation", "200 ms", "200 ms", "40 ms"],
    ], widths=[40 * mm, 38 * mm, 42 * mm, None])
    c.h2("3.3 Assumptions")
    c.p("The brief leaves hardware details open; the following assumptions are "
        "made explicit and can be revised without changing the structure of the "
        "design.")
    c.table([
        ["#", "Assumption"],
        ["A1", "Dual-core 32-bit MCU at 200 MHz or faster, shared on-chip SRAM, hardware "
               "atomics (LDREX/STREX), a shared free-running 1 microsecond timebase readable "
               "by both cores, per-interrupt core routing, and a hardware watchdog."],
        ["A2", "Shared RAM is mapped non-cacheable through the MPU (or is hardware-coherent). "
               "Every shared object is 64-byte aligned to avoid false sharing."],
        ["A3", "The RTOS is SMP, preemptive and fixed-priority (higher number = higher "
               "priority) with hard per-task core affinity, a 1 kHz tick, and static allocation "
               "only (no heap after init)."],
        ["A4", "RS422 ports are UARTs at 1 Mbaud, 8N1 (10 microseconds per byte). Each has its "
               "own DMA channel (circular RX or one-shot TX) and idle-line detection."],
        ["A5", "Frame format = 2 B sync + 1 B sequence + 1 B length + payload + 2 B CRC16 "
               "(6 B overhead). Wire times: Sensor 1 (38 B) 0.38 ms, Sensor 2 (60 B) 0.60 ms, "
               "actuator (26 B) 0.26 ms, telemetry (64 B) 0.64 ms."],
        ["A6", "Sensors push frames autonomously at exact periods; their phase relative to the "
               "MCU is unknown. The design works for any phase."],
        ["A7", "WCET budgets: ISR 5 us, sensor ingest 40 us per frame, Flight Sequencer 3 ms, "
               "Supervisor 200 us, slow task 40 ms."],
        ["A8", "Failure policy: cyclic tasks never block waiting for data. Stale or invalid "
               "input means hold the last good value, raise a flag, and enter degraded mode."],
        ["A9", "The 200 ms feedback is applied only at a fixed frame boundary (every 20th "
               "frame), so behaviour is repeatable regardless of when the slow task finishes."],
    ], widths=[10 * mm, None])

    # ---------------- 4 architecture ----------------
    c.h1("4. System Architecture")
    c.h2("4.1 Multi-Core Strategy")
    c.p("The design partitions work so that the hard real-time control loop has a "
        "dedicated core.")
    c.b([
        "Core 1 is the deterministic compute core. It runs only the Flight Sequencer task and "
        "its 3 microsecond timer ISR. No UART interrupt, no logging and no lower-priority task "
        "can run there, so jitter comes only from the timer ISR and shared-bus contention.",
        "Core 0 is the I/O and housekeeping core. It absorbs all asynchronous events (sensor "
        "frame interrupts), ingest, supervision and the slow computation. Its load is about "
        "23 percent, and the slow task is lowest priority, so everything else preempts it and "
        "it can never delay ingestion.",
        "Contention is minimised because every shared object has exactly one writer and a "
        "wait-free write path. The cores communicate only through four small mailboxes. There "
        "are no cross-core mutexes, queues or kernel calls on the critical path.",
        "Why the slow task is on Core 0: placing a 40 ms task on Core 1 would let it interfere "
        "with the hard 10 ms task and would put the cross-core boundary in the wrong place. "
        "Core 1 keeps spare capacity for growth.",
    ])
    c.figure("architecture_high_level.png",
             "Figure 1. High-level architecture: the dual-core split, task "
             "placement, external RS422 interfaces and the four lock-free "
             "mailboxes that form the only cross-core boundary.",
             width_mm=165)
    c.h2("4.2 Low-Level Architecture")
    c.p("The low-level view shows the concrete implementation units and the "
        "source file that owns each one. On Core 0 a UART RX DMA ring per sensor "
        "raises one idle-line interrupt (I1/I2) which notifies the single ingest "
        "task (T1); T1 validates the frame and publishes it into a seqlock "
        "mailbox. On Core 1 a hardware timer (I3) releases the Flight Sequencer "
        "(T2), which snapshots the navigation mailboxes, latches feedback only on "
        "a 20-frame boundary, publishes g_seqOut and starts the actuator DMA. The "
        "slow task (T4) and the supervisor (T3) live on Core 0 and reach the "
        "sequencer only through the mailboxes and the shared atomic health block.")
    c.figure("architecture_low_level.png",
             "Figure 2. Low-level architecture: ISRs, DMA rings, the seqlock "
             "mailboxes (g_nav1, g_nav2, g_fb, g_seqOut) and the shared health "
             "block, annotated with the implementing source files.",
             width_mm=170)
    c.p("Implementing files: interrupts, tasks, mailboxes and health live in "
        "src/modules/flight_sequencer.c; the shared types and sizes are in "
        "include/types.h; the seqlock protocol is header-only in "
        "include/mailbox.h; the port contract is include/bsp_api.h, implemented "
        "for the host by platform/host_bsp.c; the entry point is src/main.c; and "
        "run-time parameters are in config/simulation.h. All of these live in the "
        "mission_computer/ package of the repository.")
    c.h2("4.3 Tasks, Timers and Interrupts")
    c.table([
        ["ID", "Name", "Kind", "Core", "Prio", "Trigger / period", "Budget"],
        ["I1", "UART_S1_ISR", "ISR", "0", "IRQ 1", "Sensor 1 frame end, 5 ms", "5 us"],
        ["I2", "UART_S2_ISR", "ISR", "0", "IRQ 1", "Sensor 2 frame end, 10 ms", "5 us"],
        ["I3", "TMR_A_ISR", "ISR", "1", "IRQ 2", "10 ms, phase 0", "3 us"],
        ["I4", "TMR_B_ISR", "ISR", "0", "IRQ 2", "10 ms, phase +6 ms", "3 us"],
        ["T1", "SensorIngestTask", "task", "0", "5", "notified by I1/I2", "40 us/fr"],
        ["T2", "FlightSeqTask", "task", "1", "5", "released by I3, 10 ms", "3 ms"],
        ["T3", "SupervisorTask", "task", "0", "4", "released by I4, 10 ms", "200 us"],
        ["T4", "SlowCompTask", "task", "0", "2", "every 20th frame, 200 ms", "40 ms"],
    ], widths=[8 * mm, 30 * mm, 12 * mm, 10 * mm, 12 * mm, 40 * mm, None])
    c.p("Priority ordering, higher number meaning more urgent: ISRs above all "
        "tasks; then on the application side FlightSeq (5) equals ingest (5) but "
        "on a different core; Supervisor (4) then SlowComp (2). All interrupt "
        "priorities are numerically at or below the kernel syscall ceiling, so "
        "the FromISR APIs are legal.")
    c.h2("4.4 Data Flow and IPC Map")
    c.code(
        " Sensor1 (5 ms)  --DMA ring--> UART_S1_ISR --notify(EVT_S1)--> T1 Ingest\n"
        " Sensor2 (10 ms) --DMA ring--> UART_S2_ISR --notify(EVT_S2)--> T1 Ingest\n"
        "                                                                  |\n"
        "                    seqlock mailbox g_nav1 / g_nav2  <-----------+\n"
        "                                                                  |\n"
        "            +-----------------+------------------+--------------+\n"
        "            v                                    v\n"
        "      T2 FlightSeq (Core 1)                T4 SlowComp (Core 0)\n"
        "      - snapshot nav                       - snapshot nav + g_seqOut\n"
        "      - latch feedback @ frame%20          - CalculateSlowDynamics\n"
        "      - ComputeFlightActuation             - publish g_fb + activate_frame\n"
        "      - publish g_seqOut (seqlock)  ------>\n"
        "      - actuator DMA TX (20 B)\n"
        "      - health counters\n"
        "            ^\n"
        "            |  g_fb (seqlock, latched at fixed boundary)\n"
        "            |\n"
        " T3 Supervisor (10 ms) --atomic reads--> telemetry --DMA TX(UART_TLM)\n"
        "        |\n"
        "        +--> Wdt_Kick() only if critical flags clear")
    c.sp(4)
    c.table([
        ["Data / event", "Mechanism", "Why"],
        ["Frame received", "Direct bit notification (ISR to T1)",
         "Lightest unblock primitive, same core, no allocation."],
        ["Nav 1 / Nav 2 latest", "Seqlock latest-value mailbox",
         "Only the newest sample matters; a queue would grow stale or drop."],
        ["Periodic release", "Counting notification (I3 to T2; I4 to T3/T4)",
         "Hardware-driven release; the count also exposes missed releases."],
        ["Sequencer output (16 B)", "Seqlock mailbox g_seqOut",
         "Wait-free for the 10 ms writer."],
        ["Feedback (16 B)", "Seqlock mailbox g_fb + activate_frame",
         "Reader never blocks on the slow task; result activates at a fixed boundary."],
        ["Actuator command (20 B)", "T2-owned DMA buffer",
         "Single owner, nothing to share."],
        ["Health data", "Atomic counters/timestamps, one writer per field",
         "Supervisor observes faults with no lock."],
        ["Watchdog", "Kicked only by T3 when critical flags are clear",
         "Converts missed timing or stale data into observable reset behaviour."],
    ], widths=[32 * mm, 55 * mm, None])
    c.h2("4.5 Hardware Interface Strategy: Interrupts versus Polling")
    c.p("Per-frame costs at 1 Mbaud are 10 microseconds per byte. Sensor 1 "
        "(38 B) occupies about 0.38 ms of its 5 ms period and Sensor 2 (60 B) "
        "about 0.60 ms of its 10 ms period. A per-byte RX interrupt strategy "
        "would generate roughly 13,000 interrupts per second; polling would "
        "require a tight poll interval during each burst and would burn CPU.")
    c.table([
        ["Option", "Pros", "Cons for this timing budget"],
        ["Per-byte RX interrupt", "Simple, no DMA",
         "About 13,000 ISRs/s at about 1.5 us each (about 2 percent CPU) and a "
         "preemption every 10 us during each 0.4 to 0.6 ms burst. Large, "
         "unpredictable jitter."],
        ["Polling (busy or fast task)", "Fully deterministic, easiest to certify",
         "Must poll at least every 160 us during bursts. Costs about 7 percent "
         "(S1) plus 6 percent (S2) of a core and starves lower tasks; fails if a "
         "frame is late or a poll slips."],
        ["DMA + idle-line IRQ (chosen)", "One ISR per frame (about 300/s, about "
         "0.05 percent CPU); bytes land with no CPU cost; idle-line gives automatic "
         "frame resync",
         "Needs DMA and ring-buffer handling; ISR latency adds a small, bounded jitter."],
    ], widths=[38 * mm, 52 * mm, None])
    c.p("Decision: use interrupts where arrival is asynchronous (the two sensor "
        "receives) and polled DMA completion where the flight software controls "
        "the timing (actuator and telemetry transmit). A rejected actuator frame "
        "is counted, never retried in the loop.")
    c.figure("rx_interrupt_rate.png",
             "Figure 3. RX strategy: event rate and approximate CPU cost.")

    # ---------------- 5 timing ----------------
    c.h1("5. Timing and Determinism Analysis")
    c.h2("5.1 Interrupt Load")
    c.p("Each sensor needs one interrupt per frame, so both sensors together "
        "produce about 300 interrupts per second at roughly 5 microseconds each "
        "-- about 0.05 percent of a core. This is why DMA plus idle-line "
        "interrupt beats per-byte interrupts by two orders of magnitude.")
    c.figure("wire_time_vs_period.png",
             "Figure 4. Frame wire time versus period budget: why DMA is required.")
    c.h2("5.2 Worst-Case Response Times")
    c.p("The Flight Sequencer owns Core 1, so its worst-case response is its own "
        "WCET plus the timer ISR plus a bus-contention allowance: about "
        "3 ms + 3 us + 30 percent, approximately 3.9 ms against a 10 ms "
        "deadline. That leaves about 6 ms of slack. Sensor ingest on Core 0 has "
        "a worst case of ISR (5 us) + at most one other ingest in progress "
        "(40 us) + its own work (40 us), under 100 us, about 2 percent of the "
        "5 ms period.")
    c.table([
        ["Activity", "Worst-case response", "Deadline", "Slack"],
        ["Sensor ingest", "about 0.1 ms", "5 ms", "about 4.9 ms"],
        ["Flight Sequencer", "about 3.9 ms", "10 ms", "about 6.1 ms"],
        ["Supervisor", "about 0.2 ms", "10 ms", "about 9.8 ms"],
        ["Slow computation", "about 45 ms", "200 ms", "about 155 ms"],
    ], widths=[40 * mm, 42 * mm, 32 * mm, None])
    c.figure("response_vs_deadline.png",
             "Figure 5. Worst-case response versus deadline (log scale).")
    c.h2("5.3 CPU Utilisation")
    c.p("Core 0 utilisation: ISRs and ingest about 1.1 percent, supervisor about "
        "1.5 percent, slow task about 20 percent, total about 23 percent. Core 1 "
        "utilisation: the 3 ms sequencer in a 10 ms period is about 30 percent. "
        "Core 1 is isolated from all asynchronous load, which is the key "
        "determinism decision.")
    c.figure("core_utilisation.png",
             "Figure 6. CPU utilisation by WCET budget.")
    c.h2("5.4 Data Age and Staleness")
    c.p("With unsynchronised sensors, the worst-case data age at the sequencer "
        "is under 5.5 ms for Sensor 1 and under 10.7 ms for Sensor 2. The "
        "staleness limits are 7.5 ms and 15 ms (1.5 periods); exceeding a limit "
        "means hold the last good value and raise a flag. Worst-case "
        "sample-to-actuator latency is about 9.6 ms for Sensor 1 and about "
        "14.9 ms for Sensor 2.")
    c.figure("sample_to_actuator.png",
             "Figure 7. Worst-case sample-to-actuator latency budget.")
    c.h2("5.5 Overrun and Missed-Release Detection")
    c.p("Counting notifications reveal missed releases, and any WCET breach is "
        "reported in telemetry and gates the watchdog. This turns any future "
        "violation into an observable signal rather than silent drift.")

    # ---------------- 6 synchronization ----------------
    c.h1("6. Synchronization and Concurrency")
    c.h2("6.1 Shared Resources")
    c.table([
        ["Resource", "Writer", "Readers", "Critical section"],
        ["g_nav1 (32 B + ts)", "T1 (Core 0)", "T2 (Core 1), T4", "Mailbox write / copy"],
        ["g_nav2 (54 B + ts)", "T1 (Core 0)", "T2 (Core 1), T4", "Mailbox write / copy"],
        ["g_seqOut (16 B)", "T2 (Core 1)", "T4 (Core 0)", "Mailbox write / copy"],
        ["g_fb (16 B feedback)", "T4 (Core 0)", "T2 (Core 1)", "Mailbox write / copy"],
        ["Health block", "One writer per field", "T3", "None (atomic word access)"],
        ["UART RX rings", "DMA", "I1/I2 then T1", "Producer-index handoff via ISR"],
        ["TX buffers", "T2 / T3", "DMA", "Owned by sender; busy flag checked first"],
        ["g_frameId", "I3", "T2, I4", "Single atomic word"],
    ], widths=[34 * mm, 30 * mm, 30 * mm, None])
    c.h2("6.2 The Seqlock Mailbox Protocol")
    c.p("A seqlock carries a sequence counter: even means the snapshot is stable, "
        "odd means a write is in progress. The writer is wait-free; the reader "
        "copies, rechecks the counter, and retries a bounded number of times. The "
        "writer takes a roughly 0.2 microsecond critical section with local-core "
        "interrupts masked, so it cannot be preempted mid-write on its own core.")
    c.code(
        "static inline void Mbx_Publish(Mbx_t *m, const void *src, size_t n,\n"
        "                               uint64_t ts_us, uint32_t frame_id)\n"
        "{\n"
        "    uint32_t s = atomic_load_explicit(&m->seq, memory_order_relaxed);\n"
        "    atomic_store_explicit(&m->seq, s + 1u, memory_order_relaxed); /* odd */\n"
        "    atomic_thread_fence(memory_order_release);\n"
        "    memcpy(m->data, src, n);  m->ts_us = ts_us;  m->frame_id = frame_id;\n"
        "    atomic_store_explicit(&m->seq, s + 2u, memory_order_release); /* even */\n"
        "}\n"
        "\n"
        "static inline bool Mbx_Read(const Mbx_t *m, void *dst, size_t n,\n"
        "                            uint64_t *ts_us, uint32_t *frame_id)\n"
        "{\n"
        "    for (uint32_t i = 0u; i < MBX_MAX_RETRY; i++) {\n"
        "        uint32_t s1 = atomic_load_explicit(&m->seq, memory_order_acquire);\n"
        "        if ((s1 & 1u) != 0u) continue;              /* writer active */\n"
        "        memcpy(dst, m->data, n);\n"
        "        atomic_thread_fence(memory_order_acquire);\n"
        "        if (s1 == atomic_load_explicit(&m->seq, memory_order_relaxed))\n"
        "            return true;                            /* stable snapshot */\n"
        "    }\n"
        "    return false;                                   /* keep last good */\n"
        "}")
    c.h2("6.3 Correctness Arguments")
    c.b([
        "No torn reads: the reader accepts a snapshot only when the sequence counter is "
        "unchanged across the copy, with release/acquire ordering (DMB on ARM).",
        "No race on latest-value reads: readers take the freshest complete value and never "
        "block; staleness is detected by a wrap-safe timestamp and per-source sequence.",
        "No deadlock: no nested locks, no blocking call while holding exclusion, and no lock "
        "shared between cores. The only exclusion is a local IRQ mask of bounded length.",
        "No priority inversion: the high-priority consumer never waits on a lower-priority "
        "producer. Cross-core priority inheritance does not exist, which is a further reason "
        "to avoid mutexes on the hard path; any mutex is confined to non-critical Core 0 code.",
        "Different task frequencies: latest-value semantics decouple the 5, 10 and 200 ms "
        "rates; each consumer snapshots at the start of its cycle and works on the copy.",
        "Feedback loop integrity: g_fb carries activate_frame, so T2 latches new feedback only "
        "on a 20-frame boundary; output is deterministic and the previous value is held (with "
        "a stale counter) if the slow task is late.",
    ])

    # ---------------- 7 implementation ----------------
    c.h1("7. Implementation")
    c.h2("7.1 File Layout")
    c.table([
        ["Path", "Responsibility"],
        ["include/types.h", "Sizes, rates, frame format, Health_t, Mbx_t, payload types"],
        ["include/mailbox.h", "Header-only seqlock publish/read"],
        ["include/bsp_api.h", "The only interface the application depends on"],
        ["src/modules/flight_sequencer.c", "Tasks T1-T4, ISRs I1-I4, init and report"],
        ["src/main.c", "Host entry: init, run, report"],
        ["platform/host_bsp.c", "POSIX host port + fault-injecting hardware simulator"],
        ["config/simulation.h", "Run length and injected fault rates"],
        ["Makefile / CMakeLists.txt", "Host builds"],
        ["scripts/generate_timing_plots.py", "Regenerate the timing figures"],
        ["scripts/generate_report.py", "Build this report"],
        ["docs/*.md", "Architecture, decisions, validation, traceability, integration"],
    ], widths=[58 * mm, None])
    c.p("The complete package is published at github.com/GSBiradar/"
        "Skyroot-Dual-Core_RTOS_Flight_Sequencer under the mission_computer/ "
        "directory. Every source file, header, build file, figure-generation "
        "script and document listed above is committed there; the two "
        "architecture diagrams and the timing figures in this report are "
        "reproduced by the scripts in scripts/.")
    c.h2("7.2 The Board-Support Contract")
    c.p("The application is written only against include/bsp_api.h. On the target "
        "that contract is implemented over FreeRTOS-SMP or CMSIS-RTOS2; on a PC "
        "it is implemented by platform/host_bsp.c. The contract covers time, "
        "task creation with core affinity, bit and counting notifications, a "
        "local IRQ mask, hardware timers, RS422/UART with DMA, and the watchdog. "
        "Because the contract is small, porting is a bounded task.")
    c.h2("7.3 Sensor Ingest (T1)")
    c.p("The UART idle-line ISR records the DMA write index and timestamp, then "
        "notifies the ingest task. The ingest task pulls the newest complete "
        "frame out of the circular ring, validates the CRC, tracks sequence "
        "gaps, and publishes the payload to the navigation mailbox. Bad frames "
        "are discarded and counted; the last good snapshot is retained.")
    c.code(
        "static void IngestOne(RxCtx_t *c, Mbx_t *mbx, uint32_t uart, uint32_t len, ...)\n"
        "{\n"
        "    Frame_t f;\n"
        "    if (!RingExtractFrame(uart, len, &f)) { atomic_fetch_add(sync_err, 1); return; }\n"
        "    uint16_t stored = f.raw[f.n-2] | (f.raw[f.n-1] << 8);\n"
        "    if (Crc16(f.raw, f.n - 2u) != stored) { atomic_fetch_add(crc_err, 1); return; }\n"
        "    uint8_t gap = (uint8_t)(f.seq - c->last_seq - 1u);\n"
        "    if (gap) atomic_fetch_add(seq_gap, gap);\n"
        "    c->last_seq = f.seq;\n"
        "    Mbx_Publish(mbx, f.payload, len, c->isr_ts, 0u);\n"
        "    atomic_store(last_ts, (uint32_t)c->isr_ts);\n"
        "    atomic_fetch_add(frames, 1);\n"
        "}")
    c.h2("7.4 Flight Sequencer (T2)")
    c.p("The sequencer waits on a counting notification from the 10 ms timer. It "
        "reads the latest navigation snapshots (keeping the last good copy on a "
        "failed read), checks freshness, latches feedback only on a 20-frame "
        "boundary, computes the actuation, publishes the 16-byte output, starts "
        "the 20-byte actuator DMA transmit, and updates its execution-time and "
        "heartbeat counters. It never blocks on data and never busy-waits on "
        "transmit.")
    c.code(
        "uint32_t rel = BSP_NotifyTake(true, BSP_WAIT_FOREVER);\n"
        "if (rel > 1u) atomic_fetch_add(&g_health.seq_missed_rel, rel - 1u);\n"
        "uint64_t t0 = BSP_HwTimeUs();\n"
        "uint32_t frame = atomic_load(&g_frameId);\n"
        "\n"
        "if (Mbx_Read(&g_nav1, &t1, N1_LEN, &ts1, &d)) n1 = t1;   /* keep last good */\n"
        "if (Mbx_Read(&g_nav2, &t2, N2_LEN, &ts2, &d)) n2 = t2;\n"
        "bool v1 = ((t0 - ts1) <= NAV1_MAX_AGE_US);\n"
        "bool v2 = ((t0 - ts2) <= NAV2_MAX_AGE_US);\n"
        "\n"
        "if ((frame % SLOW_DIV) == 0u) {                          /* fixed boundary */\n"
        "    if (Mbx_Read(&g_fb, &fbTmp, sizeof(fbTmp), &tsf, &d) &&\n"
        "        fbTmp.cycle_id != fbCycle && fbTmp.activate_frame <= frame)\n"
        "    { fb = fbTmp.payload; fbCycle = fbTmp.cycle_id; }\n"
        "    else atomic_fetch_add(&g_health.fb_stale_cnt, 1u);   /* hold previous */\n"
        "}\n"
        "ComputeFlightActuation(&st, &n1, &n2, v1, v2, &fb, &cmd, &out16);\n"
        "Mbx_Publish(&g_seqOut, &out16, SEQOUT_LEN, t0, frame);\n"
        "if (!BSP_DmaTxBusy(UART_ACT)) { start actuator DMA; }    /* non-blocking */\n"
        "else atomic_fetch_add(&g_health.act_busy_cnt, 1u);")
    c.h2("7.5 Slow Computation (T4)")
    c.p("The slow task is released every 20th frame by the supervisor timer. It "
        "snapshots navigation and the sequencer output, computes the slow "
        "dynamics, and publishes feedback together with the next activation "
        "boundary so the sequencer can apply it deterministically.")
    c.h2("7.6 Supervisor and Watchdog (T3)")
    c.p("The supervisor runs at frame start plus 6 ms. It reads the atomic health "
        "block without locks, evaluates sensor freshness, CRC faults, sequencer "
        "heartbeat, the execution-time budget, missed releases, actuator transmit "
        "and slow-task health, builds a telemetry packet and transmits it by DMA. "
        "It kicks the watchdog only when every critical flag is clear. Fault "
        "detection is edge-triggered (it compares against the previous cycle), so "
        "a single transient event does not latch a fault forever and the "
        "watchdog keeps guarding while the system is healthy.")
    c.code(
        "uint32_t s1c = atomic_load(&g_health.s1_crc_err);\n"
        "uint32_t s2c = atomic_load(&g_health.s2_crc_err);\n"
        "if (s1c > lastS1Crc || s2c > lastS2Crc) flags |= F_NAV_CRC;   /* new faults only */\n"
        "lastS1Crc = s1c;  lastS2Crc = s2c;\n"
        "if (atomic_load(&g_health.seq_exec_us) > SEQ_BUDGET_US) flags |= F_SEQ_OVERRUN;\n"
        "...\n"
        "if ((flags & F_CRITICAL_MASK) == 0u) { BSP_WdtKick(); }        /* gate */")

    # ---------------- 8 build & run ----------------
    c.h1("8. Building and Running")
    c.h2("8.1 Windows (MinGW-w64 gcc)")
    c.code("gcc -std=c11 -O2 -Iinclude -Iconfig \\\n"
           "    src/main.c src/modules/flight_sequencer.c platform/host_bsp.c \\\n"
           "    -o flight_seq.exe -pthread\n"
           ".\\flight_seq.exe            # runs about 3 s, prints a report, exits")
    c.h2("8.2 Linux / WSL")
    c.code("sudo apt install -y build-essential\n"
           "make run                    # build + run\n"
           "make run ARGS=10            # 10 second soak")
    c.h2("8.3 Make and CMake")
    c.code("make            # build flight_seq(.exe)\n"
           "make run        # build then run\n"
           "make clean      # remove build artefacts\n"
           "\n"
           "cmake -S . -B build && cmake --build build\n"
           "./build/flight_seq 3")
    c.p("The program takes one optional argument: the run length in seconds "
        "(default 3, from config/simulation.h).")

    # ---------------- 9 validation ----------------
    c.h1("9. Validation")
    c.h2("9.1 Test Plan")
    c.table([
        ["#", "Test", "Pass criterion"],
        ["V1", "Periodic release", "FlightSeq runs every 10 ms; missed_rel == 0"],
        ["V2", "Sensor ingest + framing + CRC", "crc > 0; counts consistent; bad frames discarded"],
        ["V3", "Staleness / hold-last-good", "stale or missing input holds last good; safe fallback"],
        ["V4", "Seqlock integrity", "no torn snapshots; timeouts == 0 on target"],
        ["V5", "Feedback fixed boundary", "new feedback applied only at frame % 20 == 0"],
        ["V6", "Watchdog gating", "kicks high, skips track fault windows"],
        ["V7", "Non-blocking TX", "busy/reject counted; the run always completes"],
        ["V8", "WCET", "seq_exec_us stays well below the 3000 us budget"],
    ], widths=[10 * mm, 45 * mm, None])
    c.h2("9.2 Observed Results")
    c.p("A representative three second host run:")
    c.code(
        "============== Flight Sequencer health report (dual-core) ==============\n"
        " sensor1  frames / crc / seq_gap / sync_err : 593 / 7 / 7 / 7\n"
        " sensor2  frames / crc / seq_gap / sync_err : 295 / 5 / 5 / 3\n"
        " flight   heartbeats / missed_rel / max_us  : 301 / 0 / 4\n"
        " actuator tx / tx_err / busy_cnt           : 292 / 2 / 7\n"
        " slow     heartbeats / exec_us / fb_stale   : 15 / 0 / 1\n"
        " supervisor heartbeats / tlm / tlm_busy    : 300 / 299 / 1\n"
        " watchdog kicks / skips                     : 287 / 13\n"
        " ---------------- seqlock + timing invariants ----------------\n"
        " seqlock reads / retries / timeouts         : 663 / 0 / 0\n"
        " last supervisor flag word                  : 0x00000000")
    c.p("Interpretation: frame counts match the periods (about 600 at 5 ms, about "
        "300 at 10 ms); the crc and seq_gap counts match at about 1 percent "
        "injected corruption because a discarded frame shows up as a "
        "sequence hole; the sequencer ran every release with zero missed "
        "releases and a maximum execution well under budget; actuator and "
        "telemetry transmits were non-blocking (busy counted, never a hang); the "
        "slow loop produced about 15 feedback cycles; the watchdog was kicked 287 "
        "times with 13 transient skips corresponding to fault windows; the "
        "seqlock recorded zero torn snapshots; and the final flag word is zero, "
        "meaning the system ended healthy. Numeric values vary between runs "
        "because faults are injected at random.")

    # ---------------- 10 improvements ----------------
    c.h1("10. Improvements over the Base Pseudocode")
    c.p("The assessment pseudocode is a strong starting point. The reference "
        "implementation keeps its architecture and corrects a few details.")
    c.table([
        ["#", "Issue in base pseudocode", "Fix in this implementation"],
        ["I1", "Supervisor flags F_NAV_CRC from a cumulative counter, so one CRC "
               "error latches the fault forever and the watchdog is never kicked again.",
               "Edge-triggered fault detection: compare against the previous cycle "
               "and flag only new faults; keep the watchdog guarding while healthy."],
        ["I2", "Reads FB_LEN (16) bytes into a structure that also holds cycle_id "
               "and activate_frame.",
               "Publishes/reads sizeof(FbMsg_t) so the control fields travel "
               "atomically with the 16-byte payload."],
        ["I3", "seq - last_seq - 1 with last_seq = 0 reports a bogus 255-frame gap on "
               "the first frame.",
               "Pre-load last_seq to 0xFF so the first frame is gap-free."],
        ["I4", "Simulator corrupts a frame then recomputes a matching CRC, so the "
               "CRC check never fails.",
               "Seal the CRC over the clean frame, then flip a payload byte."],
        ["I5", "act_busy / tlm_busy treated as latched faults.",
               "Reported as counters and used edge-triggered, matching real FDIR practice."],
    ], widths=[8 * mm, None, None])

    # ---------------- 11 traceability ----------------
    c.h1("11. Evaluation Traceability")
    c.table([
        ["Criterion", "How the design meets it", "Where"],
        ["Real-time determinism",
         "Isolated hard real-time core, timer release, DMA RX, wait-free writers, "
         "bounded readers, response-time analysis with about 6 ms slack, missed-release "
         "and overrun detection.",
         "Sections 4, 5; flight_sequencer.c"],
        ["RTOS fundamentals",
         "Notifications for events, counting notifications for periodic release, seqlock "
         "mailboxes for state, single-owner DMA for TX, no mutexes on the hard path.",
         "Sections 4.3, 6; bsp_api.h"],
        ["Multi-core competency",
         "Core 1 dedicated to the sequencer; four single-writer mailboxes as the only "
         "boundary; memory barriers; non-cacheable shared RAM; false-sharing control; "
         "local IRQ mask instead of the SMP kernel lock.",
         "Sections 4.1, 6; types.h, mailbox.h"],
        ["Engineering judgment",
         "Nine documented assumptions with WCET budgets and frame formats; stale-data "
         "policy; fixed-boundary feedback activation.",
         "Section 3.3; DESIGN_DECISIONS.md"],
        ["Design justification",
         "Quantified interrupt-vs-polling comparison and lock-free-vs-mutex rationale.",
         "Sections 4.4, 6.3"],
    ], widths=[32 * mm, None, 34 * mm])

    # ---------------- 12 porting ----------------
    c.h1("12. Porting and Integration")
    c.p("Only platform/host_bsp.c is host-specific. To move to a real target, "
        "re-implement include/bsp_api.h over your RTOS and vendor drivers; the "
        "application does not change.")
    c.table([
        ["BSP function", "FreeRTOS-SMP", "CMSIS-RTOS2"],
        ["BSP_TaskCreate", "xTaskCreateAffinitySet", "osThreadNew + affinity"],
        ["BSP_NotifySetBitsFromIsr", "xTaskNotifyFromISR (eSetBits)", "osThreadFlagsSet"],
        ["BSP_NotifyWaitBits", "xTaskNotifyWait", "osThreadFlagsWait"],
        ["BSP_NotifyGiveFromIsr", "vTaskNotifyGiveFromISR", "counting semaphore"],
        ["BSP_NotifyTake", "ulTaskNotifyTake", "osSemaphoreAcquire"],
        ["BSP_LocalIrqSave/Restore", "portSET_INTERRUPT_MASK (local core)", "__disable_irq region"],
        ["BSP_DmaRx/Tx", "vendor UART DMA", "vendor UART DMA"],
        ["BSP_WdtKick", "wdt_feed", "HAL_IWDG_Refresh"],
    ], widths=[42 * mm, None, None])
    c.p("Shared memory and memory ordering are critical: map shared RAM "
        "non-cacheable (or coherent), 64-byte align every mailbox and health "
        "block, and confirm the acquire/release fences map to DMB on ARM. Route "
        "UART interrupts to Core 0 and timer A to Core 1. Do not enable the "
        "watchdog until the supervisor is proven to kick it.")

    # ---------------- 13 conclusion ----------------
    c.h1("13. Conclusion")
    c.p("The Flight Sequencer demonstrates a defensible, certifiable hard "
        "real-time architecture: a dedicated compute core, hardware-driven "
        "release, DMA-based I/O, wait-free state exchange and lock-free fault "
        "observation, all with quantified margins and explicit failure "
        "behaviour. The accompanying implementation is not a diagram -- it "
        "builds and runs on Windows and Linux, exercises its safety paths under "
        "injected faults, and self-reports its health so the timing and "
        "synchronization claims can be observed directly.")

    # ---------------- appendix A ----------------
    c.pb()
    c.h1("Appendix A. Constants and Frame Format")
    c.table([
        ["Constant", "Value", "Meaning"],
        ["FRAME_US", "10000", "Nominal 10 ms flight frame"],
        ["SLOW_DIV", "20", "Slow task every 20th frame (200 ms)"],
        ["SENSOR1_PERIOD_US", "5000", "Sensor 1 period"],
        ["SENSOR2_PERIOD_US", "10000", "Sensor 2 period"],
        ["N1_LEN / N2_LEN", "32 / 54", "Sensor payload lengths (bytes)"],
        ["ACT_LEN / FB_LEN", "20 / 16", "Actuator command / feedback lengths"],
        ["FRAME_OVERHEAD", "6", "2 sync + 1 seq + 1 len + 2 crc"],
        ["BAUD_RATE", "1000000", "1 Mbaud, 8N1 (10 us/byte)"],
        ["NAV1_MAX_AGE_US", "7500", "1.5 periods staleness limit"],
        ["NAV2_MAX_AGE_US", "15000", "1.5 periods staleness limit"],
        ["SEQ_BUDGET_US", "3000", "Flight sequencer WCET budget"],
        ["MBX_MAX_RETRY", "3", "Bounded seqlock reader retries"],
    ], widths=[45 * mm, 26 * mm, None])
    c.code("Frame:  [0xAA][0x55][seq][len][ payload ... ][crc_lo][crc_hi]\n"
           "CRC-16/CCITT-FALSE over every byte except the two CRC bytes.")

    # ---------------- appendix B ----------------
    c.h1("Appendix B. Board-Support API Reference")
    c.table([
        ["Function", "Purpose"],
        ["BSP_ClockInit / BSP_HwTimeUs/Ms", "Initialise and read the shared 1 us timebase"],
        ["BSP_TaskCreate", "Create a statically allocated task pinned to a core"],
        ["BSP_NotifySetBitsFromIsr / BSP_NotifyWaitBits", "Bit notification for events"],
        ["BSP_NotifyGiveFromIsr / BSP_NotifyTake", "Counting notification for periodic release"],
        ["BSP_LocalIrqSave / BSP_LocalIrqRestore", "Bounded per-core interrupt mask"],
        ["BSP_TimerSetIsr / StartPeriodic / ClearIrq", "Hardware timer release"],
        ["BSP_Rs422Init / UartSetIdleIsr / UartEnableIdleIrq", "UART + idle-line IRQ setup"],
        ["BSP_UartStatus / ClearIdle / ClearErr", "Status and flag handling"],
        ["BSP_DmaRxCircular / RingBuffer / RingSize / DmaWriteIndex", "Circular RX DMA"],
        ["BSP_DmaTxStart / DmaTxBusy", "One-shot TX DMA with polled completion"],
        ["BSP_WdtKick", "Watchdog feed (supervisor only)"],
        ["BSP_RunForSeconds", "Host-only: run the simulator for N seconds"],
    ], widths=[70 * mm, None])

    # ---------------- appendix C ----------------
    c.h1("Appendix C. Repository Layout")
    c.code("mission_computer/\n"
           "  CMakeLists.txt, Makefile, README.md\n"
           "  config/simulation.h\n"
           "  include/  types.h  mailbox.h  bsp_api.h  flight_sequencer.h\n"
           "  platform/ host_bsp.c\n"
           "  src/      main.c  modules/flight_sequencer.c\n"
           "  scripts/  generate_architecture_diagrams.py\n"
           "            generate_timing_plots.py  generate_report.py\n"
           "  docs/     ARCHITECTURE.md  DESIGN_DECISIONS.md  VALIDATION.md\n"
           "            TRACEABILITY.md  INTEGRATION.md  figures/  figures_bw/\n"
           "            Flight_Sequencer_Report.pdf")

    # ---------------- appendix D ----------------
    c.h1("Appendix D. Glossary")
    c.table([
        ["Term", "Definition"],
        ["Seqlock", "Sequence-lock; a lock-free data exchange where the writer is wait-free "
                    "and the reader retries on overlap."],
        ["Wait-free", "An operation guaranteed to complete in a bounded number of steps "
                      "regardless of other threads."],
        ["Counting notification", "A task signal that accumulates a count, so missed releases "
                                  "can be detected."],
        ["Edge-triggered fault", "A fault flagged only at the transition (new event), rather "
                                 "than for as long as a cumulative counter is non-zero."],
        ["WCET", "Worst-Case Execution Time."],
        ["False sharing", "Performance loss when independent variables share a cache line; "
                          "avoided by 64-byte alignment."],
    ], widths=[35 * mm, None])

    return c.f


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs",
                                                  "Flight_Sequencer_Report.pdf"))
    args = ap.parse_args()

    to_grayscale()
    styles = make_styles()
    story = build_story(styles)

    doc = ReportDoc(args.out, styles, pagesize=A4,
                    leftMargin=18 * mm, rightMargin=18 * mm,
                    topMargin=20 * mm, bottomMargin=16 * mm,
                    title="Flight Sequencer — Dual-Core RTOS Firmware Design",
                    author="GSBiradar")
    doc.multiBuild(story)
    print("wrote", args.out)


if __name__ == "__main__":
    main()

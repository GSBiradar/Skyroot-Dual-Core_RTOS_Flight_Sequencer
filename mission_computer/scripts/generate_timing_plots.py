#!/usr/bin/env python3
"""
generate_timing_plots.py

Reproduce the assessment's timing figures from its own model (not target
measurements). Run:

    python scripts/generate_timing_plots.py [--out docs/figures]

Produces:
  1. rx_interrupt_rate.png        - RX strategy: ISR rate + CPU cost
  2. wire_time_vs_period.png      - frame wire time vs period budget
  3. core_utilisation.png         - Core 0 / Core 1 WCET load
  4. response_vs_deadline.png     - worst-case response vs deadline
  5. sample_to_actuator.png       - worst-case latency budget per sensor

All numbers come from the assessment assumptions (1 Mbaud, 10 us/byte,
6-byte frame overhead) and its WCET budgets.
"""
import argparse
import os

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "matplotlib is required:  pip install matplotlib"
    ) from exc

# ---- model constants (assessment assumption A4/A5) ----
BAUD = 1_000_000
US_PER_BYTE = 10_000_000 / BAUD / 1e6 * 1e6  # 10 us/byte
OVERHEAD = 6

# port: (payload bytes, period ms)
PORTS = {
    "Sensor 1 (in)":  (32, 5.0),
    "Sensor 2 (in)":  (54, 10.0),
    "Actuator (out)": (20, 10.0),
    "Telemetry (out)": (64, 10.0),
}


def wire_ms(payload):
    return (payload + OVERHEAD) * US_PER_BYTE / 1000.0


def fig_rx_interrupt_rate(outdir):
    strategies = ["Per-byte\ninterrupt", "Polling", "DMA +\nidle-line IRQ"]
    s1_bytes, s1_period = PORTS["Sensor 1 (in)"]
    s2_bytes, s2_period = PORTS["Sensor 2 (in)"]

    # interrupts per second for both sensors during their bursts
    per_byte_s = (s1_bytes + OVERHEAD) / (s1_period / 1000.0) + \
                 (s2_bytes + OVERHEAD) / (s2_period / 1000.0)
    frame_s = 1 / (s1_period / 1000.0) + 1 / (s2_period / 1000.0)

    rates = [per_byte_s, frame_s, frame_s]           # polling == frame poll
    cpu = [1.5e-6 * per_byte_s * 100, 0.07 * 100, 0.0005 * 100]  # rough %

    fig, ax1 = plt.subplots(figsize=(7, 4.2))
    bars = ax1.bar(strategies, rates, color=["#c0392b", "#e67e22", "#27ae60"])
    ax1.set_ylabel("interrupts / poll events per second")
    ax1.set_title("RX strategy: event rate and CPU cost")
    for b, r in zip(bars, rates):
        ax1.text(b.get_x() + b.get_width() / 2, r, f"{int(r)}",
                 ha="center", va="bottom", fontsize=9)

    ax2 = ax1.twinx()
    ax2.plot(strategies, cpu, "k--o", linewidth=1.5)
    ax2.set_ylabel("approx. CPU cost (%)")
    for x, c in zip(strategies, cpu):
        ax2.text(x, c, f"{c:.2f}%", ha="center", va="bottom", fontsize=8, color="k")

    fig.tight_layout()
    path = os.path.join(outdir, "rx_interrupt_rate.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def fig_wire_vs_period(outdir):
    names = list(PORTS.keys())
    wtimes = [wire_ms(PORTS[n][0]) for n in names]
    periods = [PORTS[n][1] for n in names]
    pct = [100 * w / p for w, p in zip(wtimes, periods)]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = range(len(names))
    ax.bar([i - 0.2 for i in x], wtimes, width=0.4,
           label="wire time (ms)", color="#2980b9")
    ax.bar([i + 0.2 for i in x], periods, width=0.4,
           label="period budget (ms)", color="#bdc3c7")
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=12, ha="right", fontsize=8)
    ax.set_ylabel("time (ms)")
    ax.set_title("Frame wire time vs. period budget (why DMA, not polling)")
    for i, p in zip(x, pct):
        ax.text(i, max(wtimes[i], periods[i]), f"{p:.0f}%", ha="center",
                va="bottom", fontsize=8)
    ax.legend()
    fig.tight_layout()
    path = os.path.join(outdir, "wire_time_vs_period.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def fig_core_utilisation(outdir):
    # Core 0: ISRs+ingest ~1.1%, supervisor 1.5%, slow 20%  -> ~23%
    # Core 1: FlightSeq 3ms/10ms = 30%
    labels = ["Core 0", "Core 1"]
    used = [23.0, 30.0]
    free = [100 - u for u in used]

    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.barh(labels, used, color="#27ae60", label="used")
    ax.barh(labels, free, left=used, color="#ecf0f1", label="headroom")
    for i, u in enumerate(used):
        ax.text(u / 2, i, f"{u:.0f}%", ha="center", va="center", color="white",
                fontweight="bold")
        ax.text(u + (100 - u) / 2, i, f"{100 - u:.0f}% free", ha="center",
                va="center", fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("utilisation (%)")
    ax.set_title("CPU utilisation by WCET budget")
    ax.legend(loc="lower right")
    fig.tight_layout()
    path = os.path.join(outdir, "core_utilisation.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def fig_response_vs_deadline(outdir):
    activities = ["Sensor ingest", "FlightSeq", "Supervisor", "SlowComp"]
    response = [0.1, 3.9, 0.2, 45.0]     # ms
    deadline = [5.0, 10.0, 10.0, 200.0]  # ms

    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = range(len(activities))
    ax.bar([i - 0.2 for i in x], response, width=0.4,
           label="worst-case response (ms)", color="#8e44ad")
    ax.bar([i + 0.2 for i in x], deadline, width=0.4,
           label="deadline (ms)", color="#bdc3c7")
    ax.set_xticks(list(x))
    ax.set_xticklabels(activities, fontsize=9)
    ax.set_ylabel("time (ms)")
    ax.set_yscale("log")
    ax.set_title("Worst-case response vs. deadline (log scale)")
    for i, (r, d) in enumerate(zip(response, deadline)):
        ax.text(i - 0.2, r, f"{r}", ha="center", va="bottom", fontsize=8)
        ax.text(i + 0.2, d, f"{d}", ha="center", va="bottom", fontsize=8)
    ax.legend()
    fig.tight_layout()
    path = os.path.join(outdir, "response_vs_deadline.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def fig_sample_to_actuator(outdir):
    # Sensor 1: data age <5.5 ms + sequencer 3.9 ms + TX 0.26 ms ~ 9.6 ms
    # Sensor 2: data age <10.7 ms + sequencer 3.9 ms + TX 0.26 ms ~ 14.9 ms
    labels = ["Sensor 1", "Sensor 2"]
    data_age = [5.5, 10.7]
    seq = [3.9, 3.9]
    tx = [0.26, 0.26]

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    x = range(len(labels))
    ax.bar(labels, data_age, color="#3498db", label="sensor data age")
    ax.bar(labels, seq, bottom=data_age, color="#e74c3c", label="sequencer response")
    ax.bar(labels, tx, bottom=[a + s for a, s in zip(data_age, seq)],
           color="#f39c12", label="actuator TX")
    for i, (a, s, t) in enumerate(zip(data_age, seq, tx)):
        ax.text(i, a + s + t, f"{a + s + t:.1f} ms", ha="center", va="bottom",
                fontsize=9, fontweight="bold")
    ax.set_ylabel("latency (ms)")
    ax.set_title("Worst-case sample-to-actuator latency budget")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(outdir, "sample_to_actuator.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("docs", "figures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    made = [
        fig_rx_interrupt_rate(args.out),
        fig_wire_vs_period(args.out),
        fig_core_utilisation(args.out),
        fig_response_vs_deadline(args.out),
        fig_sample_to_actuator(args.out),
    ]
    for m in made:
        print("wrote", m)


if __name__ == "__main__":
    main()

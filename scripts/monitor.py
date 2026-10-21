#!/usr/bin/env python3
"""Record per-step solver data and display a live or saved monitoring figure."""
import argparse
import csv
import math
import os
from pathlib import Path
import re
import tempfile

NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
COLUMNS = ["Time", "deltaT", "Co_mean_before_step", "Co_max_before_step",
           "Ux_initial", "Uy_initial", "p_initial", "Ux_final", "Uy_final",
           "p_final", "Cd", "Cl"]


class Recorder:
    def __init__(self, destination, initial_dt):
        self.file = open(destination, "w", newline="", buffering=1)
        self.writer = csv.DictWriter(self.file, fieldnames=COLUMNS)
        self.writer.writeheader()
        self.pending = {"deltaT": initial_dt}
        self.row = None
        self.steps = 0

    def feed(self, line):
        match = re.match(rf"Courant Number mean:\s*({NUMBER})\s+max:\s*({NUMBER})", line)
        if match:
            self.pending.update(Co_mean_before_step=match[1], Co_max_before_step=match[2])
        match = re.match(rf"deltaT\s*=\s*({NUMBER})", line)
        if match:
            self.pending["deltaT"] = match[1]
        match = re.match(rf"Time\s*=\s*({NUMBER})\s*(?:s)?\s*$", line)
        if match:
            self.finish_step()
            self.row = dict(self.pending, Time=match[1])
        if self.row is None:
            return
        match = re.search(rf"Solving for (Ux|Uy|p), Initial residual = ({NUMBER}), "
                          rf"Final residual = ({NUMBER})", line)
        if match:
            self.row.setdefault(match[1] + "_initial", match[2])
            self.row[match[1] + "_final"] = match[3]
        match = re.match(rf"\s*(Cd|Cl)\s*=\s*({NUMBER})\s*$", line)
        if match:
            self.row[match[1]] = match[2]
        # Foundation 14 executes force function objects after ExecutionTime.
        # Commit only after the last force-coefficient output for this step.
        if re.match(r"\s*Cl\(r\)\s*=", line):
            self.finish_step()

    def finish_step(self):
        if self.row is not None:
            missing = set(COLUMNS) - self.row.keys()
            if missing:
                raise RuntimeError(f"监控数据缺少 {sorted(missing)}，时间 {self.row['Time']}")
            if not all(math.isfinite(float(value)) for value in self.row.values()):
                raise RuntimeError("监控数据中出现非有限值")
            self.writer.writerow(self.row)
            self.file.flush()
            self.steps += 1
            self.row = None

    def close(self, successful=False):
        try:
            if successful:
                self.finish_step()
        finally:
            self.file.close()


def main():
    parser = argparse.ArgumentParser(description="实时显示残差、Courant 数及升阻力系数")
    parser.add_argument("--save", metavar="PNG", help="保存静态图片并退出，不打开窗口")
    parser.add_argument("--interval", type=float, default=1, help="实时刷新间隔，秒")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("刷新间隔必须大于零")
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / f"re200-mpl-{os.getuid()}"))
    import matplotlib
    if args.save:
        matplotlib.use("Agg")
    else:
        matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    fig.canvas.manager.set_window_title("Re200 live monitor")
    definitions = [(axes[0], ["Ux_initial", "Uy_initial", "p_initial"], "Initial residual"),
                   (axes[1], ["Co_mean_before_step", "Co_max_before_step"], "Courant (before step)"),
                   (axes[2], ["Cd", "Cl"], "Force coefficient")]
    plots = {}
    for axis, names, label in definitions:
        for name in names:
            plots[name], = axis.plot([], [], label=name)
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)
        axis.legend(loc="upper right")
    axes[0].set_yscale("log")
    axes[-1].set_xlabel("Physical time [s]")
    fig.tight_layout()
    data_path = Path(__file__).resolve().parents[1] / "monitoring.csv"

    def update(_=None):
        try:
            with data_path.open() as stream:
                # A concurrent writer may be in the middle of its last row.
                rows = [row for row in csv.DictReader(stream)
                        if all(row.get(name) not in (None, "") for name in COLUMNS)]
            times = [float(row["Time"]) for row in rows]
            for name, plot in plots.items():
                values = [float(row[name]) for row in rows]
                if name.endswith("_initial"):
                    values = [max(value, 1e-30) for value in values]
                plot.set_data(times, values)
            for axis in axes:
                axis.relim()
                axis.autoscale_view()
            fig.suptitle(f"Re200: {len(rows)} completed steps")
        except FileNotFoundError:
            fig.suptitle("Waiting for monitoring.csv ...")

    update()
    if args.save:
        if not data_path.is_file():
            parser.error("尚无 monitoring.csv，请先启动计算")
        fig.savefig(args.save, dpi=150)
    else:
        animation = FuncAnimation(fig, update, interval=args.interval * 1000,
                                  cache_frame_data=False)
        plt.show()


if __name__ == "__main__":
    main()

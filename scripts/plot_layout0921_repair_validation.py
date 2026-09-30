#!/usr/bin/env python3
"""Render the Layout0921 report from saved runs; never replay or modify inputs.

Requires Matplotlib, NumPy and Pillow. Refuses an existing output directory.
"""
import argparse
import csv
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PALETTE = ["#0072B2", "#007F6D", "#7F4283", "#B35B00"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Sources:
    def __init__(self, root):
        self.root = root
        self.files = {}
        self.cache = {}

    def path(self, run, name):
        path = self.root / run / name
        if not path.is_file():
            raise ValueError(f"Missing saved input: {path}")
        self.files[str(path.resolve())] = sha(path)
        return path

    def read(self, run, name):
        key = (run, name)
        if key not in self.cache:
            path = self.path(run, name)
            if path.suffix == ".json":
                self.cache[key] = json.loads(path.read_text())
            else:
                with path.open(newline="") as stream:
                    self.cache[key] = list(csv.DictReader(stream))
        return self.cache[key]

    def frames(self, run):
        rows = self.read(run, "frames.csv")
        summary = self.read(run, "summary.json")
        if len(rows) != summary["processed_frames"]:
            raise ValueError(f"Incomplete saved frame table: {run}")
        if [int(row["frame"]) for row in rows] != list(range(len(rows))):
            raise ValueError(f"Missing/repeated frame index: {run}")
        times = [int(row["corrected_ns"]) for row in rows]
        if not times or any(a >= b for a, b in zip(times, times[1:])):
            raise ValueError(f"Invalid saved frame times: {run}")
        return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--experiment-root", type=Path,
                    default=ROOT / "results/repair_20260930T142226")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--font", type=Path,
                    default=Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"))
    args = ap.parse_args()
    out = (args.output or args.experiment_root / "report_figures").resolve()
    if out.exists():
        ap.error(f"Output already exists: {out}")
    if not args.font.is_file():
        ap.error(f"Chinese font is unavailable: {args.font}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.font_manager import FontProperties, fontManager
    from matplotlib.lines import Line2D
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Patch
    from PIL import Image

    fontManager.addfont(str(args.font))
    font_name = FontProperties(fname=args.font).get_name()
    style = {
        "font.family": font_name, "font.size": 11, "axes.titlesize": 13,
        "axes.labelsize": 11, "xtick.labelsize": 10, "ytick.labelsize": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.unicode_minus": False, "figure.facecolor": "white",
        "axes.facecolor": "white", "savefig.facecolor": "white",
        "svg.fonttype": "path", "pdf.fonttype": 42,
    }
    sources = Sources(args.experiment_root.resolve())
    out.mkdir(parents=True)
    outputs = []
    series_data = {}

    def export(fig, name, details):
        for ext in ["png", "svg"]:
            path = out / f"{name}.{ext}"
            fig.savefig(path, dpi=180, transparent=False)
            outputs.append({"file": str(path), "sha256": sha(path), **details})
        plt.close(fig)

    with plt.rc_context(style):
        # Raw runs are shown separately, without a mean or confidence interval.
        experiments = [
            ("E0 原配置", ["E0_original"]),
            ("E0 有效射线（3 次）", [f"E0_rays_{i}" for i in range(1, 4)]),
            ("E1 四路投影修复", ["E1_level3_full"]),
            ("E2 观测 / 索引修复", ["E2_full"]),
            ("E3 前双目几何匹配", ["E3_front_full"]),
            ("E4 前双目 / 30 点", ["E4_30_full"]),
            ("E4 前双目 / 50 点", ["E4_50_full"]),
            ("E5 加 cam1–cam3", ["E5_13_full"]),
            ("E5 再加 cam0–cam2", ["E5_02_full"]),
            ("E6 小角积分 / 原门槛", ["E6_kernel_legacy_full"]),
            ("E6 小角积分 / 三对种子", ["E6_kernel_rig_full"]),
            ("E6 重置边界 / 原门槛", ["E6_time_legacy_full"]),
            ("E6 重置边界 / 三对种子", ["E6_time_rig_full"]),
            ("V3 最终（3 次）", [f"E7_v3_debug_{i}" for i in range(1, 4)]),
        ]
        fig, axes = plt.subplots(1, 2, figsize=(13, 8.8), layout="constrained",
                                 gridspec_kw={"width_ratios": [1.6, 1]})
        fig.suptitle("开发包：逐阶段真实回放指标", fontsize=16)
        metric_rows = []
        for y, (label, runs) in enumerate(experiments):
            color = PALETTE[1] if label.startswith("V3") else PALETTE[0]
            values = []
            for i, run in enumerate(runs):
                s = sources.read(run, "summary.json")
                init = s["first_imu_initialized_frame"]
                score = 100 * s["post_init_ok_ratio"] if init is not None else None
                offset = (i - (len(runs) - 1) / 2) * .16
                if score is not None:
                    axes[0].scatter(score, y + offset, marker=["o", "s", "^"][i],
                                    s=45, color=color, edgecolors="black", linewidths=.4)
                    axes[1].scatter(init, y + offset, marker=["o", "s", "^"][i],
                                    s=45, color=PALETTE[3] if init > 299 else color,
                                    edgecolors="black", linewidths=.4)
                metric_rows.append({"label": label, "run": run, "imu_init_frame": init,
                                    "post_init_ok_percent": score})
                values.append((score, init))
            if values[0][0] is None:
                for ax in axes:
                    ax.text(.5, y, "未初始化；指标未定义", transform=ax.get_yaxis_transform(),
                            ha="center", va="center", color="#606870", fontsize=9)
            else:
                for panel in range(2):
                    raw = [value[panel] for value in values]
                    if len(set(raw)) == 1:
                        suffix = f" ×{len(raw)}" if len(raw) > 1 else ""
                        text = (f"{raw[0]:.1f}%" if panel == 0 else str(raw[0])) + suffix
                        x = raw[0] - 1.6 if panel == 0 and raw[0] > 98 else raw[0] + (2 if panel == 0 else 7)
                        axes[panel].text(x, y, text, ha="right" if panel == 0 and raw[0] > 98 else "left",
                                         va="center", fontsize=9)
                    else:
                        for i, value in enumerate(raw):
                            axes[panel].text(value + 2, y + (i - 1) * .19,
                                             f"{value:.1f}%" if panel == 0 else str(value), fontsize=9)
        for ax in axes:
            ax.set_ylim(len(experiments) - .5, -.8)
            ax.set_yticks(range(len(experiments)))
            ax.grid(axis="x", color="#DDE1E5", linewidth=.6)
            ax.set_axisbelow(True)
        axes[0].set_yticklabels([x[0] for x in experiments])
        axes[1].set_yticklabels([])
        axes[0].set_xlim(0, 105)
        axes[0].set_xticks([0, 25, 50, 75, 100])
        axes[0].set_xlabel("IMU 初始化后的 OK 比例（%）")
        axes[0].axvline(95, color="#202020", linestyle="--", linewidth=1)
        axes[0].set_title("连续性门槛：≥95%")
        axes[1].set_xlim(0, 370)
        axes[1].set_xlabel("首次 IMU 初始化帧（从 0 开始）")
        axes[1].axvline(299, color="#202020", linestyle="--", linewidth=1)
        axes[1].set_title("开发包期限：前 300 组")
        fig.supxlabel("每个点是一次完整 1195 帧运行；重复点纵向错开，无均值 / 置信区间。", fontsize=10)
        series_data["experiment_metrics"] = metric_rows
        export(fig, "01_experiment_metrics", {"transform": "saved summaries; raw replicates; no smoothing"})

        representatives = [("开发包", "E7_v3_debug_1"), ("独立包", "E7_v3_validation01_1")]
        # Matching counts are before cross-pair merge; seeds are already deduplicated.
        fig, axes = plt.subplots(2, 1, figsize=(13, 7.8), layout="constrained", sharex=True)
        support_data = {}
        for ax, (label, run) in zip(axes, representatives):
            matches = sources.read(run, "match_stages.csv")
            diagnostics = sources.read(run, "diagnostics.csv")
            values = {}
            for i, pair in enumerate([(0, 1), (1, 3), (0, 2)]):
                rows = {int(x["frame"]): x for x in matches if (int(x["a"]), int(x["b"])) == pair}
                accepted = [int(rows[j]["accepted"]) for j in range(128)]
                values[f"cam{pair[0]}–cam{pair[1]}"] = accepted
                ax.plot(range(128), accepted, color=PALETTE[i], linestyle=["-", "--", "-."][i],
                        marker=["o", "s", "^"][i], markevery=16, markersize=4, linewidth=1.1,
                        label=f"cam{pair[0]}–cam{pair[1]} 三角化通过")
            by_frame = {int(x["frame"]): x for x in diagnostics}
            seeds = [int(by_frame[j]["rig_seeds"]) for j in range(128)]
            ax.plot(range(128), seeds, color="#202020", linewidth=1.8,
                    label="合并 / 去重后的独立种子")
            ax.axhline(30, color="#606870", linestyle=":", linewidth=1.4, label="30 点门槛（另需空间覆盖）")
            ax.set(title=f"{label}：前 128 帧几何支持", ylabel="每帧对应 / 种子数量", xlim=(0, 127))
            ax.set_ylim(bottom=0)
            ax.grid(color="#E4E7EA", linewidth=.6)
            support_data[run] = {"pairs": values, "independent_seeds": seeds}
        axes[0].legend(ncol=3, fontsize=9, loc="upper left")
        axes[1].set_xlabel("输入帧号（0–127）")
        series_data["matching_support"] = support_data
        export(fig, "02_match_support", {"transform": "first 128 frames; native counts; no smoothing"})

        # Original diagnostic pixels are copied byte-for-byte, not redrawn.
        for run, frame, name in [("E7_v3_debug_1", 136, "03_debug_initialization.jpg"),
                                 ("E7_v3_validation01_1", 727, "04_validation_initialization.jpg")]:
            source = sources.path(run, f"overlays/frame_{frame}.jpg")
            target = out / name
            shutil.copyfile(source, target)
            assert sha(source) == sha(target)
            outputs.append({"file": str(target), "sha256": sha(target),
                            "source": str(source), "transform": "byte-for-byte copy; no image adjustment"})

        # Discrete state cells cover every input frame, including failed startup.
        fig = plt.figure(figsize=(13, 8.1), layout="constrained")
        grid = fig.add_gridspec(3, 1, height_ratios=[1, 1, .2])
        axes = [fig.add_subplot(grid[0]), fig.add_subplot(grid[1])]
        legend_ax = fig.add_subplot(grid[2]); legend_ax.axis("off")
        states = {0: ("尚无图像", "#BAC2C9", ".."), 1: ("未初始化", "#BAC2C9", ".."),
                  2: ("OK", PALETTE[0], ""), 3: ("RECENTLY_LOST", "#D55E00", "///"),
                  4: ("LOST", PALETTE[2], "xx")}
        timeline_data = {}
        for ax, label, baseline, prefix in [
                (axes[0], "开发包", "E0_rays_1", "E7_v3_debug"),
                (axes[1], "独立包", "E7_validation01_2", "E7_v3_validation01")]:
            runs = [baseline] + [f"{prefix}_{i}" for i in range(1, 4)]
            ticks = []
            for index, run in enumerate(runs):
                rows = sources.frames(run)
                t = np.asarray([(int(x["corrected_ns"]) - int(rows[0]["corrected_ns"])) * 1e-9 for x in rows])
                dt = float(np.median(np.diff(t)))
                state = [int(x["state"]) for x in rows]
                if set(state) - states.keys():
                    raise ValueError(f"Unsupported saved state: {run}")
                y = 3 - index
                start = 0
                for stop in range(1, len(state) + 1):
                    if stop == len(state) or state[stop] != state[start]:
                        right = t[stop] if stop < len(state) else t[-1] + dt
                        _, color, hatch = states[state[start]]
                        ax.broken_barh([(t[start], right - t[start])], (y - .25, .5),
                                       facecolors=color, edgecolors="#505860", linewidth=.25, hatch=hatch)
                        start = stop
                init = next((i for i, x in enumerate(rows) if x["imu_initialized"] == "1"), None)
                if init is not None:
                    ax.scatter(t[init], y + .38, marker="v", color="black", s=35, zorder=5)
                    ax.annotate(f"IMU：{init} 帧", (t[init], y + .38), xytext=(5, 3),
                                textcoords="offset points", fontsize=9)
                resets = [i for i in range(1, len(rows)) if int(rows[i]["resets"]) > int(rows[i - 1]["resets"])]
                ax.scatter(t[resets], [y - .39] * len(resets), marker="|", s=35, color="black", linewidths=.8)
                ok = sum(x == 2 for x in state)
                run_label = ("E0 射线基线" if label == "开发包" else "V1 失败对照") if index == 0 else f"V3 重复 {index}"
                ticks.append(f"{run_label}  全窗口 {100*ok/len(state):.2f}%")
                timeline_data[run] = {"frames": len(rows), "ok_frames": ok, "imu_init_frame": init,
                                      "reset_frames": resets, "duration_seconds": float(t[-1])}
            ax.set_yticks([3, 2, 1, 0], ticks)
            ax.set_ylim(-.55, 3.85)
            ax.set_xlim(0, t[-1] + dt)
            ax.set_title(f"{label}：完整输入状态（包含启动阶段）", loc="left")
            ax.set_xlabel("从该包首帧起算的校正图像时间（秒）")
            ax.grid(axis="x", color="#DDE1E5", linewidth=.6)
        handles = [Patch(facecolor=states[s][1], edgecolor="#505860", hatch=states[s][2], label=states[s][0])
                   for s in [1, 2, 3, 4]]
        handles += [Line2D([], [], color="black", marker="v", linestyle="none", label="首次 IMU 初始化"),
                    Line2D([], [], color="black", marker="|", linestyle="none", label="重置计数增加")]
        legend_ax.legend(handles=handles, ncol=3, loc="center", fontsize=10)
        series_data["tracking_timeline"] = timeline_data
        export(fig, "05_tracking_timeline", {"transform": "all saved frame states; contiguous state intervals; no trimming"})

        # Camera observations and distinct point counts are intentionally distinct.
        fig, axes = plt.subplots(2, 1, figsize=(13, 7.5), layout="constrained")
        camera_data = {}
        for ax, (label, run) in zip(axes, representatives):
            rows = sources.frames(run)
            diag = sources.read(run, "diagnostics.csv")
            if len(diag) != len(rows):
                raise ValueError(f"Diagnostic/frame length mismatch: {run}")
            first = sources.read(run, "summary.json")["first_imu_initialized_frame"]
            t = np.asarray([(int(x["corrected_ns"]) - int(rows[0]["corrected_ns"])) * 1e-9 for x in rows[first:]])
            camera_data[run] = {"first_frame": first, "optimized_observations": {}}
            for c in range(4):
                counts = np.asarray([int(x[f"local_after_cam{c}"]) for x in diag[first:]], dtype=float)
                camera_data[run]["optimized_observations"][f"cam{c}"] = counts.tolist()
                counts[counts < 0] = np.nan  # unexecuted stages are gaps, not zero observations
                ax.plot(t, counts, color=PALETTE[c], linestyle=["-", "--", "-.", ":"][c],
                        linewidth=1.05, label=f"cam{c} 优化后观测")
            unique = [int(x["unique_inliers"]) for x in diag[first:]]
            ax.plot(t, unique, color="#202020", linewidth=1.7, linestyle=(0, (5, 2)), label="帧末独立地图内点")
            camera_data[run]["unique_inliers"] = unique
            ax.set(title=f"{label}：IMU 初始化后（第 {first} 帧起）", ylabel="每帧数量", xlim=(t[0], t[-1]))
            ax.set_ylim(bottom=0)
            ax.grid(color="#E4E7EA", linewidth=.6)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, ncol=3, fontsize=9, loc="outside upper center")
        axes[1].set_xlabel("从该包首帧起算的校正图像时间（秒）")
        series_data["camera_support"] = camera_data
        export(fig, "06_camera_support", {"transform": "rows from first IMU initialization; negative stage counts retained as gaps; no smoothing"})

        # This is a projection of exported poses, not a ground-truth accuracy plot.
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.8), layout="constrained")
        trajectory_data = {}
        for ax, (label, run) in zip(axes, representatives):
            path = sources.path(run, "trajectory_body.txt")
            data = np.asarray([[float(v) for v in line.split()] for line in path.read_text().splitlines()
                               if line.strip() and not line.startswith("#")])
            if data.ndim != 2 or data.shape[1] != 8 or not np.isfinite(data).all() or not np.all(np.diff(data[:, 0]) > 0):
                raise ValueError(f"Invalid exported trajectory: {path}")
            step = np.diff(data[:, 0])
            gap = step > 1.5 * np.median(step)
            segments = np.stack([data[:-1, 1:3], data[1:, 1:3]], axis=1)
            ax.add_collection(LineCollection(segments[~gap], colors="#A0A7AE", linewidths=.7))
            ax.scatter(data[:, 1], data[:, 2], s=5, color=PALETTE[0], alpha=.9, label="导出位姿")
            ax.scatter(*data[0, 1:3], s=85, marker="^", color=PALETTE[1], edgecolor="black", linewidth=.5, label="起点")
            ax.scatter(*data[-1, 1:3], s=110, marker="*", color=PALETTE[3], edgecolor="black", linewidth=.5, label="终点")
            ax.set(title=f"{label}：最大地图轨迹（{len(data)} 行）", xlabel="参考系 X（m）", ylabel="参考系 Y（m）")
            ax.set_aspect("equal", adjustable="datalim")
            ax.autoscale_view()
            ax.margins(.1)
            ax.grid(color="#E4E7EA", linewidth=.6)
            ax.legend(fontsize=9, loc="best")
            trajectory_data[run] = {"rows": len(data), "large_time_gaps_not_connected": int(gap.sum()),
                                    "reference": "largest map first keyframe body origin; XY projection"}
        fig.supxlabel("每段使用自己的参考系；没有 mocap / 真值对齐，不能据此判断绝对精度。", fontsize=10)
        series_data["trajectory_xy"] = trajectory_data
        export(fig, "07_trajectory_xy", {"transform": "all exported XY positions; equal axis scale; large temporal gaps are not joined"})

    (out / "figure_data.json").write_text(json.dumps(series_data, ensure_ascii=False, indent=2) + "\n")
    for item in outputs:
        path = Path(item["file"])
        if path.suffix in [".png", ".jpg"]:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                item.update(width=im.width, height=im.height, mode=im.mode)
    manifest = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "experiment_root": str(sources.root), "generator": str(Path(__file__).resolve()),
        "generator_sha256": sha(Path(__file__)), "python": sys.version,
        "versions": {"matplotlib": matplotlib.__version__, "numpy": np.__version__, "pillow": Image.__version__},
        "font": str(args.font), "input_sha256": sources.files, "outputs": outputs,
        "methods": {"replicates": "raw runs, no uncertainty estimate",
                    "smoothing": "none", "native_images": "unmodified byte-for-byte copies",
                    "representatives": "fixed first V3 repeat; no best-run selection",
                    "timeline_baselines": "debug E0_rays_1; independent complete failed v1 repeat 2",
                    "accuracy": "no ground-truth comparison"},
    }
    (out / "figure_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Generated 5 statistical plots + 2 native diagnostic images: {out}")


if __name__ == "__main__":
    main()

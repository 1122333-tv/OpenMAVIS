# OpenMAVIS 四目 VIO 与轨迹对比流水线使用说明

本入口复用来源 run 的配组图像、标定和参考轨迹，不执行 Basalt/OKVIS2，也不重新配组。支持 Basalt 旧目录及 inputs/outputs 目录布局；OKVIS2 支持 `okvis-vio/version: 2`。实现计划与实测结果分别见同目录的 `openmavis_vio_comparison_pipeline_plan.md`、`openmavis_vio_comparison_pipeline_validation.md`。

## 1. 构建与 Python 环境

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
JOBS=4 bash scripts/build_vio.sh
```

默认生成 `build-vio/Examples/Multi-Inertial/multi_inertial_prepared`，同时编译原 `multi_inertial_euroc` 和回归目标。词典存在时不重复解压。`OUTPUT_ROOT`、`BUILD_DIR` 可覆盖隔离输出与 CMake 缓存目录；流水线要求构建目录内存在脚本保存的 `build_provenance.json`，并核对 C++ 源码与构建快照。

本机已验证 Python 3.12 环境：

```bash
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
"$vio_python" scripts/run_vio_pipeline.py --help
```

在其他环境，可用 Python 3.12 建立独立环境后安装 `scripts/requirements-vio.txt`。依赖版本是本轮真实环境的记录，不代表最新版本。无 GUI 运行使用 Agg；evo GUI 使用 QtAgg/PyQt6。

## 2. 从 Basalt run 运行

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
"$vio_python" scripts/run_vio_pipeline.py \
  --basalt-run /home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b \
  --run-name basalt_vio
```

默认无 GUI、离线处理全部帧。输出位于 `OpenMAVIS/results/<数据集名>/run_<时间>_<标签>_<随机ID>/`。对比 OpenMAVIS、Basalt 与冻结 mocap。`--output` 指定结果根目录，不是要覆盖的某个 run；每次创建新目录，拒绝写入来源或数据集目录。

短回放在上述命令添加 `--max-frames 300`。准备阶段仍校验全部输入图像；短回放标记 `SHORT_RUN_ONLY`，不作为完整跟踪通过证据。

独立验证包只需将来源换成：

```text
/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_173131_635018_DOHC2_validation_01/run_20260922T104634_12bfae
```

## 3. 从 OKVIS2 run 运行并显示 OpenMAVIS

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
"$vio_python" scripts/run_vio_pipeline.py \
  --okvis-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20260921_171047_017923_DOHC2_debug/run_20261008T151536_recovery_normal_gui_d550a0 \
  --show-gui \
  --run-name okvis_reference_gui
```

对比 OpenMAVIS、Basalt、OKVIS2 与 mocap。Basalt/mocap 来自 OKVIS2 已保存的参考快照，不需导入原 Basalt 工程代码；其配组数据链接目标必须继续可读。

`--show-gui` 只开启 OpenMAVIS；`--evo-show-gui` 在报告完成后依次打开 APE、三种 RPE 和轨迹窗口，关闭当前窗口后继续下一个。两个开关可同时使用。GUI 不隐式实时等待；需要按数据时间等待时另加 `--realtime`。在有可用 DISPLAY/Xauthority 的桌面终端运行。Viewer 的 VIO 标记锁定回环，即使尝试开启，System 层仍保持关闭。

## 4. 分阶段与冻结复用

```bash
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
# 不重跑 VIO，只根据保存轨迹重新评测、生成新报告
"$vio_python" scripts/run_vio_pipeline.py \
  --from-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T162509_okvis_gui_full_retry_627b1d \
  --step compare --run-name compare_again

# 不重跑 VIO 或评测，只从保存产物生成新报告并显示 evo
"$vio_python" scripts/run_vio_pipeline.py \
  --from-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T162509_okvis_gui_full_retry_627b1d \
  --step report --evo-show-gui --run-name report_again
```

阶段约定：

| step | 行为 |
| --- | --- |
| all | 新来源准备、VIO、评测、报告 |
| prepare | 新来源准备及部分报告；尚无跟踪结果 |
| vio | 从已有 OpenMAVIS run 复用准备和参考，仅重新跑 VIO、生成部分报告 |
| compare | 复用准备、参考和 VIO，重新评测及报告 |
| report | 复用准备、参考、VIO 和评测，仅生成报告 |

`--from-run` 核对每个复用阶段的文件哈希，创建新 run，不覆盖原 run。不能再指定来源或算法模板；compare/report 禁止通过 `--max-frames`、GUI/VIO 选项重新标记保存轨迹。prepare/vio 的部分报告会列出缺失阶段；可以继续通过新 run 的 `--from-run` 执行下一阶段。

`--binary` 用于新的 VIO 执行；`--config` 作为新来源的算法模板。标定参数始终从来源转换，只接受四路同分辨率 KB4 和正值各向同性噪声；默认要求零 IMU 校正。非零固定 bias 的显式在线估计策略见第 7 节，非零 IMU 尺度/非正交校正仍拒绝。

## 5. 产物与评测口径

| 目录 | 主要产物 |
| --- | --- |
| 01_preparation | 原始标定/算法模板快照、生成 YAML、数据链接、逐图解码和输入审计 |
| 02_reference | Basalt/OKVIS2 在线轨迹、已经转到 IMU 的 mocap、转换与准备记录、来源哈希 |
| 03_vio | 命令/日志、资源统计、frames.csv、online_body.csv、四路诊断/初始化事件、规范化在线轨迹、最终地图轨迹 |
| 04_vio_comparison | common/native/final_map 轨迹、evo zip、完整统计、RPE 帧对、命令 API 参数、对照图 |
| report | 可独立打开的 index.html、report_data.json、图片嵌入与哈希记录；可选 evo GUI 命令 |
| provenance / manifest.yaml | 实现快照、Git 版本/差异、软件与动态库哈希、来源链、阶段状态和复用关系 |

图像 CSV 的整数纳秒保持原样；`corrected_ns = raw_ns + cam_time_offset_ns`，仅调用 SLAM 时转秒。mocap 已是 IMU 时间和 body 位姿，不再叠加相机或 mocap 偏移。

在线快照是 `T_w_b = inverse(T_c_w) * T_c_b`，表示物理 IMU/body 到当前 OpenMAVIS 地图世界。主评测只使用 OK、已 IMU 初始化且有限的位姿；其他预测位姿保留在原始 CSV。多个已初始化坐标段分别诊断，Common 不排名、不拼接。最终地图轨迹受后续优化影响且只导出最大地图，单独折叠评测。

Common 使用本次处理窗口内所有算法及 GT 有效的精确整数纳秒交集，估计轨迹不插值。GT 线性位置/最短弧 SLERP，不外推、不跨无效段、间隔不超过 50 ms。每算法独立 SE(3) 无尺度对齐；RPE 0.1/0.5/1 m 使用相同参考距离帧对、10% 容差。Native 为各自覆盖范围。样本/运动/配对不足显示不可计算原因，不填零。

退出码：`0` 表示所请求阶段正常完成且没有明确的跟踪/评测失败；prepare、短回放仍不是全量跟踪 PASS。`1` 是来源、输入、程序、评测、报告或 GUI 执行错误。`2` 是流程完成但跟踪 NOT_PASSED 或 Common 不可用。以 manifest 中流程状态、跟踪验收、Common 可用性三项分别判读。

## 6. 针对性回归

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
"$vio_python" scripts/test_vio_pipeline.py
OPENMAVIS_TEST_BINARY="$PWD/build-vio/Examples/Multi-Inertial/multi_inertial_prepared" \
  "$vio_python" -m unittest scripts.test_prepared scripts.test_summary
# C++ 回归会创建诊断文件，应在新的临时工作目录运行
regression_dir=$(mktemp -d /tmp/openmavis-vio-regression.XXXXXX)
(cd "$regression_dir" && \
  /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/build-vio/Examples/Multi-Inertial/multi_regression)
git diff --check
```

带 `--vio-mode <词典> <生成的 VIO YAML>` 的 C++ 回归会实际建立 System，并验证回环开启请求无效和空帧无在线位姿。旧的 `--empty-frame-diagnostics <词典> <原 YAML>` 测试仍保留。

## 7. 1026 POC：原始 IMU 与三算法评测

2026-10-28 新增两个显式选项；不指定时保持旧行为。

| 选项 | 默认 | POC 用法 |
| --- | --- | --- |
| `--imu-bias-policy` | `require-zero` | `estimate-from-zero`：保留原始 IMU，零初始 bias，由 OpenMAVIS 在线估计 |
| `--evaluation-profile` | `legacy` | `static` 或 `motion`：APE/ARE、平移 RPE/旋转 RRE、RMSE/P95 |

非零固定 bias 只在显式 `estimate-from-zero` 下允许；源标定不改写，固定 bias 不预先扣除。IMU 尺度和非正交校正仍必须为零，非有限值拒绝。转换审计保存原始 bias、初始化策略和相机几何。该配置与本次 OKVIS2 raw-IMU 基线一致；已有 Basalt 参考应用固定 IMU 标定后估计剩余 bias，报告必须保留这一差异。

静止评测采用每个窗口起始有效 1 s 的平均位姿对齐，RPE/RRE 使用 0.1/1 s；运动评测采用整段匹配位置 SE(3) 对齐，距离间隔 0.1/0.5/1 m，并补充 0.1/1 s。均不校正尺度。Common 是三算法与可用 GT 的精确纳秒交集；帧对使用全部算法连续性边界的并集，排除 GT 空洞、输出中断和已知重置。保存实际对齐窗口、原始误差和帧对哈希。未初始化或存在多个已初始化坐标段时，Common 不排名，Native 分段诊断并保留失败原因。

单包示例（把 `okvis_run` 设置为已完成的 run 绝对路径）：

```bash
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
"$vio_python" scripts/run_vio_pipeline.py \
  --okvis-run "$okvis_run" \
  --imu-bias-policy estimate-from-zero \
  --evaluation-profile motion \
  --run-name poc1026_small_move
```

六包调度器读取 OKVIS2 批次 `state.json` 中明确记录的完成 run，冻结来源文件哈希，逐包创建新目录。先指定 `--case small_move` 完成验证，再用 `--remaining` 跑其余五包；已经完成的 small_move 不重复执行。返回码 2 的跟踪/评测未通过保留为 `diagnostic_complete`，可以继续其他场景；执行错误返回码 1 停止队列。运行中断或失败的尝试不自动覆盖重跑，须先检查保存日志。

```bash
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
source_state=/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20261028_poc1026_parallel_rawbias/state.json
batch=/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/20261028_poc1026_rawbias
"$vio_python" scripts/run_poc_batch.py --source-state "$source_state" --output "$batch" --case small_move
# 审核 small_move 后继续；已完成的包不会再次执行。
"$vio_python" scripts/run_poc_batch.py --source-state "$source_state" --output "$batch" --remaining
"$vio_python" scripts/summarize_poc_batch.py --batch "$batch"
```

汇总输出为 `report/index.html`、`report/report_data.json`、`report/metrics.csv`。HTML 自包含图片并支持放大；五包为主报告，`static_H_30s_humanmove` 单列补充。轨迹按世界 Y 向上、XZ 水平面绘制；在线结果不混入最终地图轨迹。`protected_inputs.json` 与 `preservation.json` 保存来源保护校验。

完整回归覆盖 IMU bias、POC 指标与旧流程：

```bash
"$vio_python" -m unittest discover -s scripts -p 'test*.py'
```

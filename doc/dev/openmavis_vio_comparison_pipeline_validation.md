# OpenMAVIS 四目 VIO 流水线验证记录

日期：2026-10-08。基线 `5be2702`，分支 `codex/openmavis-vio-pipeline`。计划在源码修改前保存。本报告只使用本轮实际构建和运行产物，不复用历史跟踪指标作为通过证据。

## 1. 交付结论与边界

已实现 Basalt/OKVIS2 两种 run 输入、四目 KB4 标定转换、不可被 Viewer 重新开启回环的 VIO 模式、整数纳秒在线 body 轨迹、evo Common/Native/最终地图评测、中文自包含 HTML、冻结阶段复用与失败诊断。

两种来源的开发包均完成 1195 帧，独立包完成 2683 帧，三个完整回放均达到本轮初始化后连续跟踪标准。OpenMAVIS GUI 真实完整回放正常退出；evo 四种指标和轨迹窗口实际显示并关闭。HTML 图片、结构和产物一致性通过；**桌面浏览器实际页面渲染未验证**，原因及其他限制见第 8 节。流程完成、跟踪通过和精度数值独立报告。

使用命令与阶段说明见 [使用说明](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/doc/dev/openmavis_vio_comparison_pipeline_usage.md)。所有构建、运行、失败结果和配图保存在 `OpenMAVIS/results/vio_pipeline_20261008/`，未加入 Git。

## 2. 输入、标定与来源检查

| 来源 | run 目录 | 图像组 / 图像 / IMU |
| --- | --- | --- |
| 开发 Basalt | `/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b` | 1195 / 4780 / 20219 |
| 开发 OKVIS2 | `/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20260921_171047_017923_DOHC2_debug/run_20261008T151536_recovery_normal_gui_d550a0` | 1195 / 4780 / 20219，链接同一 Basalt 配组包 |
| 独立 Basalt | `/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_173131_635018_DOHC2_validation_01/run_20260922T104634_12bfae` | 2683 / 10732 / 45059 |

准备阶段真实调用新 C++ 入口 `--validate-only`，使用 OpenCV 解析生成 YAML 并解码全部四路图像；确认组时间一致、递增、1280×800、IMU 覆盖和轴顺序。没有重新配组或改写图像 CSV。

三者标定 JSON SHA256 为 `1522183b255b82b503d173e283e8c2ab28f6bd09afae75a97250229db2cccf5c`，相机偏移均为 **+2631359 ns**。每帧核对 `corrected_ns-raw_ns=2631359`；CSV 文件名用于图像查找，转秒只发生在调用 SLAM 时。mocap 冻结文件已位于 IMU/body 和 IMU 时间，导入过程不再变换或拟合。

三个完整回放的生成配置 SHA256 相同：`d0fde872cc15568c6b069716fe5389d64bfa75c80a71c4c4be8f3c98cebb62d3`。内外参按来源双精度转换；报告列出与手写模板的末位精度及矩阵差异。特征数量、匹配模式、门槛及 IMU 噪声没有实验调参。运行前后核对来源 manifest、准备记录、标定、参考快照和五个 CSV 的哈希相同；图像只读解码，本轮不计算全部图像字节哈希。

## 3. 源码检查、测试与构建

在线位姿明确使用 `T_w_b = inverse(T_c_w) * T_c_b`，Frame 的标定 `mTcb` 是 body→cam0。合成非平凡旋转和平移测试核对 Frame::GetImuPose 和快照公式。在线时间直接导出整数 corrected_ns，与旧六位小数的 SaveTrajectoryEuRoC 分离。

`System.VIOOnly` 缺省为 false；新配置为 true，清空 Atlas 加载/保存名并禁止 ActivateLC。Viewer 默认关闭并每帧保持关闭。LoopClosing 入口记录真实回环、合并和回环 GBA 次数；局部建图、惯性初始化及必要优化保留。旧设置实际回归日志为 `VIO_MODE vio_only=0 loop_enabled=1 atlas_persistence=0`。

| 验证 | 真实结果 | 证据文件 |
| --- | --- | --- |
| 新流水线 Python 针对性测试 | **40/40** | `python_tests_delivery.log` |
| 原输入与汇总 Python 测试 | **21/21** | `legacy_tests.log` |
| C++ 合成几何/IMU/body + 实际 System VIO 锁定 | **27/27** | `cpp_tests.log` |
| C++ 原空帧/清除诊断与 body 回归 | **28/28** | `cpp_legacy.log` |
| 隔离构建 prepared、原 euroc、camera/match audit、multi_regression | 成功 | `build.log`、`build_2.log` |
| 默认 build-vio 输出构建 | 成功 | `default_build.log` |
| 源码 Python 语法、shell 语法、git diff --check | 通过 | 交付检查 |

Python 测试覆盖两种 Basalt 布局、OKVIS v2、未知版本/未完成阶段、断链/冲突、来源漂移/manifest 缺失失败报告、已经平移的图像时间、组数不符、参考时钟不重叠、来源输出保护、不同四目内外参、相机/噪声/IMU 校正拒绝、状态/非有限位姿/坐标段、501 ns 时间恢复边界和歧义、已知刚体变换的 evo 零误差、少样本/GT 缺口/RPE 跨段、资源/配置差异和 GUI 文件名及冻结输入保护。原测试覆盖缺图、坏图、重复时间、空/单样本 IMU、覆盖提前结束等。

真实运行使用固定隔离二进制：

```text
results/vio_pipeline_20261008/binary/Examples/Multi-Inertial/multi_inertial_prepared
executable SHA256: 50d3cc75e0983750ad6efd53612097ab7d3780792311d02da7966ad1944437f6
libORB_SLAM3 SHA256: c5a75428373dc8bec7aaeaa736cd7f0e3425f25fc80534137b6f27f28b96c0fc
ORBvoc SHA256: f8dd027f7a6cb88129821341194d7f2c75b77b3394257ddd0d2229863d1a3570
```

构建快照保存 C++ 源文件哈希；每个运行保存执行时的 Git HEAD/差异与脚本快照。源码提交之前的运行 HEAD 是基线，不能只看 HEAD 判断实现版本。交付时额外读取该二进制的 169 个已解析动态依赖并保存 SHA256 到 `runtime_dependencies_delivery.json`；这是补充检查时间的库快照。后续新运行 manifest 自动保存动态依赖、Python/包版本及实现哈希。

本机真实 Python 环境为 `/home/yuewang/.local/share/pipx/venvs/evo/bin/python`，Python 3.12，evo 1.37.0、NumPy 2.5.2、Matplotlib 3.11.1、Pillow 12.3.0、PyYAML 6.0.3、PyQt6 6.11.0。版本固定文件为 `scripts/requirements-vio.txt`。

## 4. 真实短回放及完整连续性

短回放 `run_20261008T161507_basalt_short_2904c9` 与 `run_20261008T161811_okvis_short_ac9594` 均处理 300 帧，首次 IMU 初始化分别为 frame 135、136，初始化后 OK 为 100%，四路均有优化观测，标记 SHORT_RUN_ONLY。早期短报告 Native 参考范围尚未裁到短窗口；最终实现已限定到本次实际处理窗口，保存首次产物不覆盖。

以下 frame 编号从 **0** 开始；全窗口状态包含启动等待/丢失，后初始化比例只从真实首次初始化开始。

| 完整回放 | 输入/处理 | 首次 IMU frame | 全窗口 OK（帧/比例） | 初始化后 OK | 总/初始化后重置 | 末帧 | 在线主轨迹/Common | 最终地图/关键帧 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 开发 Basalt 来源 / 无 GUI | 1195/1195 | 136 | 1133 / 94.81% | 100.00% | 0/0 | OK | 1059/1059 | 1133/37 |
| 开发 OKVIS2 来源 / OpenMAVIS GUI | 1195/1195 | 135 | 1133 / 94.81% | 100.00% | 0/0 | OK | 1060/1060 | 1133/38 |
| validation_01 / 无 GUI | 2683/2683 | 726 | 2042 / 76.11% | 100.00% | 9/0 | OK | 1957/1957 | 2030/48 |

三个完整回放都记录一次实际 `imu_initialized` 异步事件，初始化后的地图切换、初始化丢失为 0；最长初始化后非 OK 时段为 0 s，地图数最大为 1。开发包在前 300 帧内初始化。独立包 frame 726 才初始化，之前 9 次重置全部保留在报告；不能将初始化后的 100% 推广为完整窗口 100%。其有效在线轨迹在 coordinate epoch 9，只有一个已初始化坐标段，因此可以做 Common。

| 回放 | 排除无位姿/未初始化 | 四路局部优化后观测累计（cam0–3） | 初始化后独立点中位数 |
| --- | --- | --- | --- |
| 开发 Basalt 来源 / 无 GUI | 62 / 74 | 147931, 188704, 222782, 190609 | 590 |
| 开发 OKVIS2 来源 / OpenMAVIS GUI | 62 / 73 | 147723, 190166, 226351, 192938 | 596.5 |
| validation_01 / 无 GUI | 638 / 88 | 287353, 320867, 487000, 556669 | 753 |

四路都实际贡献优化观测；表中是观测次数，不是唯一三维点数。在线主结果和最终地图行数不同，因为前者排除 IMU 初始化前样本，后者含后续优化并只导出最大地图。所有在线/最终轨迹有限、严格递增；最终轨迹恢复时间的残差均不超过 501 ns，无重复/歧义。保留惯性预测快照，但不混入主评测。

## 5. evo 真值对照与图表

Common 取所有算法和可插值 GT 的精确整数时间交集，估计不补帧；GT 不跨无效段、最大间隔 50 ms。各算法 SE(3) 对齐，无尺度校正。RPE 使用共同参考距离帧对，10% 容差。通过 evo Python API 实际执行，保存调用参数、zip、统计、原始误差和帧对时间。独立审计逐项核对 evo zip 的 RMSE/均值/中位数/标准差/极值/SSE、P95 和样本数；共核对 28 个 Common 指标 zip，配对在参与算法间一致且不跨 GT 段。

| 回放 / 算法 | APE RMSE(m) | RPE 0.1m RMSE(m) | RPE 0.5m RMSE(m) | RPE 1m RMSE(m) | APE N / RPE N（0.1,0.5,1） |
| --- | --- | --- | --- | --- | --- |
| 开发 Basalt 来源 / 无 GUI / openmavis | 0.127994 | 0.033064 | 0.071986 | 0.091144 | 1059 / 918, 1015, 971 |
| 开发 Basalt 来源 / 无 GUI / basalt | 0.026655 | 0.008037 | 0.020358 | 0.024940 | 1059 / 918, 1015, 971 |
| 开发 OKVIS2 来源 / OpenMAVIS GUI / openmavis | 0.047553 | 0.019541 | 0.044342 | 0.053827 | 1060 / 919, 1016, 972 |
| 开发 OKVIS2 来源 / OpenMAVIS GUI / basalt | 0.026673 | 0.008037 | 0.020352 | 0.024933 | 1060 / 919, 1016, 972 |
| 开发 OKVIS2 来源 / OpenMAVIS GUI / okvis | 0.081391 | 0.014540 | 0.030842 | 0.039380 | 1060 / 919, 1016, 972 |
| validation_01 / 无 GUI / openmavis | 0.020244 | 0.005694 | 0.010026 | 0.012494 | 1957 / 1765, 1747, 1722 |
| validation_01 / 无 GUI / basalt | 0.010849 | 0.003951 | 0.006226 | 0.007385 | 1957 / 1765, 1747, 1722 |

同一开发数据、相同配置/二进制下，两次 OpenMAVIS 的 APE 为 0.127994 m 与 0.047553 m。帧初始化时点和异步执行有所不同，本轮没有控制重复运行、线程调度或缓存，**不能将精度变化归因于 GUI、来源输入方式或宣称本算法稳定优于其他算法**。原始首次结果保留。在线曲线还显示启动后短段较大误差和变化；OK 状态表示跟踪判据通过，不等于无位姿修正或绝对精度通过。惯性初始化必要优化仍保留。

下图均来自保存数据，不做平滑或裁剪；时间轴从第一输入组开始。完整 HTML 嵌入图像字节、样式和脚本，没有 CDN/网络依赖。Native 和最终地图在折叠区单列；短/完整输入覆盖与排除理由保留。

### 开发三算法 Common 轨迹

![三算法共同窗口轨迹](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164843_report_gui_final_d5b518/04_vio_comparison/common/trajectories.png)

### 开发三算法 APE

![三算法共同窗口平移 APE](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164843_report_gui_final_d5b518/04_vio_comparison/common/ape_translation.png)

### 独立验证完整状态与特征

![独立验证完整窗口状态和特征](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164905_validation_report_final_e0af39/report/diagnostics/tracking.png)

### 四路实际优化支持

![开发四路局部优化观测](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164843_report_gui_final_d5b518/report/diagnostics/camera_support.png)

## 6. GUI、失败记录与报告复用

首次 OpenMAVIS GUI `run_20261008T162138_okvis_gui_full_4285ae` 在沙箱内退出 134，日志是 Pangolin 无法连接 X11；生成失败报告并保留。使用允许 DISPLAY/Xauthority 访问的执行环境重试 `run_20261008T162509_okvis_gui_full_retry_627b1d`，实际 `Starting the Viewer`、1195 帧、`Viewer finished`、退出 0。日志 `VIO_MODE vio_only=1 loop_enabled=0 atlas_persistence=0`，逐帧回环/合并/回环 GBA 次数全部 0。退出时有两个 Qt timer 线程警告，未造成进程非零退出或轨迹缺失；没有宣称该线程警告已修复。本次 GUI 是离线回放，没有隐式 realtime。

evo 首次测试 `run_20261008T163409_evo_gui_verified_752e50` 的自动关闭测试钩子未覆盖 evo 自身 Qt event loop，因而人工终止了该次子进程并保留失败记录。修改**测试专用**钩子后，实际显示 APE、三个 RPE 和 evo_traj 五个窗口，Qt 平台为 xcb、DISPLAY=:1，记录窗口可见性、尺寸、标题和像素；各窗口约 1.2 s 后通过自己的 QApplication 关闭，完整返回 0。普通流水线没有自动关闭钩子，等待用户关闭窗口。

首次图例中的重复 `vio_matched` 已修正为 openmavis/basalt/okvis 独立文件名。最终 GUI 证据在 `evo_gui_probe/evidence_final/`；API 锁定测试证明请求启用回环仍无效，未做 Viewer 控件鼠标交互验证。

![evo 真实 Qt 轨迹窗口](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/evo_gui_probe/evidence_final/evo_traj_trajectories.png)

`run_20261008T164204_basalt_compare_reuse_684c51` 完成 --from-run/--step compare：复用准备、参考和 VIO，仅重新评测。下列最终报告 run 复用完成产物，仅生成报告，不重跑 SLAM；三算法报告额外显示 evo 窗口。保留每次来源链和冻结文件哈希。

| 报告 | 路径 | 嵌入图 / 静态结构 |
| --- | --- | --- |
| report_gui_final | [run_20261008T164843_report_gui_final_d5b518](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164843_report_gui_final_d5b518/report/index.html) | 18 图 / 9 区块 |
| basalt_report_final | [run_20261008T164905_basalt_report_final_e690ad](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164905_basalt_report_final_e690ad/report/index.html) | 15 图 / 9 区块 |
| validation_report_final | [run_20261008T164905_validation_report_final_e0af39](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/vio_pipeline_20261008/runs/run_20261008T164905_validation_report_final_e0af39/report/index.html) | 15 图 / 9 区块 |

独立审计 `delivery_audit.json` 验证图片 base64 可解码且与源字节一致、页面没有外部资源引用、锚点存在、报告指标与保存 JSON 一致、无缺失项。配图文件使用绝对路径便于本机 Markdown 显示；删除 results 会使本文外部图片链接失效，而 HTML 内嵌图仍可独立保存。

## 7. 资源与可复制命令

| 回放 | VIO 段耗时(s) | TrackMulti 总/中位/最大 | 峰值 RSS(MiB) | 处理输入时间(s) |
| --- | --- | --- | --- | --- |
| 开发 Basalt 来源 / 无 GUI | 114.416 | 52.037s / 43.656ms / 51.418ms | 798.8 | 39.800697 |
| 开发 OKVIS2 来源 / OpenMAVIS GUI | 151.586 | 51.745s / 43.586ms / 51.040ms | 1053.3 | 39.800697 |
| validation_01 / 无 GUI | 265.513 | 115.775s / 44.459ms / 80.919ms | 1001.7 | 89.401603 |

VIO 段包含词典、图像、诊断和 SLAM 关闭，TrackMulti 只计每帧调用。RSS 是 /usr/bin/time 的进程峰值，GUI 包括显示开销；准备阶段解码不包含在 VIO 数字内。独立包准备解码耗时 469.45 s，不能因无逐图日志输出判定卡死。数据缓存与并发 I/O 未控制，这些耗时不是公平算法性能比较。

本轮真实回放共用如下二进制/结果根目录（在项目根目录执行）：

```bash
vio_python=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
vio_binary="$PWD/results/vio_pipeline_20261008/binary/Examples/Multi-Inertial/multi_inertial_prepared"
vio_output="$PWD/results/vio_pipeline_20261008/runs"
"$vio_python" scripts/run_vio_pipeline.py \
  --basalt-run /home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b \
  --binary "$vio_binary" --output "$vio_output" --run-name basalt_full
"$vio_python" scripts/run_vio_pipeline.py \
  --okvis-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20260921_171047_017923_DOHC2_debug/run_20261008T151536_recovery_normal_gui_d550a0 \
  --binary "$vio_binary" --output "$vio_output" --run-name okvis_gui_full --show-gui
"$vio_python" scripts/run_vio_pipeline.py \
  --basalt-run /home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_173131_635018_DOHC2_validation_01/run_20260922T104634_12bfae \
  --binary "$vio_binary" --output "$vio_output" --run-name validation_full
```

新用户运行建议采用使用说明中的默认 `scripts/build_vio.sh` 和 build-vio 二进制。历史失败不能覆盖；上述命令重新执行会建立新 run，不保证数值逐位重复。正式 evo GUI 命令无需测试钩子；测试钩子、证据和审计脚本均位于 results。

## 8. 未验证项与剩余限制

- 浏览器工具拒绝 `file://` 本地文件 URL，只允许 http/https，并明确禁止绕过策略。没有通过 HTTP 服务或其他浏览器绕过。实际页面渲染、响应式布局、图像放大和打印交互标记 **NOT_VERIFIED**；图片内容视觉检查、HTML 静态及字节审计已完成。
- 独立包启动阶段慢且有 9 次重置；本轮连续性门槛针对初始化后，完整窗口 OK 仅 76.11%。不隐去这些启动失败。
- 同一开发配置两次 OpenMAVIS 精度有明显差异；本轮实现评测能力，没有执行精度稳定性重复实验或轨迹精度优化，不证明优于 Basalt/OKVIS2。
- Viewer 的 Qt timer 关闭警告仍在。完整 GUI 回放正常退出；evo 自动关闭验收是测试专用钩子，未模拟用户逐项点击操作。
- 参考算法只提供来源冻结的在线轨迹，本流水线不据此追认其逐帧 OK 状态。OpenMAVIS 射线有效域与参考 mask 策略不同；mocap marker–IMU 外参、时钟转换依赖来源，本轮不重新标定。
- 仅支持目前验证的来源布局、OKVIS v2 和精确四目 KB4/零 IMU 校正；不自动修复不支持标定、找回断链数据或修改来源 run。

## 9. 提交组织

源码按 VIO 模式/在线导出、流水线工具及测试、中文文档分组提交。保留基线之前所有提交和用户图片路径修改，结果、依赖和构建不入 Git；没有推送或合并。

已提交：`05c2b48`（VIO 锁定与在线 body 导出），`91be9b9`（流水线、评测、报告、来源与测试）。中文计划、使用说明与本验证文档另作第三组提交。

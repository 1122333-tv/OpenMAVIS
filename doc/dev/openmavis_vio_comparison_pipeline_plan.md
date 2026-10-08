# OpenMAVIS 四目 VIO、轨迹对比与 HTML 报告流水线计划

日期：2026-10-08。基线 `5be2702`，实施分支 `codex/openmavis-vio-pipeline`。本文件在源码修改前保存；验收记录另存 `openmavis_vio_comparison_pipeline_validation.md`。

## 目标与固定决策

输入 Basalt run 时复用配组数据，与 Basalt、mocap 对比；输入 OKVIS2 run 时复用其准备数据和参考快照，与 Basalt、OKVIS2、mocap 对比。自动转换四目 KB4 标定，在线 body 轨迹用于主评测，最终地图轨迹另作补充。`--show-gui` 仅控制 OpenMAVIS，`--evo-show-gui` 独立控制 evo，默认均关闭。

不重新配组，不修改或重跑 Basalt/OKVIS2，不推送、不合并。不要求 OpenMAVIS 精度优于其他算法。保留已有初始化、跟踪修复及用户图片路径提交。

## 入口与来源解析

新增 `scripts/run_vio_pipeline.py`，保留 `run_prepared.py` 和原四目入口。

| 参数 | 行为 |
| --- | --- |
| `--basalt-run` / `--okvis-run` | 新运行必选其一，互斥 |
| `--step` | all/prepare/vio/compare/report，默认 all |
| `--from-run` | 后续阶段复用冻结产物并创建新运行，不重跑完成阶段 |
| `--binary`、`--config` | 二进制及算法模板覆盖；来源标定生成运行配置 |
| `--output`、`--run-name` | 结果根目录及标签；唯一运行目录，禁止覆盖 |
| `--max-frames` | 正整数短回放，默认全部 |
| `--show-gui`、`--evo-show-gui`、`--realtime` | 独立开关；GUI 不隐式启用实时等待 |

布局为 `01_preparation / 02_reference / 03_vio / 04_vio_comparison / report`，各阶段包含 inputs/outputs/logs/diagnostics。manifest 保存命令、来源链、状态、软件/二进制版本、哈希、复用关系。禁止写入来源目录。

Basalt 按 manifest 解析完成的 prepare/gt/vio，支持已核对的旧布局和 inputs/outputs 布局。OKVIS2 首版支持 okvis-vio/version 2，使用准备阶段链接与有效标定、02_reference 中冻结 Basalt/mocap、03_vio 在线规范化轨迹。运行时不导入其他工程代码。

核对数据身份、相机顺序、CSV 哈希、准备记录、时间偏移，缺失/冲突/断链在准备阶段明确失败并生成诊断报告。图像偏移只在调用 SLAM 时应用一次；已转换到 IMU 时间与 body 位姿的 mocap 原样导入。

## 标定、VIO 模式与在线导出

cam0–3 对应 Camera1–4；生成四路内参、分辨率、IMU 参数、相机到 IMU 矩阵，前双目变换 `inverse(T_b_c0) * T_b_c1`。模板默认沿用 repaired 算法参数。只接受四路同分辨率 KB4、正值各向同性 IMU 噪声和零 IMU 校正；不支持项明确拒绝，不拟合、不平均。使用 OpenCV 实际解析和逐图解码，检查四路时间及 IMU 覆盖。

新增默认关闭的 `System.VIOOnly`，新流水线开启：关闭回环修正、地图合并、回环触发 GBA、Atlas 持久化，System 阻止重新开启回环，Viewer 显示锁定状态；保留惯性初始化必要优化和局部惯性优化，不改匹配、噪声、阈值。记录实际模式与修正事件。

TrackMulti 完成时捕获只读 Frame IMU/body 到世界的在线快照，不把相机返回值当作 body。入口整数 corrected_ns 直接导出，保留有效性、状态、IMU 初始化、地图与重置信息。主评测只用 OK、已初始化、有限位姿；完整状态和排除原因单列。多次重建的坐标段分别诊断，多个已初始化段时统一 common 排名不可用，不拼接或挑最好段。

旧最终地图导出保留并注明后续优化与最大地图限制。补充转换用 frames.csv 唯一恢复精确时间，微秒舍入容差 501 ns，记录残差；超限/重复/歧义失败。在线输出不依赖此恢复。构建隔离到新目录，不默认调用历史二进制。

## 评测与报告

OpenMAVIS 内独立评测，允许复制已核对工具并保留许可证与来源哈希。Common 为所有参与算法与 mocap 有效整数 ns 的交集，Native 使用各自 GT 可匹配范围并折叠。GT 位置线性插值、最短弧 SLERP、不外推、不跨无效段、最大间隔 50 ms；估计不补帧。

冻结 GT 时间标定，SE(3) 无尺度对齐。evo 平移 APE、0.1/0.5/1 m RPE，参考距离配对容差 10%，不跨 GT 无效段或坐标段。保存命令、zip、统计、样本/配对数。少于五个共同样本、运动不足、无配对时显示不可用，不填零。

中文独立 HTML 嵌入图片、样式和脚本，无 CDN：来源/配置/模式、完整状态时间线、初始化/重置、四路支持、耗时资源、Common 指标和轨迹/APE/RPE 对照、折叠 Native/最终地图、各种计数、哈希/缺失项/GT 转换及有效域策略差异。失败或部分完成也生成报告；流程完成、跟踪验收、指标可用性分开。报告仅使用保存产物。

## 测试与验收

1. 来源：两入口、两种 Basalt 布局、未知版本、未完成阶段、冲突/断链/重复偏移；标定：不同内外参、矩阵方向、OpenCV 解析、不支持项。
2. 在线/VIO：合成 body 转换、整数时间、无位姿/非有限、状态过滤/坐标段；开启请求不能破坏 VIO，GUI 不改模式，旧入口默认兼容。
3. 评测：已知刚体变换、精确交集、GT 缺口、少样本、多段、RPE 配对、不可用项；统计与 evo 一致；HTML 图片可解码、无外部依赖、桌面浏览器实际查看。
4. 真实：关联 Basalt run、指定 OKVIS2 run 各短/1195 全量；validation_01 Basalt run 2683 全量；独立验证 OpenMAVIS GUI 正常退出及 evo 窗口。
5. 全部请求帧、有实际 IMU 初始化及四路优化；初始化后 OK≥95%、末帧 OK、无初始化后重置/地图切换/初始化丢失，开发前 300 帧初始化。精度只记录真实值。

运行前后来源哈希不变，相关现有/新增测试、新旧入口构建、git diff --check。记录命令、指标、报告路径、限制，按源码/测试/文档分组提交，结果与构建不入 Git。

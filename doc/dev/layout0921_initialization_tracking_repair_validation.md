# Layout0921 初始化与跟踪修复验证记录

日期：2026-09-30。基线 a46f14c，分支 codex/openmavis-layout0921-prepared。

## 执行状态

计划已在修改源码前保存。以下区分源码检查、针对性测试、构建与真实回放。无 GUI 算法候选 v2 已完成两段数据各三次完整复验，达到所定连续性标准。v2 的 GUI 全量回放发现退出阶段崩溃；保留失败并修复后，v3 的完整 GUI 回放已正常退出。最终 v3 两段数据各三次无 GUI 复验也全部通过。修复后的完整四目惯性回放及所定初始化后连续性验收通过，独立包仍保留启动延迟和初始化前重置限制。

本报告补充 5 张统计图和 2 张原始四目诊断叠图。配图全部读取本轮已保存的 CSV、汇总和轨迹，没有为作图重新运行 SLAM。图中帧号从 0 开始，所有时间曲线使用校正图像时间相对该包首帧的秒数。

## 输入

复用计划中的两个 Basalt 配组包，开发 1195 帧，独立验证 2683 帧。相机偏移 +2631359 ns。不得叠加 mocap 偏移。

输入目录和准备来源完全沿用计划：

| 用途 | 配组目录 | 图像/IMU 检查 |
| --- | --- | --- |
| 开发 | `/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b/01_preparation/dataset` | 1195 组 / 4780 图像，IMU 20219；完整回放逐帧解码 |
| 独立 | `/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_173131_635018_DOHC2_validation_01/run_20260922T104634_12bfae/01_preparation/dataset` | 2683 组 / 10732 图像，IMU 45059；单独逐图解码及完整回放 |

独立输入四路组时间一致且严格递增，所有图像为 1280×800；校正后首尾时间均由 IMU 覆盖。两次准备保存的 `inputs/delivery/calibration.json` SHA256 相同：`1522183b255b82b503d173e283e8c2ab28f6bd09afae75a97250229db2cccf5c`，本轮重新核对，详见 `input_calibration_audit.json`。各次运行保存自己的 preparation.json、标定来源、输入 CSV/配置哈希及配置副本，不重新配组，不写 Basalt 目录。

## 实验

结果根目录：`results/repair_20260930T142226/`。基线使用未重新构建的原始二进制/动态库，后续构建输出隔离到实验子目录。

| 实验 | 处理 | 首次 IMU 初始化帧 | 初始化后 OK | 末帧状态 | 总重置/初始化后重置 | 地图数 |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| E0_original | 1195 | 201 | 15.19% | RECENTLY_LOST | 46/4 | 2 |
| E0_rays_1 | 1195 | 201 | 30.58% | RECENTLY_LOST | 42/0 | 1 |
| E0_rays_2 | 1195 | 201 | 40.85% | OK | 42/0 | 1 |
| E0_rays_3 | 1195 | 201 | 56.54% | RECENTLY_LOST | 42/0 | 1 |

三次相同射线配置存在明显异步运行波动，均未达到 95%。不能以一次运行的改善作为因果证明。原配置也未通过。所有运行进程退出 0，包装器因验收失败退出 2。

### 源码与针对性测试

原 a46f14c 头文件和原动态库编译的合成测试：5 个四路投影场景全部失败，四路优化器姿态/射线及三角化方向通过，重复观测计数失败（2/8）。原测试日志 `baseline_regression.log`。修复投影后 7/7 通过；观测修复后 12/12 通过，覆盖最后观测删除、相机间观测融合、参考相机距离和侧右临时点索引。

### 真实回放 E1 / E2

| 实验 | 全量初始化后 OK | 末帧 | 首次初始化 | 初始化前重置 |
| --- | ---: | --- | ---: | ---: |
| E1 仅右相机模型 | 45.88% | RECENTLY_LOST | 201 | 42 |
| E1 再改侧相机窗口 | 54.53% | RECENTLY_LOST | 201 | 42 |
| E1 四路独立搜索 | 55.23% | RECENTLY_LOST | 201 | 42 |
| E2 观测/索引修复 | 41.75% | RECENTLY_LOST | 201 | 42 |

均完成 1195 帧，另各跑前 300 帧；没有通过连续性验收。E1 四路局部优化内点累计为 6168 / 4519 / 9036 / 3422，证明侧相机实际有观测进入优化；独立点中位数仍只有 16。确定的源码错误已由最小测试证实，但修复这些错误不足以解决脆弱初始化和跟踪。E1/E2 指标也不能脱离 E0 的运行波动单独解释为收益。

以上 E0–E2 尚未解决连续跟踪，继续逐阶段验证。静态匹配通过数不能替代连续跟踪或绝对精度证明。

### E3–E5 几何候选及初始化支持

所有实验先跑 300 帧再跑 1195 帧，仍保持 ratio=0.8、TH_LOW=50、视差/正深度/重投影原门槛。新增几何门槛为雅可比及金字塔方差归一化射线极线误差 ≤3.841，双向最佳一致及一对一关联。

| 实验 | 首次 IMU 初始化帧 | 初始化后 OK | 末帧 | 总/初始化后重置 | 全输入 OK |
| --- | ---: | ---: | --- | --- | ---: |
| E3 前双目几何候选，原初始化门槛 | 201 | 33.30% | RECENTLY_LOST | 42/0 | 31.30% |
| E4 前双目，30 点及覆盖 | 318 | 100% | OK | 0/0 | 79.67% |
| E4 前双目，50 点及覆盖 | 无 | 无 | NOT_INITIALIZED | 0/无 | 0% |
| E5 再加 cam1–cam3，30 点及覆盖 | 194 | 100% | OK | 2/0 | 90.13% |
| E5 再加 cam0–cam2，30 点及覆盖 | 135 | 100% | OK | 0/0 | 94.81% |

前三组候选不能满足前 300 帧惯性初始化的全部要求。最后一组是后续候选，需冻结后重复及独立验证。四路局部优化内点累计 148456 / 189503 / 222396 / 193184；这是观测次数而非独立地图点数。E3 首 128 帧前双目独立种子中位数仍仅 3，几何过滤没有凭空增加视觉支持；主要改善来自拒绝脆弱建图并增加真实跨相机支持。

E3 探索构建的后续审查发现新增 mvuRight 数组长度需要保持全局 N（部分既有建图函数会读全局索引），已修正；早期探索结果保留，最终候选重新验证。E2 后续最小测试还覆盖了右/侧左临时点的局部索引转换。

### 解析测试发现的 IMU 错误

- 原预积分在零角速度时 J1/J2 除以 θ²/θ³/θ⁴，恒加速度解析测试返回 NaN。改为无量纲转角的积分系数，并使用小角度泰勒极限；零角速度、微小角速度以及 0.2/2 rad/s 旋转加速度解析测试通过，保留原积分模型和噪声。
- 原默认 Frame 时间戳未初始化。地图重置后曾记录单帧预积分时长约 583–588 秒（设备绝对时间），而真实帧间隔约 0.03333 秒。空帧改为无有效时间，预积分跳过无真实前帧的区间；有效区间的零/单边界样本明确报错，避免负循环长度或未完成等待。
- E6 将分别记录数值修复与重置时间修复，不能把两者与几何改进混为单一因果结论。

### E6 数值及重置边界对照

| 实验 | 首次 IMU 初始化 | 初始化后 OK | 末帧 | 总重置 |
| --- | ---: | ---: | --- | ---: |
| E6 小角积分修复 + 原前双目初始化 | 201 | 8.95% | RECENTLY_LOST | 42 |
| E6 小角积分修复 + E5 三对质量门槛 | 135 | 100% | OK | 0 |
| E6 再修重置时间 + 原前双目初始化 | 203 | 48.89% | RECENTLY_LOST | 32 |
| E6 再修重置时间 + E5 三对质量门槛 | 136 | 100% | OK | 0 |

均完成 300 帧短回放及 1195 帧完整回放。E2 有 42 帧预积分区间大于 0.1 秒，最大 587.9408 秒；重置边界修复后的原初始化对照最大 0.033341 秒、异常区间为 0。质量门槛版本没有重置，本身不触发该边界；不能把其稳定跟踪归因于重置修复。

E6 最终合成测试 25/25，包括实际四相机 PoseOptimization 恢复合成位姿、零角速/恒加速、旋转加速解析解。恒加速度时积分时长误差 4.47e-8 秒，速度误差 2.89e-6 m/s，位置误差 8.74e-8 m。输入/汇总测试 19/19，使用本轮 E6 新入口运行。新旧四目入口均构建通过。

独立输入逐图检查：`validation01_input.log` 确认全部 2683 组 / 10732 张 1280×800 图像成功解码，IMU 45059 条。相同相机配置和偏移，不重新配组。

![开发包各实验的初始化后 OK 比例与首次 IMU 初始化帧](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/01_experiment_metrics.png)

**图 1：开发包逐阶段完整回放指标。** 来源为 E0–E6 对应完整运行及 `E7_v3_debug_1/2/3` 的 `summary.json`，详细运行名见配图清单。每个点表示一次 1195 帧回放，重复点仅纵向错开，没有求均值或估计置信区间。虚线分别为初始化后 OK ≥95% 和前 300 组初始化期限（最大帧号 299）。E4 前双目 30 点虽然初始化后为 100% OK，但第 318 帧才初始化，未满足开发期限；50 点版本未初始化，初始化后比例未定义，未画成 0%。这些实验顺序包含不同因素，不能仅凭相邻点差异认定单项因果收益。

## 最终候选逻辑

```mermaid
flowchart LR
    A["四路有效域特征"] --> B["01 / 13 / 02 射线极线候选"]
    B --> C["描述子门槛与双向一致"]
    C --> D["原几何门槛三角化"]
    D --> E["共享特征一致才合并种子"]
    E --> F["30 个独立点及两路空间覆盖"]
    F --> R["仅 OK 且有有效位姿的 bootstrap 关键帧"]
    R --> G["四相机地图观测与惯性优化"]
```

缺省关闭几何种子/质量门槛以保持旧配置约定；修复配置显式启用。只观察点的相机检查正深度，跨相机种子统一存 cam0 坐标，但允许 cam0 负深度。原方向直方图未改变，未放宽优化内点或几何判据。

## 冻结候选 v1 的开发通过与独立失败

冻结记录 `frozen_candidate.json`，配置 SHA256 `6c5ccf776c2fdbf19ad39d8f9b3c8b7ce5bf6bd91d39d0a7ba4ad5f0f74f978e`。开发包三次完整回放均 1195/1195，第 136 帧 IMU 初始化，初始化后 OK=100%，末帧 OK，重置 0，满足开发标准。

独立包首轮 `E7_validation01_1`：第 255 帧 IMU 初始化，初始化后 OK=24.76%，6 次初始化前重置；处理 2222/2683 后地图切换将内部 Frame 清空，诊断叠图错误调用 resize(empty) 而退出 1。该失败没有删除或覆盖。第二轮 `E7_validation01_2` 完成 2683/2683，初始化后 OK=26.77%，末帧 RECENTLY_LOST，仍未通过，证明首轮诊断异常不是跟踪失败的根因。

独立包在帧 136/148/164/170/174/178 创建 30–39 点地图后均立即重置，帧 182 的 38 点地图进入长时间丢失。原 NeedNewKeyFrame 在 IMU 尚未初始化时只按 0.25 秒间隔插入关键帧，没有先检查 OK 状态；惯性初始化所用末关键帧时间对应输入帧 254（RECENTLY_LOST），首轮陀螺偏置估计约 (0.098,0.129,-0.103) rad/s，旋转残差仍很大。这是需要进一步受控验证的视觉 bootstrap 污染问题，不能声称惯性初始化成功就表示状态可信。

后续先验证三相机对的 50 点门槛（开发包首个满足点数的帧 196，独立包 197），保持其他设置不变。原前双目 50 点没有足够支持，并不代表三相机对的 50 点也无法初始化。另单独修复诊断空帧边界，增加直接对空 Frame 的 System 诊断测试，并在初始化后重新记录前五次丢失的前后叠图。

### E8 / E9：门槛与视觉 bootstrap 可靠性

E7 v1 独立包第三轮也失败：2683 帧完整处理，首次惯性初始化 255，初始化后 OK=13.14%，末帧 RECENTLY_LOST。v1 不作为交付候选。全部失败保留。

| 实验 | 开发初始化/初始化后 OK | 独立初始化/初始化后 OK | 解释 |
| --- | --- | --- | --- |
| E8 三对 50 点，原 bootstrap | 269 / 43.41% | 271 / 100% | 开发发生一次初始化后地图切换和初始化状态丢失；不能通过统一配置验收 |
| E9 三对 30 点，仅可靠 bootstrap 帧 | 136 / 100% | 727 / 100% | 不改变点数、噪声、偏移、优化或几何阈值 |

E8 的开发短回放在初始化后仅 6.45% OK，独立短回放在初始化后 100% OK；完整回放均执行。点数越高并非一定更好：门槛改变启动时段，开始建图时的运动、可匹配性及连续视觉对应同样重要。

源码明确证实 `NeedNewKeyFrame` 的初始化分支先按时间返回 true；`Track` 在 RECENTLY_LOST 状态下仍会请求插入，而未惯性初始化时该状态又不预测位姿，Frame 可以没有有效位姿。新增 `Multi.BootstrapRequireOK`（缺省关闭）显式要求初始化前状态 OK 且 HasPose；允许原行为作对照，初始化后的关键帧策略保持原行为。最小测试直接调用真实 Tracking::NeedNewKeyFrame：无位姿 OK 帧、RECENTLY_LOST 帧被拒绝，有有效位姿的 OK 帧仍允许；关闭开关可复现原宽松行为。加空 Frame 的真实 System 诊断调用，共 27/27 通过。

配组源检查：独立包 `max_group_skew_us=49.0`，约 0.049 ms，校正参考 cam0、参考转换残差 0；未发现需要修改相机时间偏移或相机槽位的证据，继续固定 +2631359 ns。

E9 保持 30 点，仅增加可靠 bootstrap 检查：开发 1195/1195、第 136 帧初始化、初始化后 OK=100%、重置 0；独立 2683/2683、第 727 帧初始化、初始化后 OK=100%、末帧 OK，9 次重置均在初始化前，初始化后没有重置/地图变化。独立初始窗口仍会失败并等待可靠地图，不能声称启动全过程无失败；完整输入窗口比例将单列。图像全部处理，没有跳过失败区段。

可靠检查之后，独立首次惯性初始化的旋转矩阵 Frobenius 残差 RMS 从优化前 0.00230 降至 0.00137，速度残差 0.15019→0.04160 m/s，位置残差 0.03466→0.00572 m；陀螺偏置约 (-0.00233,-0.00227,-0.00369) rad/s。与 v1 由不可靠视觉关键帧构建的图相比，这支持阻止 bootstrap 污染的修复依据，不构成绝对轨迹精度评价。事件审计中初始化前不存在 state!=OK 或 pose_valid=0 的关键帧插入尝试。

最终可靠检查同时拒绝没有位姿的帧，即使异步初始化标志刚改变；初始化后有有效位姿的关键帧策略保持原行为。真实 Tracking 最小测试也覆盖这个异步边界。


## 冻结候选 v2：六次完整复验

`frozen_candidate_v2.json` 保存冻结二进制、主动态库、依赖及配置哈希。使用 `E9B_binary`，修复配置 SHA256 为 `eead56b77c83e630452778bfb7d3e8f48b8ef52c07fc2c60b59766a00495e70f`。所有复验使用同一冻结二进制/库/配置，未在独立验证之间修改。帧号均从 0 开始，因此第 136 帧对应第 137 组输入。

| 运行 | 实际处理/输入 | IMU 初始化帧 | 初始化后 OK | 全窗口 OK 帧/比例 | 总/初始化后重置 | 轨迹/关键帧行数 | 验收 |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| E7_v2_debug_1 | 1195/1195 | 136 | 100.00% | 1133 / 94.81% | 0/0 | 1133/37 | PASS |
| E7_v2_debug_2 | 1195/1195 | 136 | 100.00% | 1133 / 94.81% | 0/0 | 1133/37 | PASS |
| E7_v2_debug_3 | 1195/1195 | 136 | 100.00% | 1133 / 94.81% | 0/0 | 1133/37 | PASS |
| E7_v2_validation01_1 | 2683/2683 | 727 | 100.00% | 2042 / 76.11% | 9/0 | 2030/46 | PASS |
| E7_v2_validation01_2 | 2683/2683 | 727 | 100.00% | 2042 / 76.11% | 9/0 | 2030/48 | PASS |
| E7_v2_validation01_3 | 2683/2683 | 727 | 100.00% | 2042 / 76.11% | 9/0 | 2030/45 | PASS |

六次运行均正常退出，末帧为 OK，地图数为 1，初始化后地图变化/初始化状态丢失为 0，最长初始化后非 OK 时段为 0 秒。轨迹数值有限且时间严格递增。开发包首次 IMU 初始化距首帧 4.533408 秒，在前 300 帧内；独立包为 24.233765 秒，9 次重置全部在 IMU 初始化前。输入完整处理，没有跳过失败区段。

每次 `imu_events.csv` 都有 1 条实际 `imu_initialized` 事件，关键帧事件中不可靠 bootstrap 插入尝试为 0。四路实际局部优化后内点累计及初始化后独立点中位数：

| 运行 | cam0 / cam1 / cam2 / cam3 优化后观测累计 | 独立地图点中位数 |
| --- | --- | ---: |
| E7_v2_debug_1 | 147000 / 187931 / 219008 / 190350 | 583 |
| E7_v2_debug_2 | 148510 / 192406 / 224903 / 196417 | 598 |
| E7_v2_debug_3 | 152644 / 193289 / 226022 / 197489 | 602 |
| E7_v2_validation01_1 | 300557 / 331522 / 505460 / 561766 | 770.0 |
| E7_v2_validation01_2 | 291273 / 325927 / 504166 / 566397 | 765.0 |
| E7_v2_validation01_3 | 289855 / 323241 / 494608 / 556028 | 755.5 |

观测累计包含同一个地图点在多帧/多相机的观测，不是独立三维点数。`diagnostics.csv` 分开记录运动模型、参考关键帧和局部地图阶段，`tracking_events.csv`、`imu_events.csv` 分别记录前端和异步初始化线程。`overlays/` 包含前 128 帧、初始化附近、首批丢失前后以及每 30 帧抽样；`match_stages.csv` 和 `match_candidates.csv` 保存各阶段淘汰原因。

全部 64 次已保存短/完整/GUI 实验的机器汇总为 `experiment_summary.csv`，v2 六次复验完整汇总为 `final_repeat_summary.json`；失败实验没有覆盖或删除。

### 前 128 帧的匹配支持复查

| 数据包 | cam0–cam1 通过中位数 | cam1–cam3 通过中位数 | cam0–cam2 通过中位数 |
| --- | ---: | ---: | ---: |
| 开发 | 3.0 | 15.0 | 4.0 |
| 独立 | 4.0 | 11.5 | 5.0 |

这些是各相机对三角化检查后的数量，合并跨对种子时还会去除共享特征重复和冲突，不能直接求和作为独立建图点。前双目几何匹配本身仍不足，E3 的真实失败与此一致；增加跨相机支持及质量门槛才使开发包可靠启动。并未放宽 ratio 或正深度门槛。

`match_stages.csv` 的 `no_geometry/ratio/hamming/mutual` 是按顺序首次拒绝原因，`parallax/negative_a/negative_b/reprojection_a/reprojection_b/invalid` 是进入三角化后的拒绝原因。`singleton` 统计通过绝对距离与双向检查、尝试三角化的单候选数量；仍须通过完整三角化才能成为 accepted。不能将这组经过更多前置筛选的比例直接与历史 67.33% 非正深度比例等同。

已核对代表运行前 128 张叠图齐全，初始化前后 ±5 帧共 11 张齐全，并查看开发包第 140 帧四路诊断叠图。绿色连接为接受的相机对匹配，暗红连接为抽样拒绝候选；绿色点为地图内点、红色点为优化外点、蓝色点为未关联特征，黄色短线显示投影到测量的误差。叠图用于诊断对应关系，不能作为绝对精度证明。

![两段数据前 128 帧的三对三角化通过数与合并后独立种子数](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/02_match_support.png)

**图 2：前 128 帧几何支持。** 固定选择最终候选各包第一次复验 `E7_v3_debug_1`、`E7_v3_validation01_1`，读取 `match_stages.csv` 的各对 `accepted` 和 `diagnostics.csv` 的 `rig_seeds`，未选择最优运行。彩色曲线为跨对合并前的三角化通过数，黑线为合并、去重后的独立种子，不能把三条彩色曲线之和当作独立点数。30 点线仅表示点数门槛，还须通过空间覆盖和后续可靠 bootstrap 检查。独立包前 128 帧没有达到点数门槛，图中保留这一启动等待。

![开发包第 136 帧首次 IMU 初始化时的原始四目诊断叠图](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/03_debug_initialization.jpg)

**图 3：开发包首次 IMU 初始化帧的四目对应。** 来源为 `E7_v3_debug_1/overlays/frame_136.jpg`，即第 137 组输入、距首帧 4.533408 秒。按上述颜色口径显示匹配、地图观测及投影误差。图像为程序保存的诊断叠图，并非 GUI 截屏；直接复制原 JPEG 字节，未裁剪或调整颜色。

![独立包第 727 帧首次 IMU 初始化时的原始四目诊断叠图](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/04_validation_initialization.jpg)

**图 4：独立包首次 IMU 初始化帧的四目对应。** 来源为 `E7_v3_validation01_1/overlays/frame_727.jpg`，即第 728 组输入、距首帧 24.233765 秒。同样直接复制原 JPEG，按首次实际 IMU 初始化帧选取，不以画面质量挑帧；此前失败与重置区段见图 5。

## GUI 退出失败及单独修复

`GUI_v2_debug` 使用相同 v2 候选，`--viewer --realtime` 连接 DISPLAY=:1。实际处理 1195/1195，136 帧 IMU 初始化，初始化后 OK=100%，末帧 OK，重置 0，轨迹 1133 行、关键帧 39 行。日志 `Starting the Viewer` 位于 Pangolin/OpenCV 窗口创建之后，证明进入了真实 GUI 链路。但程序在最终退出时 SIGSEGV（exit_code=-11），故 GUI 验收为 NOT_PASSED，保留全部结果。

5 帧最小回放 `GUI_shutdown_gdb` 重现：Viewer 线程仍在创建 Qt 窗口，主线程已开始 dlclose 图形库；`GUI_shutdown_gdb.log` 保存各线程堆栈。源码 `System::Shutdown` 的 Viewer 退出等待被注释。修复将请求 Viewer 退出、由创建线程销毁窗口，并在外部调用 Shutdown 时 join；Viewer 的 Stop 菜单调用 Shutdown 时避免 join 自身，暂停循环也检查结束请求。这个修复不改变匹配、建图或优化，但需要真实 GUI 退出复验。


### GUI 修复后真实验证

| 验证 | 实际处理 | 退出状态 | IMU 初始化 | 初始化后 OK | 说明 |
| --- | ---: | ---: | --- | --- | --- |
| E10_GUI_5 | 5 | 0 | 无 | 无 | 退出早于窗口创建也能等待 Viewer 正常结束 |
| E10_GUI_300 | 300 | 0 | 136 | 100% | 短回放，不单独作为完整验收 |
| ASan_GUI_5 | 5 | 0 | 无 | 无 | ASan/UBSan 无错误，Qt 全局对象退出仍有定时器警告 |
| GUI_v3_debug | 1195 | 0 | 136 | 100.00% | PASS，完整 GUI 回放及正常退出 |

最终 GUI：末帧 OK，重置 0，初始化后地图变化/初始化丢失均为 0，轨迹 1133 行、关键帧 39 行；有限且严格递增。日志同时记录 `Starting the Viewer` 和 `Viewer finished`。`--realtime` 仅在处理快于输入间隔时等待；本机墙钟 95.94 秒，输入时长 39.800697 秒，TrackMulti 耗时中位数 46.54 ms，不能宣称达到 30 FPS。普通 GUI 与 ASan GUI 的进程退出阶段仍有 Qt 定时器跨线程销毁警告；退出状态为 0，没有再发生崩溃。没有人工操作菜单或进行画面质量评估。

## 最终候选 v3 全部验收

源码提交 `dc5521b`，冻结记录 `frozen_candidate_v3.json`。以下六次使用同一最终二进制/主库/依赖/配置，初始化后均 100% OK，末帧 OK，无初始化后重置、地图变化或初始化丢失，最长初始化后非 OK 时段 0 秒、地图数 1。完整 GUI 同候选也正常退出并通过。

| 运行 | 处理/输入 | 初始化帧 | 全窗口 OK 帧/比例 | 总/初始化后重置 | 轨迹/关键帧行数 | 验收 |
| --- | --- | ---: | --- | --- | --- | --- |
| E7_v3_debug_1 | 1195/1195 | 136 | 1133 / 94.81% | 0/0 | 1133/38 | PASS |
| E7_v3_debug_2 | 1195/1195 | 136 | 1133 / 94.81% | 0/0 | 1133/40 | PASS |
| E7_v3_debug_3 | 1195/1195 | 136 | 1133 / 94.81% | 0/0 | 1133/41 | PASS |
| E7_v3_validation01_1 | 2683/2683 | 727 | 2042 / 76.11% | 9/0 | 2030/51 | PASS |
| E7_v3_validation01_2 | 2683/2683 | 727 | 2042 / 76.11% | 9/0 | 2030/47 | PASS |
| E7_v3_validation01_3 | 2683/2683 | 727 | 2042 / 76.11% | 9/0 | 2030/50 | PASS |

初始化后的四路优化观测也逐项核对，证明四目实际参与优化，而不是仅加载图像：

| 运行 | 初始化后 cam0 / cam1 / cam2 / cam3 优化观测累计 | 独立地图点中位数 |
| --- | --- | ---: |
| E7_v3_debug_1 | 143564 / 183164 / 215434 / 185804 | 583 |
| E7_v3_debug_2 | 147797 / 185544 / 227243 / 185957 | 605 |
| E7_v3_debug_3 | 143141 / 181841 / 217531 / 190847 | 594 |
| E7_v3_validation01_1 | 287641 / 319784 / 496077 / 547333 | 754.0 |
| E7_v3_validation01_2 | 293383 / 324586 / 503822 / 566295 | 782.0 |
| E7_v3_validation01_3 | 297135 / 329833 / 510029 / 564678 | 778.0 |

六次各有实际 imu_initialized 事件，不可靠 bootstrap 关键帧尝试为 0；逐帧索引完整，图像偏移只应用一次，轨迹有限且时间严格递增，四元数单位范数误差小于 1e-5。各次前 128 帧和初始化 ±5 帧叠图齐全。详细汇总 `final_repeat_summary_v3.json`，交付独立核对 `final_acceptance_audit.json`。

结果绝对目录：`/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/`。每次目录保留 provenance.json、input_summary.json、settings.yaml、preparation.json、calibration_provenance/、working-tree.patch、build_provenance.json/build.patch/build_source_snapshot/、run.log、frames.csv、diagnostics.csv、tracking_events.csv、imu_events.csv、match_stages.csv、match_candidates.csv、overlays/、轨迹和 summary.json。v1/v2 失败结果原样保留。

![开发包和独立包完整输入窗口的失败对照与最终三次复验状态时间线](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/05_tracking_timeline.png)

**图 5：包含启动阶段的完整跟踪状态。** 读取每帧 `frames.csv`，开发对照为预先固定的第一轮射线基线 `E0_rays_1`，独立对照为完成全部输入但失败的 v1 第二轮 `E7_validation01_2`；v1 首轮在 2222 帧诊断异常退出，故没有作为完整时间线对照。每包另展示最终 v3 的全部三次复验，未截掉启动阶段。三角标记为首次 IMU 初始化，短竖线为重置计数增加；左侧比例是完整输入窗口 OK 比例。开发包最终全窗口为 94.81%，独立包为 76.11%，与初始化后 100% OK 的统计窗口不同。独立包约 24.23 秒才完成 IMU 初始化，9 次重置均在此前。

![最终候选各相机局部优化后观测与帧末独立地图内点时间曲线](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/06_camera_support.png)

**图 6：四路实际优化观测支持。** 固定读取最终各包第一次复验从首次 IMU 初始化起的 `diagnostics.csv`。彩色曲线为局部地图阶段 `local_after_cam0–3`，黑线为帧末 `unique_inliers`，二者统计对象不同；一地图点可有多路观测，不能直接求和比较。未执行阶段的负值保留为缺口，没有填成 0；所有曲线保留原始逐帧值，没有平滑。四路均持续提供优化后观测，轨迹精度仍须另行对真值评估。

## 最终源码、测试与构建

确定的修复包括四路各自投影模型与窗口、独立可见性搜索；全局/局部特征索引、观测幂等、最后观测删除和参考相机距离；零角速度及小角积分的有限极限；重置空帧时间和预积分边界；Viewer 退出生命周期。可选算法扩展为标定射线极线候选、双向一致/一对一匹配、跨相机统一种子、初始化独立点与空间覆盖门槛、可靠视觉 bootstrap。

四路投影使用各自内参/外参的合成测试，真实四相机优化恢复合成位姿，三角化相机变换方向和 KB4 有效射线往返均通过；未改变标定模型的反投影实现。保留 ratio=0.8、绝对 Hamming=50、原视差、正深度和重投影门槛，方向直方图保持原行为。原 YAML 保留，实验通过显式选择修复配置；投影确定性修复默认启用，其余算法开关默认关闭。

- `E10_tests.log`：27/27，包含真实 Tracking bootstrap 边界和 System 空 Frame 诊断。
- `asan_gui_tests.log`：27/27，ASan/UBSan 检查主库及回归程序；`ASan_GUI_5/run.log` 增加真实 GUI 生命周期检查。依赖库没有整体插桩；`ASAN_OPTIONS=detect_leaks=0`，不构成上游进程生命周期对象的泄漏清理证明。
- `E10_input_summary_tests.log`：21/21，覆盖四路时间不一致、缺/坏图、重复时间、空输入、IMU 提前结束/零/单样本、偏移一次应用，以及退出/重置/地图切换/真实初始化证据/四路优化观测/开发初始化期限的验收规则。
- `E10_build.log`：新入口、原四目入口和回归程序均构建通过。主工程 C++14，所需 g2o/DBoW2 沿用专用构建链。
- 拆分诊断和确定修复的中间提交：`commit_compile_diagnostics/compile.log` 与 `fixes_compile.log` 额外检查 Frame/Tracking/System/ORBmatcher/回归源文件的编译兼容性；这些是编译检查，不是再次完整回放。

最终二进制：`/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/E10_binary/Examples/Multi-Inertial/multi_inertial_prepared`。原根目录可执行文件和动态库仍为历史构建；运行修复配置必须使用这里的最终二进制，或按下面命令重新构建。

冻结记录 `frozen_candidate_v3.json` 对应源码提交 `dc5521b`，所有编译源文件哈希已与提交后的文件逐项比对一致。构建时 HEAD 是 a46f14c，构建记录同时保存完整源码快照和工作区差异，因此不以旧 HEAD 单独认定二进制版本。每次新回放另外记录当前提交、编译源码快照及二进制/依赖哈希。

## 可复制命令

构建到新目录；词典存在时不重复解压，默认 4 个编译任务：

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
REPAIR_REPO="$PWD"
REPAIR_BUILD="$PWD/results/layout0921_repaired_$(date +%Y%m%dT%H%M%S)_binary"
OUTPUT_ROOT="$REPAIR_BUILD" JOBS=4 bash scripts/build_prepared.sh
REPAIR_BIN="$REPAIR_BUILD/Examples/Multi-Inertial/multi_inertial_prepared"
REPAIR_SETTINGS="$PWD/Examples/Multi-Inertial/OAK4P_layout0921_repaired.yaml"
OPENMAVIS_TEST_BINARY="$REPAIR_BIN" python3 -m unittest scripts.test_prepared scripts.test_summary -v
git diff --check
```

开发包短/全量回放。包装器默认准备包为计划中的 debug 包，偏移为 +2631359 ns；不指定输出时生成新运行目录，指定已存在目录会拒绝覆盖：

```bash
python3 scripts/run_prepared.py --binary "$REPAIR_BIN" --settings "$REPAIR_SETTINGS" --diagnostics --max-frames 300
python3 scripts/run_prepared.py --binary "$REPAIR_BIN" --settings "$REPAIR_SETTINGS" --diagnostics --max-init-frame 299
```

独立验证（没有开发包的前 300 帧初始化期限）：

```bash
python3 scripts/run_prepared.py   --binary "$REPAIR_BIN" --settings "$REPAIR_SETTINGS" --diagnostics   --dataset /home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_173131_635018_DOHC2_validation_01/run_20260922T104634_12bfae/01_preparation/dataset
```

GUI 实时模式，在可连接当前桌面的终端执行：

```bash
python3 scripts/run_prepared.py --binary "$REPAIR_BIN" --settings "$REPAIR_SETTINGS" --diagnostics --viewer --realtime --max-init-frame 299
```

真实 System/Tracking 的 27 项回归，需要新工作目录保存测试事件：

```bash
mkdir "$REPAIR_BUILD/test"
cd "$REPAIR_BUILD/test"
"$REPAIR_BUILD/Examples/Multi-Inertial/multi_regression" --empty-frame-diagnostics "$REPAIR_REPO/Vocabulary/ORBvoc.txt" "$REPAIR_SETTINGS"
cd "$REPAIR_REPO"
```

## 轨迹与验收口径

逐帧 `frames.csv` 中 `raw_ns`、`corrected_ns` 为整数纳秒，图像时间只加一次 2631359 ns。`trajectory_body.txt` / `keyframes_body.txt` 的格式为 `timestamp_s tx ty tz qx qy qz qw`，时间是校正后的设备时钟秒，不是 Unix 时间或纳秒。根据实际导出实现，位姿方向为 IMU/body 到参考世界坐标系：全帧轨迹以最大地图第一关键帧 body 为原点，关键帧轨迹使用该最大地图自身世界坐标系；直接叠加两文件前需要统一参考系。

原导出器选择关键帧数最多的地图，并跳过标记 LOST 或属于其他地图的帧。RECENTLY_LOST 在已初始化时可能保留惯性预测位姿，也可能沿用参考位姿；不能把导出行数当作成功视觉跟踪帧数。开发包 1195 个处理帧、1133 个 OK 帧、1133 个导出行；独立包 2683 个处理帧、2042 个 OK 帧，但最大地图导出 2030 行，因为部分 OK 帧属于随后重置的启动地图。初始化后的有效跟踪比例与完整输入窗口比例分别报告。

![两段数据最大地图的 IMU body 轨迹 XY 投影，不包含真值对齐](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/07_trajectory_xy.png)

**图 7：导出轨迹的 XY 投影。** 读取最终各包第一次复验的 `trajectory_body.txt`，绘出全部 1133 / 2030 行，轴单位为米且 X/Y 等比例。两段分别使用各自最大地图第一关键帧 body 为原点的参考系，没有彼此对齐，也没有 mocap 对齐；XY 投影不等同于重力对齐的俯视图。相邻导出时间差超过中位帧间隔的 1.5 倍时不连线，避免跨缺失区段制造连续轨迹。该图只展示已导出的位姿形状，不证明绝对精度。

## 配图来源与复现

配图目录为 `results/repair_20260930T142226/report_figures_v2/`。统计图同时保存 PNG（180 dpi）和 SVG；两张诊断 JPEG 与源文件 SHA256 完全相同。绘制时核对逐帧索引及时间递增、轨迹有限性，逐张检查图例、中文标签和比例。首次绘制目录 `report_figures/` 也保留，第二次只调整图例位置与对照标签，没有改变数据。

绘图脚本：[plot_layout0921_repair_validation.py](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/scripts/plot_layout0921_repair_validation.py)。[配图清单与输入哈希](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/figure_manifest.json) 保存脚本哈希、每个输入文件哈希、输出尺寸/哈希、字体及依赖版本；[图中数值](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2/figure_data.json) 保存原始实验点和曲线计数。配图为已保存实验的重新展示，没有新增回放、算法修订或精度验收。

[配图核对记录](/home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS/results/repair_20260930T142226/report_figures_v2_audit.json)：7 个报告图片链接均可读取，38 个输入哈希和 12 个图像/SVG 输出哈希核对一致；匹配中位数、六次复验帧数/状态/重置、四路优化观测累计及轨迹行数与上述表格一致。已存在输出目录的运行被拒绝，清单未被覆盖；原实验输入未改变。`git diff --check` 通过。

本次使用独立临时绘图环境 `/tmp/openmavis-report-plot-20260930/bin/python`，Matplotlib 3.10.6、NumPy 2.2.6、Pillow 11.3.0，没有修改 SLAM 运行环境。复现时可将 `REPAIR_PLOT_PYTHON` 替换为安装这三项依赖的 Python；默认中文字体为 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`，可用 `--font` 指定。输出目录已存在时明确拒绝覆盖：

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
REPAIR_PLOT_PYTHON=/tmp/openmavis-report-plot-20260930/bin/python
REPAIR_FIGURES="$PWD/results/repair_20260930T142226/report_figures_$(date +%Y%m%dT%H%M%S)"
MPLCONFIGDIR=/tmp/openmavis-report-mpl-cache "$REPAIR_PLOT_PYTHON" scripts/plot_layout0921_repair_validation.py \
  --experiment-root "$PWD/results/repair_20260930T142226" --output "$REPAIR_FIGURES"
```

生成图像及清单仍放在被忽略的 `results/`，不加入版本控制。报告图片使用本机绝对路径，移动或分享文档时需一并携带配图并改写链接。

## 保留的限制

独立包仍有约 24.23 秒的 IMU 初始化等待和 9 次初始化前重置；最终方案阻止不可靠视觉关键帧污染惯性初始化，但没有消除所有启动失败。这不违反本轮独立包的验收门槛，仍应作为后续启动鲁棒性问题保留。没有跳帧、缩短输入、改变噪声/时间标定或放宽优化阈值。

本轮证明这两段数据上的完整四目惯性回放和所定义的初始化后连续跟踪，不构成 mocap 绝对精度或其他场景泛化证明。GUI 窗口链路、完整回放与正常退出已实际执行；菜单交互未验证，普通 GUI 和 ASan GUI 中的 Qt 全局对象退出警告仍保留。


## 提交整理

沿用原分支和 a46f14c 之前的全部提交，没有重写已有历史：

| 提交 | 内容 |
| --- | --- |
| 06d3947 | 四路阶段诊断、事件/叠图、运行来源与构建快照、针对性测试工具 |
| 63d00ae | 投影模型/搜索窗口、观测索引与计数、IMU 小角积分和重置时间边界修复 |
| 3283eb4 | 几何候选、跨相机统一种子、初始化质量及可靠 bootstrap，可选修复配置 |
| dc5521b | GUI 窗口和 Viewer 线程正常退出 |

计划与验证记录另作文档提交。所有结果、图像叠图、构建目录和二进制均由 .gitignore 排除，没有加入版本控制；不推送、不合并。

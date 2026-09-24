# Layout0921 配组数据适配与真实回放验证记录

## 结论

日期：2026-09-23。分支：`codex/openmavis-layout0921-prepared`。

**配组入口已适配，完整回放可执行；连续跟踪验收未通过。** 两次完整运行均处理 1195/1195 组、进程退出 0、完成 IMU 初始化并输出有限且时间递增的轨迹。最佳对照的初始化后 OK 比例为 58.15%，低于 95%，最终状态仍是 RECENTLY_LOST，因此运行脚本返回 2，不能宣称稳定跑通或精度合格。

未修改原始数据、Basalt 历史结果或源标定 JSON，未自动提交、合并或推送。未执行 GUI 或 mocap 精度评估。

## 实现与已通过验证

- 主工程统一 C++14，解决本机 Pangolin/sigslot 对 C++11 的编译错误；新入口、原四目入口和相机审计工具均构建成功。
- 修复 YAML 四个闭合括号缩进，Camera.fps 使用整数 30，Camera.RGB=0；内外参和 IMU 数值未改变。OpenCV 实际读入成功，首张图为 1280×800 三通道。
- JSON/YAML 数值核对最大误差小于 5e-13；T_b_c 为相机到 IMU，Stereo.T_c1_c2 为 inverse(T_b_c1)*T_b_c2。
- 配组输入为 1195 组、4780 张图像链接、20219 条 IMU。全量 validate-only 完成实际解码。四路 CSV 同步、单调、等长，cam2 多出的末帧已由 Basalt 准备阶段排除。
- 整数纳秒索引保留，图像时间加 2631359 ns 后送入 SLAM；所有完整回放逐帧检查均满足偏移恰好一次、IMU 提交不重复且包含帧末边界。
- 10 项输入测试覆盖有效输入、四路时间不一致、重复图像时间、缺图、坏图、IMU 提前结束、空 CSV、非有限 IMU、重复 IMU 时间和目录覆盖保护。
- 6 项汇总测试覆盖通过情形、末帧丢失、同地图重置、重复时间偏移、重复 IMU 提交和未初始化，防止只靠退出码判定成功。
- 相机审计使用实际 Frame 构造器，验证过滤前后描述子数量与关键点数量一致、双目匹配索引不越界，过滤后的首帧射线均通过 2 px 往返检查。

## 真实回放结果

| 指标 | 基线短回放 | 基线完整回放 | 有效射线过滤完整对照 |
| --- | ---: | ---: | ---: |
| 处理帧组 | 300 | 1195 | 1195 |
| IMU 首次初始化帧号（从 0 开始） | 201 | 201 | 201 |
| 初始化后 OK 比例 | 23.23% | 6.54% | 58.15% |
| 初始化后地图切换 | 0 | 2 | 0 |
| 初始化后实际重置计数 | 初版未记录 | 初版未记录 | 0 |
| 日志中的重置事件总数 | 42 | 49 | 42 |
| 最大地图数 | 1 | 3 | 1 |
| 最长初始化后非 OK 时段 | 0.467 s | 5.100 s | 1.767 s |
| 最终跟踪状态 | 3 | 3 | 3 |
| 导出帧轨迹行数 | 172 | 614 | 1067 |
| 导出关键帧行数 | 16 | 46 | 76 |
| 进程退出码 | 0 | 0 | 0 |
| 验收 | 仅短回放 | 未通过 | 未通过 |

初始化出现在序列约 6.700111 秒。状态 2=OK，3=RECENTLY_LOST。导出帧数不等于 OK 帧数：原导出器按内部 lost 标记及最大地图筛选，RECENTLY_LOST 时仍可能保存传播位姿。

结果目录（均位于本仓库 results，已忽略）：

- `layout0921_20260923T193827_b42fb3`：300 组短回放。
- `layout0921_20260923T193945_64dc56`：首次完整基线，未启用过滤。
- `layout0921_20260923T194814_c8b94a`：完整过滤对照，包含新增 resets/stereo_matches/inliers 诊断。

每个目录保存日志、逐帧 CSV、输入统计、配置副本、准备来源、工作区补丁、命令/版本/哈希、汇总和轨迹。初版运行记录无 resets 列，不能用 map_id 不变推断没有重置；对照版本通过 Tracking 的实际重置函数累计计数。新脚本还保存源文件快照及共享库哈希；新增溯源字段不追写历史记录。

轨迹为 `timestamp_s tx ty tz qx qy qz qw`，时间已校正到 IMU 时基，位姿为 body→world。trajectory_body 以最大地图首关键帧 body 原点重置参考；keyframes_body 保留该地图原始世界坐标。二者不能未经变换直接混合比较。基线最大地图只覆盖部分序列。

## 已定位的问题与对照边界

首帧特征的 OpenMAVIS 反投影/投影往返误差：

| 相机 | 过滤前特征数 | 大于 2 px 的特征数 | 最大误差 | 过滤后无效数 |
| --- | ---: | ---: | ---: | ---: |
| cam0 | 1004 | 55 | 1291.92 px | 0 |
| cam1 | 1005 | 65 | 1330.54 px | 0 |
| cam2 | 2010 | 295 | 1297.70 px | 0 |
| cam3 | 2006 | 223 | 1306.38 px | 0 |

增加可关闭的 `Camera.filterInvalidRays: 1`：在匹配前过滤第一单调前向 KB4 分支以外、离边界不足约 2 px 或往返误差大于 2 px 的特征，同步压缩描述子和重叠区索引。它不修改标定、不重编码图片、不改变优化阈值。基线配置保持默认关闭，单独的 `OAK4P_layout0921_valid_rays.yaml` 用于对照；这不是对原 KB4 unproject 的全面修复。

过滤后首帧最大往返误差小于 0.00017 px，但前双目三角化匹配仍只有 2 个。对照前 128 组的三角化匹配中位数为 4，最大 13；初始化后非 OK 帧的内点中位数仅 4。源码 `ComputeMultiFishEyeMatches` 仅对前双目三角化，不利用侧目与前目重叠建立初始深度；`MultiInitialization` 主要以总特征数大于 500 作为入口条件，因而能在极少初始地图点时建立地图并很快失败。`TrackLocalMap` 在 IMU_MULTI 常规路径要求至少 15 个内点，另有恢复分支和重定位门限。

因此已定位到有效地图点/内点不足，不能以“提取了几千个特征”替代几何可用性判断。过滤改善了这次运行的连续性，但不能解释或解决全部失败；每个配置只跑了一次，异步局部建图调度也可能影响结果，不作严格单因素因果或精度结论。

后续要达到 95% 目标，需要单独研究前双目重叠内匹配的几何支持和跨相机三角化初始化，必要时修正模型有效域处理；本次没有降低初始化/跟踪门限，没有隐去丢失或自动将实验配置设为默认。

## 可复制命令

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OpenMAVIS
bash scripts/build_prepared.sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/run_prepared.py --max-frames 300
python3 scripts/run_prepared.py
python3 scripts/run_prepared.py --settings Examples/Multi-Inertial/OAK4P_layout0921_valid_rays.yaml
```

脚本默认使用计划中的准备目录和 2631359 ns。完整回放返回 2 表示进程完成但连续性验收未通过；应读取 summary.json，不把它当作编译或输入失败。

```bash
DATASET=/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b/01_preparation/dataset
Examples/Multi-Inertial/prepared_camera_audit Examples/Multi-Inertial/OAK4P_layout0921.yaml "$DATASET"
git diff --check
```

构建/测试/相机审计/输入校验日志另存于 results/implementation_validation_20260923。已有 GCC/Eigen 弃用及上游警告仍存在；本次未进行广泛清理。所有结果仅证明实际执行及上述局限，不构成绝对精度、GUI 或其他数据集泛化验证。

# 配送匹配：自写价格引导 LNS 求解器

从候选 `(订单组合, 骑手, 成本)` 中选择若干行，让每个订单恰好被覆盖一次、每个骑手最多使用一次，并最小化总成本。

**核心求解器只有一份 C++ 实现，不调用任何现成 LP/MIP、匹配或其他优化求解库。** Python 仅使用标准库，负责跑批、测试和独立验证。原来的多求解器骨架、SciPy/HiGHS 探索入口和过时测试已移除。

算法是：全局拉格朗日价格引导邻域选择，局部有预算的分支限界联合重建订单组合与骑手，周期性进行固定分区下的全局骑手重匹配。

- [完整算法推导与逐步示例](docs/algorithm.md)：从价格的来源讲到每个 DFS 节点的下界。
- [实验与复现口径](docs/experiments.md)：正式版单轮结果、历史最好结果、时间和审计。
- [独立学习与比赛入口](docs/learning.md)：AHC、博弈 AI，以及与 AlphaGo/AlphaZero 的区别。

## 1. 先运行一个小例子

需要支持 C++11 的 GCC/Clang，以及 Python 3.10+。直接运行 C++ 不需要 Python。

```bash
git clone https://github.com/xincy22/delivery-experiments.git
cd delivery-experiments
make
mkdir -p outputs/toy

.build/native_lns tests/data/toy_case.tsv outputs/toy/solution 2 1 100 descent
python3 verify.py tests/data/toy_case.tsv outputs/toy/solution
```

小例子的最优成本是 **4.5**。输出前缀必须是新的；重新运行时换一个目录，避免把旧输出误认作新运行结果。

```text
outputs/toy/
├── solution.tsv       # 真正选中的原始候选行
├── solution.json      # 成本、时间、搜索次数和下界
└── solution.dual.tsv  # 订单/骑手价格证书，可对全量原始数据独立检查
```

运行测试：

```bash
make test
# Python 不在默认路径时，例如使用自己的虚拟环境：
make test PYTHON=/path/to/python
```

`make sanitize` 额外启用 AddressSanitizer/UndefinedBehaviorSanitizer，需要支持这些选项并带相应运行库的较新编译环境；不是求解器的运行依赖。

## 2. 获取正式数据

`Case/case1.tsv` 至 `case9.tsv` 使用 Git LFS，总数据约 1.5 GB。没有取回对象时，文件可能只有三行指针，不能直接当输入。

安装 Git LFS 后：

```bash
git lfs install
git lfs pull
python3 scripts/fetch_cases.py --verify-only
```

没有 Git LFS 时，也可用仅依赖 Python 标准库的下载脚本取回同一批对象：

```bash
python3 scripts/fetch_cases.py
# 只取一个：
python3 scripts/fetch_cases.py --cases case4
```

脚本按 [`Case/manifest.json`](Case/manifest.json) 检查原对象字节数和 SHA-256，不会覆盖校验失败的非指针本地数据。原输入为无表头 TSV：

```text
1,3,7<TAB>42<TAB>18.6
1,3,7<TAB>51<TAB>21.2
```

订单组合中的整数排序不影响含义；同一个组合允许有多条骑手候选。原始行 ID 从 0 开始，按非空行计数。当前实现使用有符号 32 位外部订单/骑手 ID，单个 bundle 最多 60 个订单；全局订单数并不受 60 限制。

## 3. 正式版实测结果

本表来自 **2026-09-17 对当前发布源码的重新运行**：统一 `descent`、seed=1、全局定价上限 200 次、每 case 120 秒软预算。每个求解器进程单 CPU 线程，跑批同时运行 3 个 case，没有使用 GPU。

| Case | 参考成本 | 正式版成本 | 参考 gap | 最好值发现时间 | 总运行时间 |
|---|---:|---:|---:|---:|---:|
| case1.tsv | 5213.8791 | 5225.172495606 | 0.216603% | 85.59 s | 120.04 s |
| case2.tsv | 5723.3037 | 5729.794994999 | 0.113419% | 71.78 s | 120.49 s |
| case3.tsv | 5714.9039 | 5717.779358382 | 0.050315% | 43.62 s | 120.01 s |
| case4.tsv | 5857.9170 | 5874.020865362 | 0.274908% | 94.56 s | 120.16 s |
| case5.tsv | 1157.0484 | 1157.048410781 | 约 0 | 32.93 s | 120.05 s |
| case6.tsv | 519.3340 | 519.334043330 | 约 0 | 32.07 s | 121.10 s |
| case7.tsv | 641.2691 | 641.269052230 | 约 0 | 10.01 s | 120.22 s |
| case8.tsv | 445.3444 | 445.344435677 | 约 0 | 20.59 s | 120.64 s |
| case9.tsv | 513.4898 | 513.489824847 | 约 0 | 44.00 s | 120.08 s |

**最大参考 gap 为 0.274908%，算术平均为 0.072807%；9 个解和全数据对偶证书全部通过独立验证。** 表中 case5–9 的“约 0”仅表示成本四舍五入到四位小数与参考一致，不宣称已经证明严格整数最优；case7 因参考值舍入而出现很小负 gap，也不是证明超过真正最优。

本次正式版没有复现历史多轮逐 case 最好表中的全部数值。历史探索最大 gap 为 0.126075%、平均为 0.035650%，来自不同版本、种子和预算的 26 次运行，单独放在 [`results/historical`](results/historical)。那不是当前正式版单次运行的成绩。

完整实际方案、证书、日志、参数、源码快照和审计结果保存在 [`results/release-20260917`](results/release-20260917)，而不是只有一张手写表。

## 4. 跑一个 case 或整套实验

原生位置参数：

```bash
.build/native_lns CASE.tsv OUTPUT_PREFIX [seconds=120] [seed=1] \
    [pricing_rounds=200] [mode=descent] [max_iterations=-1]
```

例如：

```bash
mkdir -p outputs/case4-run
.build/native_lns Case/case4.tsv outputs/case4-run/solution 120 1 200 descent
python3 verify.py Case/case4.tsv outputs/case4-run/solution
```

跑全部 case，并独立验证每次输出：

```bash
python3 benchmark.py \
    --output-dir outputs/benchmark-run1 \
    --time-limit-sec 120 --seed 1 --mode descent \
    --pricing-rounds 200 --workers 3 --verify
```

只跑部分 case：

```bash
python3 benchmark.py --cases case1 case4 \
    --output-dir outputs/two-cases --time-limit-sec 120 --verify
```

`benchmark.py` 会按源码和编译参数的内容哈希缓存编译结果。`--repeats 3` 会运行三个种子：指定 seed、seed+1、seed+2；每次结果分别保存，不会只留下最好的一次。输出目录必须为空或尚不存在。

参考成本只由跑批/报告层读取，**原生求解器不读取 `Optimal objectives.tsv`、历史方案、历史对偶或外部求解器产物**。

## 5. 怎样理解算法

起点是单订单分区。无法匹配到真实骑手的订单暂时使用高罚价人工骑手，使扩展问题有一个明确起点；人工行全部消失后才得到原问题可行解。

全局价格不是把真实成本改掉。订单价格 $\pi_o$ 与骑手价格 $\mu_r$ 给每条候选一个余量：

$$
rc_j=c_j-\sum_{o\in S_j}\pi_o-\mu_{r_j}.
$$

它用于挑选值得拆除的旧行和值得尝试的替代 bundle，进而形成一块订单/骑手冲突闭合的邻域。全局价格在 LNS 之前计算一次；局部修复另外计算自己的价格来剪枝。

每次修复最多释放 60 个订单，枚举区域内所有合法原始行，用位掩码、候选最少优先和动态骑手下界做分支限界。局部修复同时决定订单组合与骑手，不只是给固定分区换骑手。每 30 次 LNS 再对全局当前分区做一次最优骑手重匹配。

有三种模式：`descent` 只接受改进；`annealed` 偶尔允许小幅变差；`directed` 进一步尝试强制插入低余量候选。**更复杂模式不保证更好**，默认采用容易理解和比较的 `descent`。

完整公式、手算例子、下界证明、搜索步骤与函数映射见 [算法文档](docs/algorithm.md)。

## 6. 保证与不保证

结果必须由真实原始行组成，满足全部订单/骑手约束。`verify.py` 会重新扫描全部输入，检查每一条对偶约束，而不是只检查被选中的行。

当独立校验通过且下界 $L>0$，方案成本为 $C$ 时，$(C-L)/L$ 是相对真正最优值的 gap 上界；本项目使用浮点算术和明确容差，不是有理数形式化证明。

外层 LNS 没有全局最优保证。局部 B&B 有节点和时间上限，未搜完时也没有邻域最优保证。找不到真实可行解会返回失败，不能解释为证明原问题不可行。新实例也不保证在某个预算内达到 5%。

`runtime_sec` 包含输入解析、定价、初始化和搜索，不含编译和审计；`first_feasible_sec`、`best_found_sec` 分别记录首次可行和最终最好值的发现时刻。所有时间预算均为软限制，固定种子的限时搜索也可能因环境、负载和检查时机而走出不同轨迹。

## 7. 仓库结构

```text
solvers/native_lns.cpp   唯一自写求解器
benchmark.py            编译、跑批和参考成本评价
verify.py               不依赖求解器的全量验证
scripts/fetch_cases.py  原始 LFS 对象下载与校验
tests/                  小实例穷举对照、非法输入、输出与入口测试
Case/                   原始数据指针、参考值与哈希清单
docs/algorithm.md       完整算法说明
docs/experiments.md     实验与复现口径
docs/learning.md        独立学习路线和官方比赛入口
results/                已保存的方案、证书、日志和汇总
```

这仍然是算法实验项目，不是可插拔求解框架。没有 registry、adapter、跨 solver 依赖，也不维护已经删除的旧 solver API。

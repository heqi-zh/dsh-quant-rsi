# DSH 三插件实测与运行

使用项目内安装的 DSH `0.2.1-rc.2`，没有安装或修改同级参考仓库。Node 24+、pnpm 11、Python 3.12+；会话证据核验脚本使用 Node 24 的 Zstd API。首次安装见 [README](../README.md#首次配置)。

```bash
cd dsh-quant-rsi
python3 scripts/setup-dsh.py
python3 scripts/run-research.py --snapshot cf7f626a9fde7b73baf406ad3fc7f4938b546be65f527918888e0e73d13dab07 --rounds 3
```

如果 Node／pnpm 不在 PATH，脚本会检查 Codex 桌面自带运行时；也可显式传入 `--node`、`--pnpm`。首次 setup 下载锁定依赖，编译 TypeScript，并通过标准 `dsh plugin` 将本地工具包接入独立的 `dqr-research` profile。重复 setup 不重置已有 profile。

当前入口默认最多3轮，`--rounds` 可减小额度，`--timeout` 可缩短300秒时限。`--parent-trial <id>` 从历史候选继续；不传则从当前策略开始。总历史额度仍按同一数据和固定评测累计，不能用新运行清零。

## 多轮执行边界

- `configs/research.json`：累计6次、单次最多3轮／300秒、连续失败2次停止、连续未改善2轮停止。先前已用2次计入累计额度，评测文件与门槛未改。
- `research.json` 在模型启动前固定数据、评测、当前策略哈希与运行预算；每轮执行前检查并原子预占预算。
- 模型须逐轮提交上一轮 Trial ID、反馈分析和修改后的代码；同一运行的独立评测工具也进入同一预算，不可绕过。
- 每轮保留 `candidate.py`、`parent.py`、`request.json`、`result.json`，包括失败结果。请求记有运行 ID、轮次、父版本及模型的反馈分析。
- 最佳候选按固定门槛筛选后比较收益，仅保留引用，不复制到 `strategies/current.py`。低于最佳但通过基线门槛的候选仍可归档，二者不是同一个判断。
- 外层进程组超时停止、工具内时限检查，以及失败／无改善停止由代码执行，不仅依赖提示词。该预算包含轮数和时间，不是精确的模型费用上限。
- `verify-research.mjs` 支持单轮历史记录和多轮记录，逐轮检查反馈先于下一候选、代码与父版本一致、最终模型回答引用所有 Trial ID。

## 当前 Codex 登录接入

本机 Codex 配置为 `gpt-6.1-sol`、low reasoning，DSH 内置 `llm-pi-ai` 的 `openai-codex` 提供方包含该模型。

启动器只读取现有 `CODEX_HOME/auth.json`（默认 `~/.codex/auth.json`）中的访问令牌与配置中的模型名。令牌在子进程环境中传给 DSH 提供方，不写入 YAML、命令行或实验记录，不复制 refresh token，不修改 Codex 登录。请求使用提供方预设的官方 Codex 端点；令牌过期时明确失败，需要先通过 Codex 正常刷新登录。

这是 DSH 内置提供方对现有登录的接入，不是把当前聊天输出当作模拟模型调用，也不是调用 Codex 子 Agent 来替代 DSH Agent 循环。

官方认证说明：[本地凭据缓存](https://learn.chatgpt.com/docs/auth#login-caching)。DSH 提供方行为以安装版本及本地源码为准。

## 已验证的一次闭环

运行目录：`data/dsh-runs/6c58dbf932a740c189d5739be90de24d/`

DSH Session：`session-b0224d19-1d19-4185-b087-ee89c066ba63`

模型工具调用链：`fund_daily` → 模型提出假设与修改代码 → `research_trial` → 独立评测反馈 → 模型最终解释。

持久化会话的真实模型请求列出了四个 DQR 工具：`fund_snapshot`、`fund_daily`、`strategy_evaluate`、`research_trial`，证明三个插件均实际完成注册。本轮直接调用每日分析和研究工具；策略评测由研究服务内部调用，独立 `strategy_evaluate` 工具没有额外消耗一次预算。

模型将月初等权策略的总基金仓位从100%降至80%，保留20%现金。候选是模型提交到工具的代码，已落盘为实验 `23b161a4e33d4148bdcc27682a12660e/candidate.py`。

| 固定验证期 2023–2025 | 候选 | 父策略 | 买入持有基线 |
| --- | ---: | ---: | ---: |
| 区间费后收益 | -1.5935% | -3.0354% | -3.1544% |
| 最大回撤 | 25.5471% | 30.9635% | 30.9215% |

固定门槛返回 `retain_for_review`。模型在收到反馈后引用实际 Trial ID 和这些指标，明确仅保留待人工复核。当前策略文件哈希保持不变。这次单轮运行时旧预算剩余一轮；多轮版本迁移后保留其历史用量，现行状态以持久化预算为准。

每日模型组合分析截至2026-10-22，研究评测截至2025-12-31。两者用途不同，输出已明确拆分 `analysis_period` 与 `research_evaluation_period`，避免直接横向比较。

## 独立核验证据

```bash
node scripts/verify-research.mjs data/dsh-runs/6c58dbf932a740c189d5739be90de24d
```

脚本读取 DSH 的多帧 Zstd 持久化会话，以及 headless 事件和实验文件，检查模型／提供方、实际注册工具、调用顺序、候选修改、归档一致性、评测配置未改、当前策略未替换，并检查模型在评测结果之后引用同一实验。生成 `proof.json` 和 `final.md`；验证不需要再次请求模型。

`events.jsonl` 是 headless 实际事件，`manifest.json` 是启动记录，`task.txt` 是原始任务。没有把模型自行宣称成功当作验收依据。

候选通过的是示例规则下的验证门槛，没有最终留出检验，也没有证明策略未来有效。个人持仓、真实申赎及产品规则核验仍未接入。

## 三轮真实模型实测 · 2026-10-22

本次从单轮候选 `23b161a4e33d4148bdcc27682a12660e`（两只各40%、20%现金）继续，命令为：

```bash
python3 scripts/run-research.py \
  --snapshot cf7f626a9fde7b73baf406ad3fc7f4938b546be65f527918888e0e73d13dab07 \
  --rounds 3 --parent-trial 23b161a4e33d4148bdcc27682a12660e
```

DSH Session 为 `session-1e260d0f-64ed-4d7e-ae8b-7ae372abf107`，运行目录为 `data/dsh-runs/79b3a3dbb0264badacfd8d7f1d31ff79/`。模型逐轮读取反馈，然后串行修改仓位常量：

| 轮次 | Trial ID | 总基金目标仓位 | 固定验证期收益 | 最大回撤 |
| --- | --- | ---: | ---: | ---: |
| 1 | `0d5c2bb6da5e4c09956eced370a405aa` | 60% | -0.6629% | 19.7364% |
| 2 | `2f7f1eb838f1451bb423ca63985d71db` | 40% | -0.0528% | 13.5455% |
| 3 | `d1272b2b9e24493fb85d67af12fba0f8` | 20% | +0.1485% | 6.9800% |

三轮均通过原有基线／回撤门槛，最佳待复核候选为第三轮。主机在第三轮返回 `round_limit`，模型读取停止原因后总结所有实验，没有提交第四轮。`proof.json` 的逐轮反馈顺序、代码／父版本、评测不变和当前策略不变检查均通过。

累计额度从旧账本的2次开始，本次用了3次，现为5/6；再次运行相同数据最多只会获得剩余1次，不会自动重新分配3次。

该结果也揭示当前门槛偏好降仓的局限：验证期中降低风险敞口改善了收益／回撤，并没有证明模型找到了择时或选基能力。尚未加入风险匹配基线或最终留出检验；本次没有为了提升候选得分修改评测规则。当前策略仍是两只各50%的初始策略。

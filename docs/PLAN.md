# maa-distill 实现方案

> 目标：在 MAA 全部功能之上（并能跟随 MAA 官方更新），蒸馏作业站的作战记录，
> 针对**你自己的干员 box**不断制定、实跑、优化作战方案，用于新活动关卡、危机合约、
> 保全派驻、悖论模拟，以及肉鸽。
>
> 前提：只会 Python，不熟悉 MAA。

---

## 1. 核心决策：不改 MAA，站在 MAA 上面

```
┌───────────────────────────── maa-distill（你的项目，纯 Python）────────────────────────────┐
│  crawler        →  db (SQLite)  →  planner（蒸馏 + 替补改编 + 打分）  →  runner              │
│  作业站增量爬取       作业/关卡/box/实跑记录     生成新作业 JSON                 调 MAA 执行     │
│                                       ↑                                         │         │
│                                       └──── feedback（胜负写回，下次重新排序）──────┘         │
└──────────────────────────────────────────────┬────────────────────────────────────────────┘
                                               │ 官方 Python 绑定（src/Python/asst）
                                               ▼  AsstAppendTask("Copilot", {"filename": ...})
┌───────────────────── MAA 官方发布包（update-maa 自动下载/升级，不做任何修改）─────────────────┐
│ MaaCore：任务调度 / 图像识别 / 模拟器控制 / 自动编队 / 战斗执行（BattleHelper）              │
│ resource：tasks.json、模板图、OCR 模型、roguelike 策略、battle_data.json                     │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**为什么不 fork MAA 改 C++？**

- 你的编程基础是 Python，C++ 内核（Vision/Controller/Task）学习成本高。
- MAA 几乎每周发版，活动一上线就会更新资源。fork 后每次都要合并上游冲突；分层方案下只需运行 `update-maa`。
- MAA 已经把"抄作业"做完了：读作业 JSON、自动编队、按时间轴部署、放技能。缺的只是"用哪份作业、怎么改成你能用的"。这正是 Python 层要做的事。

所以 **MAA 是执行器，maa-distill 是大脑**。两者之间唯一的接口是**作业 JSON 文件**（格式见 MAA 的 `docs/zh-cn/protocol/copilot-schema.md`）。

---

## 2. 与 MAA 各模块的对应关系

| maa-distill 模块 | 用到的 MAA 部分 | 作用 |
|---|---|---|
| `updater.py` | GitHub Releases、源码仓库 | 下载/升级 MAA 本体；拉取源码供参考和获取 Python 绑定 |
| `runner.py` | `src/Python/asst`（C API 的 ctypes 封装）→ `Assistant.cpp` → `Task/Interface/CopilotTask` 等 | 连接模拟器，执行 `Copilot` / `SSSCopilot` / `ParadoxCopilot` / `OperBox` |
| `box.py` | `OperBox` 任务的 `OperBoxInfo` 回调（`Vision/Oper/OperBoxImageAnalyzer`） | 识别你拥有的干员和练度 |
| `gamedata.py` | `resource/battle_data.json` | 干员职业、分支、站位、星级，用于找替补 |
| `planner.py` | 作业 JSON 的 `opers` / `groups` / `actions` 语义（`Task/Miscellaneous/BattleFormationTask` 按 group 自动选人） | 蒸馏、替补改编、打分 |
| `roguelike.py` | `resource/roguelike/<主题>/recruitment.json`、`autopilot/*.json` | 肉鸽策略与 box 的覆盖度分析 |
| `crawler.py` | 作业站 API（MAA 官方的作业站后端） | 增量同步作业 |

---

## 3. 数据来源（已实测，2026-11-26）

| 接口 | 内容 |
|---|---|
| `GET https://prts.maa.plus/arknights/level` | 3592 个关卡：活动 2292、主线 724、悖论模拟 317、保全派驻 138、**危机合约 49**、剿灭 37、资源 35 |
| `GET /copilot/query?page&limit≤200&order_by=id&desc=true&level_keyword=<stage_id>` | 作业列表，共 45,091 份。注意：**不含 actions** |
| `GET /copilot/get/{id}` | 单份完整作业（含 actions） |

爬取策略：列表按 id 倒序增量同步，每关只拉点赞最高的前 N 份详情，请求间隔 ≥1 秒。作业站是社区公益服务，**不要全量高频爬取**。

---

## 4. "蒸馏 → 制定 → 优化"算法（v0.1 已实现）

1. **蒸馏（stats）**：统计一个关卡所有作业的常用干员和常用部署点（按点赞加权），帮你看懂"这关大家怎么打"。
2. **可行性检查**：逐个编队位对照 box，检查是否拥有、练度是否达到 `requirements`。
3. **替补改编（制定新方案）**：缺的干员按"同分支（×0.8）> 同职业同站位（×0.5）"挑替补，练度不足再 ×0.6。
   改编时把缺的干员改写成**同名 group**，例如 `{"name":"圣聆初雪","opers":[{"name":"蜜蜡"}]}`。
   这样 actions 里所有按名字引用的部署、技能、撤退都不用改，MAA 会自动从 group 里挑人。
4. **打分**：
   - 先验 = 站内点赞/点踩的 Wilson 下界
   - 后验 = 加上你的实跑胜负做 Beta 更新
   - 最终分 = 后验 × 替补系数
5. **优化循环（run）**：执行排名第一的方案，结果写入 `runs` 表，然后重新排序。失败的方案分数下降，下一个替补组合或下一份作业自动顶上。实测：某方案失败两次后分数 0.498 → 0.332，被其他组合超过。

---

## 5. 各玩法的策略

| 玩法 | MAA 任务 | 数据来源 | 本项目做法 | 状态 |
|---|---|---|---|---|
| 新活动关卡（含突袭） | `Copilot` | 作业站，活动开放后数小时内就有作业 | 第 4 节全流程；用 `crawl --stage` 盯新关 | ✅ v0.1 |
| 危机合约 | `Copilot` | 作业站（`obt/rune/*`） | 同上；从标题解析风险等级与人数，`plan/run --min-risk 10 --max-opers 5` 筛选（`contract.py`，已用真实作业验证） | ✅ v0.1.1 |
| 保全派驻 | `SSSCopilot` | 作业站（保全派驻 138 个关卡） | `run --kind SSSCopilot`。格式见 `sss-schema.md`，替补逻辑要适配 | 🟡 v0.2 |
| 悖论模拟 | `ParadoxCopilot` | 作业站（317 个） | 单干员关卡，基本只需检查是否拥有 | 🟡 v0.2 |
| 肉鸽 | `Roguelike` | **作业站没有肉鸽作业**；来源是 MAA 自带策略 + 你自己的运行日志 | 覆盖度分析；按你的练度生成招募优先级增量资源（已从 MAA 源码确认：增量 recruitment.json 会整份替换该主题配置，所以写完整文件）；`roguelike <主题> --run --bonus N` 带覆盖跑并记录结果，对比不同 N | 🟡 v0.1.3：招募覆盖 + 逐关翻车率统计（解析 MAA `StageInfo`/`RoguelikeSettlement` 回调）+ 配置 A/B 对比已实现，待真机验证；按翻车关调整 autopilot 部署需先积累数据（阶段 4） |

> **说明**：本项目能把成功率较高的作业找出来、改成你能用的版本，并通过实跑快速淘汰失败方案。
> 但它不能凭空为一个零作业的新关卡生成完整时间轴：新活动开放最初几个小时作业站还没有作业，这段时间需要等。
> 从零生成时间轴是阶段 5 的研究课题。

---

## 6. 路线图（结合 Python 学习）

### 阶段 0：熟悉 MAA（约 1 周）

- 先用 MAA 图形界面正常抄几次作业，理解自动编队和作业 JSON。
- 阅读 MAA 文档：`copilot-schema.md`（作业格式）、`integration.md`（接口和任务类型）、`callback-schema.md`（回调消息）。
- 运行 MAA 的 `src/Python/sample.py`，体验用 Python 控制 MAA。

### 阶段 1：MVP（✅ 本仓库 v0.1）

- 爬取、box 导入、统计、替补改编、打分、实跑循环、MAA 自动更新、单元测试。
- **你要做的验收**：装好模拟器（1280×720 或 16:9），运行 `update-maa` → `box --scan` → `crawl --stage <新活动关卡>` → `run <关卡>`。

### 阶段 2：补齐玩法和健壮性（2～3 周）

- 保全派驻、悖论模拟的替补逻辑；危机合约按具体 tag 组合（而非仅等级）过滤。
- 胜负判定更准：除了 `TaskChainCompleted`，还解析战斗结算的星级和失败原因。
- 加 `watch` 命令：定时检测新活动（`levels` 表新增 stage_id），自动拉取作业并生成方案。

### 阶段 3：更聪明的蒸馏（3～4 周）

- 替补质量：引入技能类型、费用、攻击范围（`battle_data.json` 的 `rangeId`）计算相似度，替代现在的职业规则。
- 作业合成：同一关的多份作业里，若部署点和时间轴高度一致，合成"共识方案"，并标注最稳定的动作。
- 失败归因：读取 MAA 日志，判断失败发生在哪个 action，有针对性地只替换那个位置。

### 阶段 4：肉鸽（4 周以上）

- 记录每局肉鸽回调，包括层数、分队、招募、结局。
- 基于 box 的覆盖度生成增量资源：降低你没有的干员的招募优先级，提升你练度高的同职能干员。
- A/B 对比不同参数的通关层数，保留更好的配置。

### 阶段 5（研究）：无作业关卡的方案生成

- 利用关卡地图（`resource/Arknights-Tile-Pos`）和历史作业的"地形→部署"模式，生成候选方案，再靠实跑循环筛选。

---

## 7. 跟随 MAA 更新

```bash
python -m maa_distill update-maa          # 下载最新官方发布包到 maa/，git pull 源码
```

- 项目只依赖 MAA 的**公开 C API、Python 绑定、作业 JSON 格式和 battle_data.json**，这些接口都很稳定。
- 每次 MAA 大版本更新后运行一遍 `python -m unittest discover tests`。
- 如果 MAA 改了作业格式，只需要修改 `schema.py`。

---

## 8. 风险与注意事项

- **账号风险**：自动化操作违反游戏用户协议，使用 MAA 本身就有风险（见 MAA 的 `terms-of-service.md`），请自行权衡。
- **作业站负载**：保持 `request_interval ≥ 1`，只按需拉详情。
- **替补不等价**：替补干员的费用、技能时机可能不同，按时间轴写的作业可能失败。这正是需要实跑反馈的原因。
- **分辨率**：MAA 要求 16:9，推荐 1280×720 或 1920×1080。

---

## 9. 代码地图（供学习）

| 文件 | 行数级别 | 你能学到什么 |
|---|---|---|
| `crawler.py` | ~150 | HTTP 请求、分页、限速、SQLite 写入 |
| `schema.py` | ~120 | dataclass 建模 JSON |
| `planner.py` | ~230 | 核心算法：组合枚举、打分、生成 JSON |
| `scoring.py` | ~40 | 贝叶斯更新 / Wilson 区间 |
| `runner.py` | ~120 | ctypes 回调、线程安全队列、调用 MAA |
| `cli.py` | ~200 | argparse 子命令 |

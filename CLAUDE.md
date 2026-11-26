# maa-distill 交接说明（给在用户 Mac 上运行的 Claude）

## 这个项目是什么

在 MAA（MaaAssistantArknights）之上的纯 Python 层：爬取作业站（prts.maa.plus）的作战记录 →
对照用户的干员 box 打分、缺人时按同分支/同职业替补改编 → 调 MAA 实跑 → 胜负写回数据库并重新排序。
设计与路线图见 `docs/PLAN.md`，用法见 `README.md`。**不修改 MAA 本体**，`update-maa` 跟随官方发版。

## 用户环境（已确认）

- macOS，BlueStacks，**B 服**（包名 `com.hypergryph.arknights.bilibili`），分辨率 1280×720
- adb：`/Users/Zhuanz/platform-tools/adb`，设备 `127.0.0.1:5555`（`config.json` 已配好）
- 国内网络：Homebrew、GitHub HTTP/2 不稳定；git 已设 `http.version HTTP/1.1`，失败就重试
- 用户只会 Python，对 MAA 不熟；回复用中文，命令里**不要写行内 `#` 注释**（用户的 zsh 会把它当参数）

## 常用命令

```bash
python3 -m maa_distill update-maa
python3 -m maa_distill box --scan
python3 -m maa_distill crawl --stage <关卡>
python3 -m maa_distill plan <关卡>
python3 -m maa_distill run <关卡> --max-attempts 3
python3 -m maa_distill undo-run
python3 -m maa_distill roguelike <主题> --run --starts 3
python3 -m maa_distill roguelike <主题> --report
python3 -m unittest discover tests
```

## 安全规则（必须遵守）

- `run` / `roguelike --run` / `task` / `daily` 会真实操作游戏并消耗理智：**每次执行前先征得用户同意**。
- `run` 必须从该关卡带「开始行动」按钮的编队界面开始，且自动编队会**清空当前队伍**。
  执行前可用 `adb -s 127.0.0.1:5555 exec-out screencap -p > /tmp/s.png` 截图确认当前界面。
- 不要把用户账号信息、截图发到任何外部服务。

## 当前进度（2026-11-26）

已在真机验证：`update-maa`（macOS v6.23.2）、`box --scan`（277 名干员）、`plan 1-7`、`run 1-7`（作业 22515 胜，记录生效，分数 0.987→0.989）。

下一步：
1. `git pull` 后 `plan TL-8`（会自动补拉其余作业详情，期望出现「无需替补」方案），用户同意后 `run TL-8 --max-attempts 3`。
2. 危机合约：`plan <level_rune_xx-xx> --min-risk N`，实跑验证。
3. 肉鸽：`roguelike <主题> --run` 积累数据 → `--report` 找翻车关 → 实现「按关卡调整 autopilot 部署」（PLAN.md 阶段 4，尚未编写）。
4. `task` / `daily` 尚未实机验证（B 服 `client_type` 用 `Bilibili`）。

## 开发约定

- 只用标准库；改动后跑 `python3 -m unittest discover tests`，实机发现的 bug 尽量把真实回调写成测试。
- MAA 行为以源码为准（MaaAssistantArknights 仓库 `src/MaaCore`、`docs/zh-cn/protocol/*.md`），不要猜。
- 提交推送到 `origin main`；提交信息结尾加：`Co-Authored-By: Claude <noreply@anthropic.com>`。

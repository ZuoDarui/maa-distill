# maa-distill

在 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 之上的 Python 层。功能：

- 蒸馏作业站的作战记录
- 按**你自己的 box** 改编出可用的作战方案
- 用 MAA 实跑，按胜负不断重新排序优化

MAA 本体不做任何修改，用 `update-maa` 即可跟随官方更新。

完整设计和路线图见 [docs/PLAN.md](docs/PLAN.md)。

## 快速开始

```bash
# 0. 需要 Python ≥ 3.10，无第三方依赖
git clone <本仓库> && cd maa-distill
cp config.example.json config.json   # 填 adb 地址（MuMu 一般为 127.0.0.1:16384）

# 1. 获取 MAA（官方发布包 + 源码中的 Python 绑定）
python -m maa_distill update-maa

# 2. 同步作业站：关卡表 + 某关的作业（每关默认拉点赞前 5 份详情）
python -m maa_distill crawl --stage TL-S-2

# 3. 导入你的 box
python -m maa_distill box --scan                 # 用 MAA 在模拟器里识别
python -m maa_distill box --file mybox.json      # 或手写 JSON（格式见 tests/fixtures/sample_box.json）

# 4. 看这关大家怎么打，并生成适配你的方案
python -m maa_distill stats TL-S-2
python -m maa_distill plan TL-S-2                # 生成的作业 JSON 在 data/plans/，也可以导入 MAA 图形界面

# 5. 实跑：失败自动换下一个方案，直到成功
python -m maa_distill run TL-S-2 --max-attempts 5
python -m maa_distill run <保全关卡> --kind SSSCopilot

# 用 MAA 图形界面跑完，可以手动记录结果
python -m maa_distill record data/plans/xxx.json win

# MAA 全部原生功能：日常一键执行 / 任意任务直通（参数格式同 MAA 文档 integration.md）
python -m maa_distill daily                      # 默认清单 daily.example.json：启动→刷理智→公招→基建→商店→奖励
python -m maa_distill task Fight '{"stage":"1-7","times":3}'
python -m maa_distill task Reclamation '{"theme":"Tales"}'

# 危机合约：只要风险 ≥10 级、≤5 人的作业
python -m maa_distill plan level_rune_14-02 --min-risk 10 --max-opers 5

# 肉鸽：查看你的 box 对某主题策略的覆盖度
python -m maa_distill roguelike JieGarden
python -m maa_distill roguelike JieGarden --write-override --bonus 50   # 按练度调招募优先级
python -m maa_distill roguelike JieGarden --run --bonus 50 --starts 3    # 带调整跑肉鸽，逐关记录胜负
python -m maa_distill roguelike JieGarden --report                      # 哪关最容易翻车、哪个 bonus 更好
```

## 示例输出（TL-S-2，示例 box 缺 圣聆初雪）

```text
#1 分数 0.498 | 作业 110081 时间啊，向前！ - TL-S-2 - 霜解
   圣聆初雪 → 伊芙利特
   站内先验 1.00，实跑 0 胜 0 负，替补系数 0.50
```

记录两次失败后重新运行 `plan`，该组合降到 0.332，其他替补组合自动排到前面。

## 目录

```text
maa_distill/
  crawler.py    作业站增量爬虫（限速、按需拉详情）
  db.py         SQLite：copilots / levels / box / runs
  schema.py     作业 JSON 数据模型
  gamedata.py   干员职业数据（读 MAA 的 battle_data.json）、关卡别名
  box.py        干员 box（MAA OperBox 识别或手写）
  planner.py    蒸馏统计、替补改编、方案排序
  scoring.py    Wilson 下界 + 贝叶斯后验
  feedback.py   实跑记录
  runner.py     调用 MAA Python 绑定执行任务
  updater.py    跟随 MAA 官方更新
  contract.py   危机合约风险等级/人数解析与筛选
  roguelike.py  肉鸽策略覆盖度分析
tests/          离线单元测试：python -m unittest discover tests
```

## 在 Mac + BlueStacks 上运行（推荐）

```bash
brew install android-platform-tools        # 提供 adb
git clone git@github.com:ZuoDarui/maa-distill.git && cd maa-distill
cp config.example.json config.json         # adb_path 填 "adb"，adb_address 填 BlueStacks 显示的 "127.0.0.1:5555"
python3 -m maa_distill update-maa          # 下载 macOS 版 MAA 与同版本 Python 绑定（不再需要克隆 MAA 源码）
adb connect 127.0.0.1:5555 && adb devices  # 应显示 device
python3 -m maa_distill box --scan
python3 -m maa_distill crawl --stage <关卡> && python3 -m maa_distill plan <关卡>
python3 -m maa_distill run <关卡>
```

BlueStacks 设置：高级 → 打开 Android 调试桥（ADB）；分辨率 16:9（1280×720 或 1920×1080）。
B 服玩家在 `daily` 清单里把 `client_type` 改成 `"Bilibili"`。

## 远程测试（模拟器在你的 Mac 上，程序在另一台 Linux 机器上）

两台机器在同一 Tailscale 网络时，在 Mac 上开一条 SSH 反向隧道，把模拟器的 adb 端口转发过去：

```bash
# Mac 上（MuMu Pro 默认 adb 端口 16384）
ssh -N -R 16384:127.0.0.1:16384 <user>@<linux 机器的 tailscale ip>
```

Linux 机器的 `config.json` 里 `adb_address` 填 `127.0.0.1:16384`。注意跨地域延迟会影响按时间轴执行的作业，
实测（2026-11-26，美国机房 ↔ 北京 Mac，RTT 277ms）：单张截图传输约 21 秒，MAA 无法正常工作，\n远程方式只能验证连通性；请直接在 Mac 上运行本项目。

## 跟上游保持同步

- MAA 本体：`python -m maa_distill update-maa`
- 本仓库：日常 `git add -A && git commit -m "..." && git push`

## 声明

自动化操作存在违反游戏用户协议的风险，请自行承担。请合理控制对作业站的请求频率。

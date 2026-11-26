"""评分：把作业站评价和你自己的实跑结果合成一个"成功概率"。

思路（贝叶斯更新，不需要任何机器学习库）：
- 先验：作业站点赞/点踩 → Wilson 下界，代表"社区认为它能过的概率"
- 证据：你自己跑这份方案的成功/失败次数
- 后验均值 = (prior_strength * p0 + 成功) / (prior_strength + 成功 + 失败)
跑得越多，你自己的结果权重越大 —— 这就是"不断优化"的基础。
"""

from __future__ import annotations

import math


def wilson_lower_bound(pos: int, neg: int, z: float = 1.96) -> float:
    n = pos + neg
    if n == 0:
        return 0.5
    p = pos / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def site_prior(likes: int, dislikes: int, views: int = 0) -> float:
    base = wilson_lower_bound(likes, dislikes)
    # 浏览多但没人评价的，稍微降一点；完全没数据保持 0.5
    if likes + dislikes == 0 and views > 500:
        base = 0.45
    return base


def posterior(prior_p: float, successes: int, failures: int, prior_strength: float = 4.0) -> float:
    a = prior_strength * prior_p + successes
    b = prior_strength * (1 - prior_p) + failures
    return a / (a + b)

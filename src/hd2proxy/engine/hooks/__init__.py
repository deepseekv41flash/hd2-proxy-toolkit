"""改写钩子（M1 从 legacy_proxy.py 抽出）。

顺序固定且**有语义**：warinfo（星球身份）→ Status（战况）→ Progression（目录/库存）。
每个钩子都支持两种取配置的方式：
  * `spec=<dict>`：显式传入（schema v2 profile / 单元测试用）；
  * `spec=None`：退回研究线旧行为（读 environment / runtime/*.json），保证兼容与可回退。
"""

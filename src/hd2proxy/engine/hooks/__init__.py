"""改写钩子（M1 从 legacy_proxy.py 抽出）。

顺序固定且**有语义**：warinfo（星球身份）→ Status（战况）→ Progression（目录/库存）
→ 存档（G2：`/api/Progression` 根响应的 earned 合并，见 progression.py）。
每个钩子都支持两种取配置的方式：
  * `spec=<dict>`：显式传入（schema v2 profile / 单元测试用）；
  * `spec=None`：退回研究线旧行为（读 environment / runtime/*.json），保证兼容与可回退。

存档钩子（progression.py）与之不同：它的「配置」不是 profile 里的一个 dict，而是引擎进程级的
`ActiveSave`（active_save.py）。所以它吃 ``save=`` 而不是 ``spec=``，且**不读 runtime/*.json**。
"""

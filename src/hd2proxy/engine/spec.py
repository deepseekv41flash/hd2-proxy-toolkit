"""一次运行所需的全部输入（schema v2 profile 归一化后的产物）。

为什么单独一个 dataclass：
  * 引擎钩子只认「spec」，不关心它是从 profile JSON 还是旧 runtime/*.json 来的；
  * `None` 保留旧行为（钩子自己去读 env / runtime 文件），便于回退与 A/B；
  * 控制面（control.py）热更新时只替换 spec，不需要重启代理。
"""

from dataclasses import dataclass, field


@dataclass
class EngineSpec:
    """代理运行参数 + 各钩子的显式配置。None = 该钩子退回研究线旧行为/不启用。"""

    # ---- 运行参数 ----------------------------------------------------------
    host: str = "api.live.prod.thehelldiversgame.com"
    listen_ip: str = "auto"
    port: int = 443
    crl_port: int = 8080
    control_port: int = 0
    passthrough: bool = True
    verbose: bool = False

    # ---- 证书策略 ----------------------------------------------------------
    cert_days: int = 2
    cert_min_remaining_hours: float = 12.0
    cert_auto_renew: bool = True

    # ---- 钩子 spec（键名与 hooks/* 一一对应） -------------------------------
    warinfo: dict | None = None
    status_extra: dict | None = None
    status_plan: dict | None = None
    inventory: dict | None = None
    items: dict | None = None
    customize: dict | None = None
    capture: dict | None = None
    # G2 存档层：{"enabled","wait_seconds","identity_strict"}；None = 未启用（legacy 模式）
    saves: dict | None = None

    # ---- 运行期附加信息（不参与改写，供控制面/日志展示） --------------------
    profile_name: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "host": self.host, "listen_ip": self.listen_ip, "port": self.port,
            "crl_port": self.crl_port, "control_port": self.control_port,
            "passthrough": self.passthrough, "verbose": self.verbose,
            "cert": {"days": self.cert_days,
                     "min_remaining_hours": self.cert_min_remaining_hours,
                     "auto_renew": self.cert_auto_renew},
            "hooks": {
                "warinfo": self.warinfo,
                "status_extra": self.status_extra,
                "status_plan": self.status_plan,
                "inventory": self.inventory,
                "items": self.items,
                "customize": self.customize,
                "capture": self.capture,
                "saves": self.saves,
            },
            "profile_name": self.profile_name,
            "warnings": list(self.warnings),
        }

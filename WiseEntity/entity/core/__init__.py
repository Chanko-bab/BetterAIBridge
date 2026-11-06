"""无名的常驻内核（entity_core）。

包内模块：
- settings   路径/常量/日志/JSON 读写
- brain_box  神经内核（flybrain v2）的加载、驱动、存盘
- memory_box 分片长期记忆的检索与写入
- llm_box    系统提示拼装与 DeepSeek 调用
- chat_core  会话历史与一次完整回复
- bili_door  B 站私信门（轮询/收发）
- app        FastAPI 服务（网页客厅 + 内部 API）
"""

__all__ = ["settings", "brain_box", "memory_box", "llm_box", "chat_core", "bili_door", "app"]

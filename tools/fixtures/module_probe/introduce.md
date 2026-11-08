# 契约探针

这是 `tools/test_module_contract.py` 用的最小合规 fixture。

它只回答两个问题：

- `GET /health`：我还活着。
- `GET /ping`：我能被调用。

不读写用户数据；测试结束会清理临时目录。

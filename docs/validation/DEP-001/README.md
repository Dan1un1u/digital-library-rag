# DEP-001 验证记录

本项修复真实模式启动依赖个人 D 盘服务目录的问题，并按用户要求将本机接入代码移出交付项目。基线为 main bdfb737c555b4e55d9216f1397316b3bfb513ec0；工作目录、数据、报告与旧任务分开。

## 修改与贡献

- 移除本机服务快照、代理与本地嵌入适配器、LLM 相关性重排器、配置写入器及本机联调脚本；云端四项 provider 只接受 siliconflow，省略时仍默认云端。
- 一键启动只调用本项目控制器；首次运行自动创建目录，真实数据路径从配置和进程环境读取，MOCK 使用独立库。
- 新增18项测试，覆盖旧配置装配、四项 HTTP 契约、provider 与 HTTPS 边界、数据路径和三种入口模式。
- 同步部署 README、云端操作说明与 Word/Markdown 手册。截图、旧文档验收文件和历史实测环境保持原样，本轮输出另记。

## 复现

在本分支的干净提交和独立 Python 环境中运行：

```powershell
& .\.venv\Scripts\python.exe scripts/run_catalog_checks.py --work-item DEP-001 --scope new
& .\.venv\Scripts\python.exe scripts/run_catalog_checks.py --work-item DEP-001 --scope all
```

新增用例位于 app/tests/integration/test_siliconflow_portability.py，继承测试从 app/tests 复用。测试不读取真实密钥；四项 HTTP 使用拦截响应，启动入口使用隔离副本和禁止启动外部服务的拦截器。新项目启动烟测使用独立端口和空库，不对真实模型发请求。

正式执行结果、被测提交、移除与新增用例归属、启动与文档核验见 results.json。首次本机接入只读审计与撤出前备份保存在仓库外；本项不清理 Git 历史，不改写旧结果中的模型名、SHA、失败或批次身份。

## 边界

- 未执行真实硅基流动付费请求，不能声称账户权限、网络或模型在线响应已验收。
- 本机既有正式与 dev 服务保留原源码和配置，没有部署本 PR，也没有迁移馆藏。
- 手册沿用14幅历史实拍图，只更新当前部署要求，不将旧截图冒充云端重新实拍。
- 本项为独立 Draft PR；通过后仍由用户决定合并。

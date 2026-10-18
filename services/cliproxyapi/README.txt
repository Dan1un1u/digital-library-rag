本机 CLIProxyAPI

位置：D:/cliproxyapi-local/
官方来源：https://github.com/router-for-me/CLIProxyAPI
已固定版本：8.0.33。下载包和官方 checksums.txt 均已校验 SHA256。
证据：evidence/release.json。

接口：http://127.0.0.1:8317/v1
只监听本机回环地址。管理 API 与管理页面关闭，未设置开机自启。
只接入一次单独授权的 Codex 登录，未复制、修改桌面 Codex 的已有登录凭证。
项目指定模型为 gpt-6-luna；没有将其他模型伪装成 Luna。

本机操作：
进入本目录，在 PowerShell 运行 ./Start-CLIProxyAPI.ps1。
查看状态 ./Status-CLIProxyAPI.ps1；停止 ./Stop-CLIProxyAPI.ps1。
登录失效时运行 ./Login-CLIProxyAPI.ps1，在官方 OpenAI 登录页完成授权。
停止脚本只操作本部署保存的、进程路径与创建时间均匹配的进程。

config.yaml：本地客户端口令与服务配置，不要提交到 Git 或展示在视频中。
auth/：单独 OAuth 凭证，程序负责续期，不要公开或复制给他人。
凭证、配置及代理日志已限制为当前用户、SYSTEM 和管理员可访问。
调用口令是本机代理的客户端口令，不是 OpenAI 平台签发的 API Key。
代理与客户端在本机；Luna 推理仍通过 OpenAI 服务，使用订阅账户的访问权限和额度。
重试次数为 0，未配置其他账户或模型作为限额回退。

上游连接复用现有的本机网络代理 http://127.0.0.1:7897。
仅访问本机 BGE 和本机 CLIProxyAPI 的图书馆适配器会绕过环境网络代理。
运行依赖该网络出口可用；Luna 的可用性也取决于上游网络、账户权限及额度。

已接入的图书馆：
D:/llm_exp/digital-library/workspace/deployments/lib_management_v1_20261018/
其 Start-Library.ps1 会先启动本代理与本地 BGE，再启动图书馆。
详细运行证据请看图书馆 reports/local_models_integration.json。

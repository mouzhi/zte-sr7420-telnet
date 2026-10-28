# 中兴问天 BE7200 MAX / ZXSLC SR7420 开启 LAN Telnet

**ZTE BE7200 MAX (SR7420) LAN Telnet / root shell research notes and tools.**

适用于自有设备管理员的可复现流程：备份原配置、离线生成只改四个字段的候选配置、在网页中手动恢复、验证 root Telnet 登录。针对常见的 `webFac 404`、配置导出中途断开、Python 3.13+ 没有 `telnetlib` 等问题记录了实际处理办法。

**只发布开通 Telnet 所必需的代码和经验。仓库不包含任何实机配置、密码、证书、序列号、MAC 地址、网络拓扑或流量规则。测试数据全部是人工构造的最小样例。**

## 使用范围与免责声明

本项目仅面向个人对**同时拥有所有权和合法管理权限的设备**进行研究、学习和自主管理。请勿用于他人、运营商所有或其他未明确授权的设备，勿用于未授权访问、扫描、攻击或公开暴露管理服务。

- 本项目非中兴官方工具，与厂商无隶属关系，也不构成厂商支持或安全认证。
- 配置恢复可能自动重启、短暂断网；错误型号、固件、文件损坏或操作失误可能造成配置丢失、设备无法启动，并可能影响保修。请自行评估风险，保留原始备份和现场恢复手段。
- Telnet 和此固件的 HTTP 管理连接是明文传输。仅在可信、受控的本地网络操作。请保持 WAN Telnet 关闭、IPv4/IPv6 防火墙开启，不做端口映射、DMZ 或公网开放。
- 端口开放不等于获得 shell，LAN 登录成功也不等于 WAN 一定不可达。按下文分别验证。
- 软件按 MIT License“按原样”提供，不提供适用性、可用性或不损坏设备的保证。使用范围说明不授予任何设备访问权，也不免除依法应承担的责任。

## 已验证的适用范围

| 项目 | 已验证值 |
| --- | --- |
| 商品名称 | 中兴问天 BE7200 MAX |
| 设备型号 | ZXSLC SR7420 |
| 固件 | `V1.0.0.2B4.8000` |
| 配置封装 | 无额外外层签名的 Type-4，AES-256-CBC + 分块 zlib |
| shell | BusyBox ash，实际 `id` 验证 `uid=0` |
| 管理入口 | LAN Telnet，TCP 23 |
| 客户端 | Python 3.11+；本地实测 Windows / Python 3.14 |

本工具**不默认支持其他固件、硬件修订或运营商定制版**。`backup` 会读取实际型号和版本，不匹配即停止。修改这个限制不意味着设备兼容。此流程不安装 SSH，也不修改固件镜像。

## 快速使用

先准备网线连接和维护窗口，确认能登录自己的路由器管理页面。保持 IPv4 和 IPv6 防火墙均开启且等级为“高”。确保没有同时进行其他配置编辑；备份与恢复之间应尽量短。

以下 `192.168.1.1` **只是示例地址**，请替换为自己的路由器 LAN 地址。

### 1. 安装

```sh
git clone https://github.com/mouzhi/zte-sr7420-telnet.git
cd zte-sr7420-telnet
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Linux / macOS：

```sh
. .venv/bin/activate
python -m pip install -e .
```

### 2. 备份原配置

```sh
python -m sr7420.cli backup --host 192.168.1.1 --output-dir ~/sr7420-private/backup
```

密码通过隐藏输入提示读取，不要放进命令行、截图或 Issue。工具只尝试登录一次，不自动重试密码，不保存管理员密码。

输出目录必须是**仓库之外、尚不存在的新目录**。工具在 Windows 限制目录 ACL 为当前用户和 SYSTEM；在 POSIX 系统使用目录 `0700`、文件 `0600`。

生成：

- `original.bin`：完整原始备份，**务必保留**。
- `backup-manifest.json`：型号、版本、设备地址、文件哈希。仅用于本地验证，不要上传。

该阶段仅登录、读取型号和导出备份，不恢复配置、不重启。只有传输长度、解密及 CRC 验证通过，备份才会写入输出目录。

### 3. 离线生成候选配置

```sh
python -m sr7420.cli prepare --backup-dir ~/sr7420-private/backup --output-dir ~/sr7420-private/candidate
```

生成：

- `candidate.bin`：用于手动恢复的候选配置。
- `candidate-report.json`：只列修改字段和哈希，不含密码或原配置值。
- `telnet-credentials.json`：随机生成的 Telnet 密码，**属于敏感文件**。

工具只改变以下四个字段，保留其他配置文本：

| 表 | 字段 | 变化 |
| --- | --- | --- |
| `TelnetCfg` | `TS_Enable` | `0 → 1` |
| `TelnetCfg` | `Lan_Enable` | `0 → 1` |
| `TelnetCfg` | `TS_UPwd` | 设置独立随机密码 |
| `PortControl` 的 `TELNET` 行 | `ServIPMode` | `0 → 1` |

`Wan_Enable=0`、`PortEnable=0`、`PortLANEnable=1` 保持不变。若源配置与这些前置条件不同、Telnet 已开启、防火墙状态不符合要求或表结构异常，工具停止，不强行覆盖。

重新编码后会再次解密，校验 CRC，并确认得到的 XML 与候选文本完全相同。压缩库差异可能导致候选文件大小变化，**不能仅按大小判断是否正确**。离线校验也不能替代设备实际接受配置的验证。

### 4. 手动恢复候选配置

1. 关闭其他正在编辑路由器设置的管理会话。
2. 在路由器网页的“系统”中找到“配置管理／配置恢复”（名称以实际页面为准）。
3. 使用**恢复配置功能**选择 `candidate.bin`；不要把它当作固件升级文件。
4. 确认自己已保留 `original.bin`，并接受重启和短暂断网后再提交。
5. 等待页面报告成功并让路由器自行恢复。提交后连接断开时，先检查状态，**不要重复上传**。

项目故意不提供自动恢复、重启、刷机或命令执行子命令。人工确认是为了让使用者控制这一有中断风险的边界。

### 5. 验证实际 root 登录

```sh
python -m sr7420.cli verify --credentials ~/sr7420-private/candidate/telnet-credentials.json
```

验证器只执行 `id` 和 `uname -n`，不写配置、不收集日志、不执行任意命令。输出示例：

```json
{
  "root_verified": true,
  "hostname": "SR7420",
  "transport": "LAN Telnet"
}
```

随后自行检查上网、Wi-Fi 和管理页面，并从**外部网络**验证 WAN 的 IPv4 与 IPv6 TCP 23 均不可连接。仅从 LAN 访问公网地址可能经过回环，不能代替真正的外部检查。不要为了测试而开放 WAN。

注意：该固件的 `telnetd` 可能仍在 IPv6 地址上监听。`ServIPMode=1` 是配置中的服务策略字段，不能据此断言操作系统只绑定 IPv4。是否限制外部访问，必须结合 WAN 设置、防火墙和外部连通性判断。

## 常见问题和排障经验

### `webFac` / `webFacEntry` 返回 404

部分旧教程和工具依赖这些工厂接口。在本项目实测固件上，HTTP、HTTPS 和特定客户端 MAC 的尝试均未打开该路径。本项目使用**已有管理员权限下的配置备份／恢复**，不依赖旧工厂接口，也不将 404 自动认定为所有型号均不支持。

### 备份显示 HTTP 200，但下载被 reset／文件截断

实测中，部分关闭连接的 HTTP 客户端只获得了部分二进制数据。改为 HTTP/1.1、`Connection: keep-alive`、保持认证 Cookie，并按网页正常流程先调用导出准备接口后，完整导出成功。

本工具使用标准库 `http.client` 保持连接，检查完整响应长度，并验证备份内部长度和 CRC。**不要给截断文件补零后用于恢复，也不要把状态码 200 当作备份成功。**

### 为什么用了名为 SR7410 的加密常量？

实测 SR7420 此版本的 Type-4 备份可由公开研究中的 `SR7410Key80748010` / `SR7410Iv80748010` 模型常量解密。它们是上游项目已公开的模型级常量，**不是任何使用者的管理员或 Telnet 密码**。这不意味着两个型号的完整配置可以互换。

格式和常量来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。不要将其他人的配置文件导入自己的设备。

### Python 3.13+ 没有 `telnetlib`

本项目使用有限的 socket Telnet 协商实现，不依赖已移除的 `telnetlib`。验证器必须见到真实 shell 提示符，再验证 `uid=0`；XML 行末的 `>` 不会被当作 shell 提示符。

### 验证失败／想回滚

- 保持现场有线连接，检查设备是否完成启动；不要连续尝试错误密码，以免触发登录锁定。
- 若网页还可用，使用**配置恢复**导入本机此前保存的 `original.bin`。这也可能重启。
- 回滚的是备份时间点的整个配置，会覆盖之后的修改；操作前核对是否有新增设置。
- 网页也不可用时，本项目不承诺能远程恢复。应按厂商提供的恢复流程处理，或联系厂商。不要直接尝试来历不明的固件、跨型号备份或盲目刷写。

## 隐私与提交问题

请先阅读 [SECURITY.md](SECURITY.md)。不要在 Issue、PR 或聊天截图里粘贴配置文件（即便它已加密）、解密 XML、登录凭据、Cookie、Token、序列号、MAC 地址或完整抓包。只提供脱敏后的型号、固件版本、执行阶段和错误类别。

仓库范围不包括其他网络服务、分流规则、节点、账号、证书或个人环境。`.gitignore` 和输出目录限制只是降低误提交风险，不能代替人工检查。

## 开发与验证

```sh
python -m unittest discover -v
python -m sr7420.cli --help
```

测试使用人工构造的 XML、临时目录、本地 HTTP 服务器和假 Telnet socket，验证完整性检查、四字段限制、隐私输出、认证／导出流程及提示符识别。CI 在 Windows 与 Linux、Python 3.11 与 3.14 上运行，**不会连接任何真实路由器**。

历史实机流程已在上述型号／固件上完成恢复和 root 登录；开源重构版发布前另做了只读实机导出、离线兼容性及登录验证。重构后的工具未为了发版再对设备执行恢复或重启。参见 [验证范围](docs/validation.md)。

## License

原创代码采用 [MIT License](LICENSE)。基于上游配置格式实现的部分保留其版权与许可说明，见 [第三方声明](THIRD_PARTY_NOTICES.md)。

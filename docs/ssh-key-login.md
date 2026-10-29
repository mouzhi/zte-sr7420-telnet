# SR7420 的 LAN SSH 密钥登录与交互终端修复

适用范围与主 README 相同：**自有且有合法管理权限的 ZXSLC SR7420 / 问天 BE7200 MAX，实测固件 `V1.0.0.2B4.8000`**。需要先完成 [LAN root Telnet](../README.md) 流程。

本章只讨论设备管理权限。没有其他网络服务、用户账号、地址分配、出口或业务规则配置。所有示例 IP 和文件路径均为通用示例，必须按自己的设备替换。

## 实测发现

| 项目 | 结论 |
| --- | --- |
| `uname -m` | 内核报告 `aarch64` |
| 现有 BusyBox ELF | 32 位 ARM EABI；不能只看内核架构就选二进制 |
| SSH 服务端 | 固件中可能有 `/etc/dropbear` 目录，但本次设备没有可用的 SSH 服务端程序 |
| root 用户名 | Telnet 可以接受 `root`，但 Unix `/etc/passwd` 的 UID 0 名称可能不同 |
| 标准 PTY | 没有 `/dev/pts`，普通 glibc `openpty()` 失败 |
| 旧式 PTY | 存在 `/dev/ptyp*`；不能据此认定另一 SSH 实现直接使用它就一定兼容 |
| 信号 | 从 Telnet 启动的 SSH 曾继承被屏蔽的 SIGINT／SIGPIPE，影响 Ctrl+C |
| 系统分区 | 本次设备始终保持只读，重挂载返回成功也没有改变实际挂载状态 |

检查时不要公开 `/etc/passwd`、完整日志或设备配置。若需判断实际 UID 0 名称，在自己的终端中运行：

```sh
busybox awk -F: '$3 == 0 { print $1 }' /etc/passwd
```

SSH 登录应使用实际存在的 UID 0 账号；不要为了照抄示例而修改系统账号数据库。

## 方案与边界

- 使用 [官方 Dropbear 2026.94](https://github.com/mkj/dropbear/releases/tag/DROPBEAR_2026.94) 的固定提交构建 ARM32 静态程序，增加两个本地适配补丁。
- 编译时关闭密码和 PAM 认证，仅保留 Ed25519 公钥认证；私钥只留在管理电脑。
- 服务绑定路由器 LAN IPv4 地址和 `br0`，按 LAN CIDR 限制 SSH 入站；不监听 IPv6，并增加 IPv6 TCP 22 丢弃规则。
- 程序保存在 `/Plugin/local-ssh`；主机私钥和授权公钥保存在 `/usercfg/local-ssh`。不使用固件自带的共享主机密钥。
- 使用 `/var/run/local-ssh-pts` 私有 devpts，启动脚本在需要时创建。目录 `0700`，PTY 节点初始权限 `0600`。不替换全局 `/dev`。
- 不修改 `/etc`、系统启动脚本或固件分区。可手动启动，或使用管理电脑上的可选按需恢复桥接器。
- `-j -k` 禁用端口转发。本方案是管理终端，不是转发服务。

**“SSH 只接受密钥”不等于删除所有密码管理入口。** 按需恢复方案依赖保留的 LAN Telnet 及其本地凭据；网页管理仍使用自己的认证方式。

## 1. 从固定源码构建

在 Linux 构建机准备交叉编译工具。例如 Debian／Ubuntu：

```sh
sudo apt-get install git make gcc-arm-linux-gnueabi libc6-dev-armel-cross
sh scripts/build-dropbear.sh "$HOME/sr7420-dropbear-build"
```

构建目录必须是仓库之外的新目录。脚本会校验上游提交：

```text
28216cd9af822732a1549b78621c2ea9a76a0fe5
```

然后应用 [PTY／信号补丁](../patches/dropbear-2026.94-sr7420-pty.patch)，构建 `dropbearmulti` 与版本记录。输出位于 `output/`。编译器和 libc 版本可能影响输出哈希；源码提交固定不等于不同机器上的二进制必然逐字节一致。

`dropbearmulti` 同时包含服务端和 `dropbearkey`，通过不同名字的符号链接选择功能。它是**修改版**，不能当作官方原样发布包。仓库不提供预编译二进制。

## 2. 生成管理电脑专用密钥与离线部署包

在管理电脑执行；若文件已存在，先核对用途，不要覆盖：

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_sr7420 -C sr7420-admin
```

按自己的使用需求设置私钥口令，并确保私钥文件仅自己可读。仅把 `.pub` 公钥交给部署工具；不要复制不带 `.pub` 的私钥。

```sh
python -m sr7420.ssh_setup --lan-ip 192.168.1.1 --lan-cidr 192.168.1.0/24 --public-key ~/.ssh/id_ed25519_sr7420.pub --output-dir ~/sr7420-private/ssh-bundle
```

部署包包含 `authorized_keys`、`lan.conf` 和 `start.sh`。公钥注释会被剥离，工具只接受一个结构正确的 Ed25519 公钥和匹配的 RFC1918 LAN 地址／网段。它不生成 SSH 私钥，不连接路由器，也不自动部署。

把上一步构建的 `dropbearmulti` 复制到这个独立部署目录。该目录**不得混入** Telnet 凭据、配置备份或 SSH 私钥。

## 3. 部署到自己的路由器

通过现有 root Telnet 通道操作。若以下两个目录已经存在，先检查并备份已有内容，不要直接覆盖：

```sh
mkdir -p /Plugin/local-ssh /usercfg/local-ssh
chmod 700 /Plugin/local-ssh /usercfg/local-ssh
```

将文件传输到以下位置：

| 本地部署文件 | 路由器目标 |
| --- | --- |
| `dropbearmulti` | `/Plugin/local-ssh/dropbearmulti` |
| `start.sh` | `/Plugin/local-ssh/start.sh` |
| `authorized_keys` | `/usercfg/local-ssh/authorized_keys` |
| `lan.conf` | `/usercfg/local-ssh/lan.conf` |

若 Telnet 通道不方便传文件，可以在可信 LAN 的管理电脑临时提供**仅部署目录**的只读 HTTP 文件服务：

```sh
python -m http.server 18080 --bind 192.168.1.2 --directory ~/sr7420-private/ssh-bundle
```

这里的管理电脑地址同样只是示例。仅允许自己的路由器访问这个临时端口，传输完成立即关闭服务。不要提供整个家目录或 `sr7420-private` 父目录。HTTP 传输本身不提供机密性或来源认证，只应在受控可信 LAN 使用。

路由器上逐项获取，传输报错立即停止：

```sh
curl -f --max-time 20 -o /Plugin/local-ssh/dropbearmulti http://192.168.1.2:18080/dropbearmulti
curl -f --max-time 20 -o /Plugin/local-ssh/start.sh http://192.168.1.2:18080/start.sh
curl -f --max-time 20 -o /usercfg/local-ssh/authorized_keys http://192.168.1.2:18080/authorized_keys
curl -f --max-time 20 -o /usercfg/local-ssh/lan.conf http://192.168.1.2:18080/lan.conf
chmod 755 /Plugin/local-ssh/dropbearmulti /Plugin/local-ssh/start.sh
chmod 600 /usercfg/local-ssh/authorized_keys /usercfg/local-ssh/lan.conf
ln -s dropbearmulti /Plugin/local-ssh/dropbear
ln -s dropbearmulti /Plugin/local-ssh/dropbearkey
```

先执行 `/Plugin/local-ssh/dropbear -V` 确认能运行。如果出现架构错误、缺少解释器或非法指令，停止，不要修改系统 libc。

在路由器上生成自己的主机密钥，**已有密钥时不要重复生成或覆盖**：

```sh
/Plugin/local-ssh/dropbearkey -t ed25519 -f /usercfg/local-ssh/host_ed25519
chmod 600 /usercfg/local-ssh/host_ed25519
/Plugin/local-ssh/dropbearkey -y -f /usercfg/local-ssh/host_ed25519
```

最后一条只用于查看主机公钥／指纹。将这一经已认证管理通道核对的公钥保存到管理电脑专用 `known_hosts` 文件，格式为：

```text
sr7420-lan ssh-ed25519 REPLACE_WITH_VERIFIED_HOST_PUBLIC_KEY_BASE64
```

不要把 `host_ed25519` 私钥当作公钥复制出去，也不要以未经比对的 `ssh-keyscan` 输出替代身份核验。

```sh
sh -n /Plugin/local-ssh/start.sh
/Plugin/local-ssh/start.sh
netstat -lnt
```

应看到指定的 LAN IPv4 地址监听 TCP 22，不应看到 `0.0.0.0:22` 或 IPv6 的 SSH 监听。脚本遇到已有但不匹配的专用 SSH 防火墙链会停止，要求先人工核对，避免清空已有策略。

## 4. 配置 SSH 客户端

在自己的 `~/.ssh/config` 中新建独立别名。以下账号名称是占位符，必须替换为之前查到的 UID 0 用户名；地址和密钥路径同样按本机调整：

```sshconfig
Host my-sr7420
  HostName 192.168.1.1
  User REPLACE_WITH_UID0_USER
  IdentityFile ~/.ssh/id_ed25519_sr7420
  IdentitiesOnly yes
  ForwardAgent no
  PasswordAuthentication no
  KbdInteractiveAuthentication no
  HostKeyAlias sr7420-lan
  UserKnownHostsFile ~/.ssh/known_hosts_sr7420
  StrictHostKeyChecking yes
  ConnectTimeout 8
```

先用它登录并检查：

```sh
ssh my-sr7420
```

## 5. 必须验证交互终端，而不只是远程命令

在真正的终端中进入 SSH，不附带远程命令，然后输入：

```sh
id
test -t 0; echo $?
sleep 120
```

- `id` 应实际显示 `uid=0`。
- `test -t 0` 的退出码应为 `0`。
- 按 **Ctrl+C**，`sleep` 应立即被中断并回到 shell 提示符。
- 再输入一个简单命令确认终端可继续使用，最后 `exit` 正常退出。

还应检查错误密钥不能登录、密码认证不可用，以及从外部网络访问 WAN IPv4／IPv6 的 TCP 22 均失败。服务监听地址、接口绑定和防火墙应分别核对。

**不要用立即关闭 stdin 的管道测试替代真实终端。** 在排障时，这类测试曾让 PTY 在子进程建立控制终端前被挂断，产生 `TIOCSCTTY: Input/output error`。这与终端中真实保持 stdin 打开的 SSH 会话不同。

## PTY 和 Ctrl+C 修复原理

### `PTY allocation request failed` / `shell request failed`

本次固件没有标准 `/dev/pts`。原先的 Dropbear 使用 `openpty()`，服务端日志为 `openpty: No such file or directory`；执行非 PTY 命令却能成功，所以仅测试 `ssh host id` 会漏掉这个问题。

修复是在 `/var/run/local-ssh-pts` 挂载独立 devpts，使用该实例的 `ptmx` 分配主端，通过 `TIOCSPTLCK` 解锁、`TIOCGPTN` 获取编号，再打开对应从端。修改仅落在本地 Dropbear 的 `pty_allocate()` 适配中，没有替换全局 `/dev`，也不需要写只读系统分区。

### 已进入 shell，但 Ctrl+C 不起作用

POSIX 进程会继承信号屏蔽状态。本次 Telnet 启动环境把 SIGINT／SIGPIPE 的屏蔽状态传给了 SSH，继而传给 shell。终端虽然显示 `^C`，命令却没有被及时中断。

补丁在 SSH 服务端入口用空集合重设信号掩码，再由 Dropbear 安装自己的信号处理逻辑。实机确认新的会话不再继承该屏蔽，Ctrl+C 可立即中断前台命令。

## 可选：只在连接时恢复 SSH

本次固件的系统分区不能正常改为可写；没有安装原生启动钩子。**不要为了照抄自启动教程去强改分区或刷固件。** 程序和密钥可以保存在持久化目录，但 `/var` 下的 PTY 环境重启后会消失，需要重新运行启动脚本。

仓库提供可选的 `ProxyCommand` 桥接器：TCP 22 可用时只转发字节；不可用时读取你本地保存的 Telnet 凭据，登录同一个 LAN 地址，仅调用固定的 `/Plugin/local-ssh/start.sh`，随后继续传递 SSH 流量。它不读取 SSH 私钥，不跳过 SSH 主机密钥验证，不后台轮询、不创建计划任务。

在客户端配置中增加下面一行，替换 Python 路径和本地凭据路径。带空格的路径须正确加双引号。使用已安装本项目的 Python：

```sshconfig
  ProxyCommand /ABSOLUTE/PATH/TO/python -m sr7420.ssh_bridge --host %h --credentials /ABSOLUTE/PRIVATE/PATH/telnet-credentials.json
```

Windows 示例（路径均为占位示例）：

```sshconfig
  ProxyCommand C:/Tools/sr7420/.venv/Scripts/python.exe -m sr7420.ssh_bridge --host %h --credentials C:/Private/sr7420/telnet-credentials.json
```

必须保留前面的 `StrictHostKeyChecking yes`、专用主机公钥和专用客户端私钥配置。凭据中的 host 必须与 `%h` 完全一致，桥接器不会跟随任意目标地址。SSH 密码登录仍被禁用，但恢复阶段使用的 **Telnet 密码管理通道仍然存在且为明文**；如不接受这一边界，就不用桥接器，改为在可信 LAN 手动启动 SSH。

## 回滚和限制

- 不要在其他人正在使用 SSH 时停止服务。先核对 `/var/run/local-ssh.pid` 对应的进程路径确为本项目 Dropbear，再停止该 PID。
- 保留旧二进制、启动脚本和主机密钥的本地受限备份。替换运行中的二进制应采用上传新文件后重命名，不能直接截断正在运行的文件。
- 私有 PTY 挂载仅在所有相关终端关闭后才可卸载；不要强制卸载或删除全局 `/dev` 下的节点。
- 移除客户端别名或 `ProxyCommand` 可停用按需恢复。仅删除本项目创建的 SSH 防火墙链／跳转；不要删除此前已有的规则。
- 本方案没有安装系统级自启动，固件升级、恢复出厂设置或厂商插件管理可能清除持久化文件。
- 历史实机验证包含真实交互 shell、Ctrl+C、停止 SSH 并卸载私有 PTY 后的重新连接恢复；**没有为这一验证再次重启整台路由器**。

构建脚本、通用部署包生成器和参数化启动模板通过离线／构建检查，不代表其他固件已获验证。不要上传自己的密钥、配置、终端记录或原始备份来报告问题。详见 [SECURITY.md](../SECURITY.md)。

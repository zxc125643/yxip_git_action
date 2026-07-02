# yxip_git_action

GitHub Actions 自动抓取 Cloudflare 优选 IPv4，生成 `ip.txt`。

当前默认来源：

- `https://www.wetest.vip/page/cloudflare/address_v4.html`
- `https://ip.164746.xyz`
- `https://cf.090227.xyz/ct?ips=20`
- `https://cf.090227.xyz/cu?ips=20`
- `https://cf.090227.xyz/cmcc?ips=20`

可在仓库 Variables 中设置 `EXTRA_SOURCES` 追加更多来源，多个 URL 用逗号、空格或换行分隔。

## IP 纯净度检查

默认只生成 `ip.txt`。如需检查 IP 纯净度，在仓库 `Settings -> Secrets and variables -> Actions -> Variables` 中设置：

- `CHECK_PURITY=true`：开启纯净度检查，额外生成 `ip_clean.txt` 和 `ip_purity.csv`。
- `PURITY_FILTER=true`：只把纯净 IP 写入 `ip.txt`。建议先观察 `ip_purity.csv` 后再开启。
- `OUTPUT_WITH_REMARKS=true`：开启纯净度时按 `ip#地区-纯净度分数` 格式输出；设为 `false` 可退回纯 IP。
- `EXPECTED_ASN=13335,209242`：期望的 Cloudflare ASN，可按需调整。
- `REQUIRE_EXPECTED_ASN=true`：非期望 ASN 直接判为 dirty。
- `MIN_PURITY_SCORE=4.2`：低于该分值不进入 `ip_clean.txt`。
- `EXTRA_SOURCES=...`：追加抓取源。

可选 Secret：

- `IPAPI_KEY`：`ipapi.is` API key；不设置也可使用匿名额度。

`ip_purity.csv` 会标记 `clean`、`warning`、`dirty` 或 `unknown`，并输出 ASN、国家、网络类型、是否 proxy/VPN/Tor/abuser、来源等字段。

开启纯净度后，`ip.txt` 和 `ip_clean.txt` 默认输出短备注，避免部分订阅生成器被空格解析坏：

```txt
104.17.175.237#CF-4.8分
172.67.174.74#CF-4.8分
```

同时会生成 `ip_plain.txt`，只包含纯净 IP、不带任何备注。若 `ip.txt` 订阅后无网络，可先用 `ip_plain.txt` 判断是否为备注格式兼容问题。

纯净度参考视频里的思路：重点看风险值、是否已知滥用、是否代理服务器、落地 IP 信息页是否大多为绿色，以及最终纯净度分值。脚本用 5 分制近似表达：

- `4.8-5.0`：`extremely_clean`
- `4.2-4.7`：`clean`
- `3.2-4.1`：`normal`
- `2.0-3.1`：`high_risk`
- `<2.0`：`extreme_risk`

`is_abuser`、`is_proxy`、`is_tor`、`is_bogon`、高风险标签、非期望 ASN 会直接判为 `dirty`；`is_vpn` 只降分，因为 Cloudflare/CDN IP 可能有误判。Cloudflare IP 属于 CDN/机房网络，`is_datacenter=true` 是正常现象，不作为脏 IP 判断条件。

测试页面：

- `https://www.itdog.cn/ping/zzzyxhkfc.pages.dev`

## 订阅转换配置

仓库内置了一个带 AI 分流和国内图片/CDN 直连修正的订阅转换配置：

- `custom/ACL4SSR_Online_Mini_MultiMode_AI_CNFix.ini`

使用方式：

1. 后台进入“订阅转换配置”。
2. “订阅转换配置文件”选择“自定义”。
3. 填入 raw 链接：

```txt
https://raw.githubusercontent.com/zxc125643/yxip_git_action/main/custom/ACL4SSR_Online_Mini_MultiMode_AI_CNFix.ini
```

这个配置会新增 `🤖 AI` 策略组，并让国内常见图片、静态资源、对象存储和 CDN 域名优先直连。为避免国内商品图、头像、封面图被误杀，默认不启用广告拦截规则。

如果 AI 应用同时命中 `🤖 AI` 和 `🐟 漏网之鱼`，通常表示该应用有部分登录、风控、统计、资源域名没有被公开 AI 规则覆盖。仓库额外维护了：

- `custom/AI_Supplement.list`

这个补充列表会优先归入 `🤖 AI`。同时 `🐟 漏网之鱼` 策略组也加入了 `🤖 AI` 选项；如果某个 AI 应用仍然有请求落到漏网之鱼，可以临时把 `🐟 漏网之鱼` 也选到 `🤖 AI`，用于保持同一出口 IP 排查。

## 本地 Cloudflare 机房检测

`ipapi.is` 的国家信息不适合判断 Cloudflare Anycast IP 的真实接入地区。要看本地网络实际进哪个 Cloudflare 机房，请在本地 Linux 电脑上运行：

```bash
git clone https://github.com/zxc125643/yxip_git_action.git
cd yxip_git_action
python3 scripts/local_cf_trace.py --host 你的Cloudflare域名 --input ip.txt --workers 16
```

示例：

```bash
python3 scripts/local_cf_trace.py --host edgar.vegaavc.cn --input ip.txt --workers 16
```

输出文件：

- `ip_trace.csv`：详细检测报告，包含 `colo`、`loc`、延迟、错误信息。
- `ip_traced.txt`：可读备注列表，例如 `104.17.x.x#新加坡-SIN-4.8分`。

注意：这个脚本必须在你实际使用的网络里运行。家宽、电信、联通、移动、VPS 跑出来的 `colo` 都可能不同。`colo` 是 Cloudflare 接入机房代码；`loc` 是发起请求的客户端国家，不代表机房国家。

## Linux 定时任务合并

你的 Linux 电脑上现有两类任务：

- `update_proxyip.sh`：每天更新 Worker 的 `PROXYIP` / `PROXYIP_LIST`，但旧脚本依赖 `httpx`。
- `run_manage.sh`：发现并测速 SOCKS5，更新 Worker Secret `SOCKS5`。

仓库内新增了一个合并入口：

```bash
bash scripts/linux_daily_update.sh
```

推荐在 Linux 上用它替代原来的 `update_proxyip.sh`。它会先拉取 GitHub 最新 IP 结果，再从本地网络跑 `local_cf_trace.py`，然后用 `select_trace_ips.py` 按本地延迟和纯净度选出前 5 个 IP，部署到 Worker 的 `PROXYIP` / `PROXYIP_LIST`，最后继续调用原有 `manage.py run` 更新 SOCKS5。

示例 crontab：

```cron
0 5 * * * cd /home/yi/yxip_git_action_trace && TRACE_HOST=edgar.vegaavc.cn EDGAR_DIR=/home/yi/projects/edgar3.0 PUSH_TRACE=true bash scripts/linux_daily_update.sh >> linux_daily_update.log 2>&1
```

常用开关：

- `TRACE_INPUT=ip_clean.txt`：默认使用纯净 IP；没有该文件时自动退回 `ip.txt`。
- `TOP_N=5`：部署到 Worker 的 IP 数量。
- `MIN_PURITY_SCORE=4.2`：如果 trace 结果带纯净度，只选不低于该 5 分制分数的 IP。
- `DEPLOY_WORKER=false`：只测速和生成结果，不部署 Worker。
- `RUN_SOCKS5=false`：只更新 Cloudflare 优选 IP，不刷新 SOCKS5。
- `PUSH_TRACE=true`：把 `ip_trace.csv`、`ip_traced.txt`、`cf_proxyip_list.txt` 和 `cf_proxyip_labels.txt` 推回 GitHub。
- `PULL_REPO=false`：本地试跑时跳过 `git pull`。
- `CUSTOM_SOCKS5=用户:密码@IP:端口`：使用自己的 SOCKS5，并写入 Worker Secret `SOCKS5`。
- `CUSTOM_SOCKS5_FILE=/path/to/socks5.txt`：从文件第一行读取自己的 SOCKS5，避免把账号密码直接写进 crontab。

注意：SOCKS5 只是 Worker 的上游/中继能力，不建议把免费 SOCKS5 节点直接混进订阅 IP 列表。订阅侧继续使用 Cloudflare 优选 IP，Worker 侧再用 SOCKS5 做兜底或链式代理。

如果你使用自己的 SOCKS5，推荐在 `/home/yi/projects/edgar3.0/.env` 增加：

```bash
CUSTOM_SOCKS5_FILE=/home/yi/projects/edgar3.0/custom_socks5.txt
```

然后把 SOCKS5 写到该文件第一行，格式为：

```txt
用户:密码@IP:端口
```

如果没有账号密码，则写：

```txt
IP:端口
```

这里不要加 `socks5://` 前缀；Worker Secret 里只需要地址本体。

## macOS 定时任务迁移

macOS 不使用 systemd，推荐用用户级 `launchd` 定时运行。仓库新增了 macOS wrapper：

```bash
bash scripts/macos_daily_update.sh
```

它会复用 `scripts/linux_daily_update.sh` 的主逻辑，并额外处理 macOS 常见 PATH、当前仓库路径和本机配置文件。

本机配置文件：

```bash
cp scripts/macos_daily_update.env.example scripts/macos_daily_update.env
```

常用配置：

- `TRACE_HOST=edgar.vegaavc.cn`：用于本地 Cloudflare trace 的域名。
- `EDGAR_DIR=$HOME/projects/edgar3.0`：Worker 项目目录。
- `DEPLOY_WORKER=false`：未迁移 Worker 项目前建议保持关闭。
- `RUN_SOCKS5=false`：未迁移 `manage.py` 前建议保持关闭。
- `PUSH_TRACE=false`：需要把本机 trace 结果推回 GitHub 时再开启。

安装每天 05:00 运行的 LaunchAgent：

```bash
REPO_DIR="$(pwd)"
mkdir -p "$HOME/Library/LaunchAgents" "$REPO_DIR/logs"
sed "s#__REPO_DIR__#$REPO_DIR#g" \
  launchd/com.zxc125643.yxip-daily-update.plist.template \
  > "$HOME/Library/LaunchAgents/com.zxc125643.yxip-daily-update.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.zxc125643.yxip-daily-update.plist"
launchctl enable "gui/$(id -u)/com.zxc125643.yxip-daily-update"
```

立即试跑一次：

```bash
launchctl kickstart -k "gui/$(id -u)/com.zxc125643.yxip-daily-update"
```

查看日志：

```bash
tail -f logs/macos_daily_update.out.log logs/macos_daily_update.err.log
```

卸载定时任务：

```bash
launchctl bootout "gui/$(id -u)/com.zxc125643.yxip-daily-update"
rm "$HOME/Library/LaunchAgents/com.zxc125643.yxip-daily-update.plist"
```

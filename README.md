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
- `OUTPUT_WITH_REMARKS=true`：开启纯净度时按 `ip#地区-纯净度百分比` 格式输出；设为 `false` 可退回纯 IP。
- `EXPECTED_ASN=13335,209242`：期望的 Cloudflare ASN，可按需调整。
- `REQUIRE_EXPECTED_ASN=true`：非期望 ASN 直接判为 dirty。
- `MIN_PURITY_SCORE=4.2`：低于该分值不进入 `ip_clean.txt`。
- `EXTRA_SOURCES=...`：追加抓取源。

可选 Secret：

- `IPAPI_KEY`：`ipapi.is` API key；不设置也可使用匿名额度。

`ip_purity.csv` 会标记 `clean`、`warning`、`dirty` 或 `unknown`，并输出 ASN、国家、网络类型、是否 proxy/VPN/Tor/abuser、来源等字段。

开启纯净度后，`ip.txt` 和 `ip_clean.txt` 默认输出短备注，避免部分订阅生成器被空格解析坏：

```txt
104.17.175.237#美国-96%
172.67.174.74#加拿大-96%
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
- `ip_traced.txt`：可读备注列表，例如 `104.17.x.x#美国-SJC-96%`。

注意：这个脚本必须在你实际使用的网络里运行。家宽、电信、联通、移动、VPS 跑出来的 `colo` 都可能不同。`colo` 是 Cloudflare 接入机房代码；`loc` 是发起请求的客户端国家，不代表机房国家。

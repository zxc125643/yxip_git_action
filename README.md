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
104.17.175.237#美国-California-San_Francisco-96%
172.67.174.74#加拿大-Ontario-Toronto-96%
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

import csv
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


SOURCES = [
    {"name": "wetest", "url": "https://www.wetest.vip/page/cloudflare/address_v4.html"},
    {"name": "ip164746", "url": "https://ip.164746.xyz"},
    {"name": "cf090227-ct", "url": "https://cf.090227.xyz/ct?ips=20"},
    {"name": "cf090227-cu", "url": "https://cf.090227.xyz/cu?ips=20"},
    {"name": "cf090227-cmcc", "url": "https://cf.090227.xyz/cmcc?ips=20"},
]

IP_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
USER_AGENT = "yxip_git_action/2.0 (+https://github.com/JERRYZFC/yxip_git_action)"

COUNTRY_NAMES_ZH = {
    "AU": "澳大利亚",
    "BR": "巴西",
    "CA": "加拿大",
    "DE": "德国",
    "FR": "法国",
    "GB": "英国",
    "HK": "香港",
    "HU": "匈牙利",
    "ID": "印度尼西亚",
    "IN": "印度",
    "JP": "日本",
    "KR": "韩国",
    "NL": "荷兰",
    "RU": "俄罗斯",
    "SG": "新加坡",
    "TH": "泰国",
    "TW": "台湾",
    "US": "美国",
    "VN": "越南",
}

PURITY_LEVEL_NAMES_ZH = {
    "extremely_clean": "极度纯净",
    "clean": "纯净",
    "normal": "普通",
    "high_risk": "高风险",
    "extreme_risk": "极度风险",
    "unknown": "未知",
}


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_sources():
    sources = list(SOURCES)
    extra_sources = os.getenv("EXTRA_SOURCES", "")
    for url in re.split(r"[\s,]+", extra_sources.strip()):
        if url:
            sources.append({"name": f"extra-{len(sources) + 1}", "url": url})
    return sources


def is_public_ipv4(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_global


def extract_ips(text):
    ips = []
    seen = set()
    for ip in IP_PATTERN.findall(text):
        if ip not in seen and is_public_ipv4(ip):
            ips.append(ip)
            seen.add(ip)
    return ips


def fetch_source(source, timeout=20):
    request = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
        text = body.decode(charset, errors="ignore")
        return {
            "name": source["name"],
            "url": source["url"],
            "ips": extract_ips(text),
            "error": "",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "name": source["name"],
            "url": source["url"],
            "ips": [],
            "error": str(exc),
        }


def collect_ips(sources):
    results = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(sources)))) as executor:
        for result in executor.map(fetch_source, sources):
            results.append(result)

    ip_sources = {}
    ordered_ips = []
    for result in results:
        if result["error"]:
            print(f"WARN source failed: {result['name']} {result['url']} ({result['error']})", file=sys.stderr)
        else:
            print(f"OK {result['name']}: {len(result['ips'])} IPs")
        for ip in result["ips"]:
            if ip not in ip_sources:
                ip_sources[ip] = []
                ordered_ips.append(ip)
            ip_sources[ip].append(result["name"])
    return ordered_ips, ip_sources


def chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def ipapi_lookup(ips, timeout=30):
    if not ips:
        return {}

    api_key = os.getenv("IPAPI_KEY", "").strip()
    records = {}
    for chunk in chunks(ips, 100):
        payload = {"ips": chunk}
        if api_key:
            payload["key"] = api_key

        request = urllib.request.Request(
            "https://api.ipapi.is",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict):
                records.update(data)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            print(f"WARN purity lookup failed for {len(chunk)} IPs: {exc}", file=sys.stderr)
            for ip in chunk:
                records[ip] = {"error": str(exc)}
    return records


def parse_expected_asns():
    raw = os.getenv("EXPECTED_ASN", "13335,209242")
    expected = set()
    for value in re.split(r"[\s,]+", raw.strip()):
        if not value:
            continue
        try:
            expected.add(int(value.removeprefix("AS").removeprefix("as")))
        except ValueError:
            print(f"WARN ignoring invalid EXPECTED_ASN value: {value}", file=sys.stderr)
    return expected


def env_float(name, default):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        print(f"WARN ignoring invalid {name} value: {value}", file=sys.stderr)
        return default


def parse_risk_label(value):
    if not value:
        return ""
    match = re.search(r"\(([^)]+)\)", str(value))
    return match.group(1).strip().lower() if match else ""


def risk_penalty(label):
    return {
        "very low": 0.0,
        "low": 0.0,
        "elevated": 0.2,
        "medium": 0.7,
        "moderate": 0.7,
        "high": 1.8,
        "very high": 3.0,
        "extreme": 3.0,
    }.get(label, 0.0)


def purity_level(score):
    if score >= 4.8:
        return "extremely_clean"
    if score >= 4.2:
        return "clean"
    if score >= 3.2:
        return "normal"
    if score >= 2.0:
        return "high_risk"
    return "extreme_risk"


def format_region(location):
    country_code = str(location.get("country_code") or "").upper()
    return COUNTRY_NAMES_ZH.get(country_code) or location.get("country") or country_code or "未知地区"


def format_remark_region(record):
    source = os.getenv("REMARK_REGION_SOURCE", "provider").strip().lower()
    if source == "ipapi":
        return format_region(record.get("location") or {})
    if source == "none":
        return ""

    asn = record.get("asn") or {}
    company = record.get("company") or {}
    cloudflare_text = " ".join(
        str(value or "")
        for value in (
            asn.get("org"),
            asn.get("descr"),
            asn.get("domain"),
            company.get("name"),
            company.get("domain"),
        )
    ).lower()
    if "cloudflare" in cloudflare_text:
        return "CF"

    asn_number = asn.get("asn")
    return f"AS{asn_number}" if asn_number else "节点"


def format_remark(value):
    value = re.sub(r"\s+", "_", str(value).strip())
    value = value.replace("#", "-")
    return value or "unknown"


def purity_percent(purity):
    score = purity["score"]
    if score == "":
        return ""
    return f"{round(float(score) / 5 * 100)}%"


def purity_score_text(purity):
    score = purity["score"]
    if score == "":
        return ""
    return f"{float(score):.1f}分"


def format_purity_text(purity):
    score_text = purity_score_text(purity)
    if score_text:
        return score_text
    return PURITY_LEVEL_NAMES_ZH.get(purity["level"], purity["level"] or "未知")


def format_remark_line(ip, record, purity):
    region = format_remark(format_remark_region(record))
    purity_text = format_remark(format_purity_text(purity))
    return f"{ip}#{region}-{purity_text}" if region else f"{ip}#{purity_text}"


def classify_purity(record, expected_asns):
    min_score = env_float("MIN_PURITY_SCORE", 4.2)
    require_expected_asn = env_bool("REQUIRE_EXPECTED_ASN", True)

    if not record or record.get("error"):
        return {
            "status": "unknown",
            "score": "",
            "level": "unknown",
            "reasons": ["lookup_failed"],
            "risk_label": "",
        }

    score = 5.0
    reasons = []
    hard_bad = False

    penalties = {
        "is_bogon": 5.0,
        "is_tor": 3.0,
        "is_proxy": 2.0,
        "is_vpn": 0.8,
        "is_abuser": 2.5,
    }
    hard_flags = {"is_bogon", "is_tor", "is_proxy", "is_abuser"}
    for flag, penalty in penalties.items():
        if record.get(flag) is True:
            reasons.append(flag)
            score -= penalty
            hard_bad = hard_bad or flag in hard_flags

    company = record.get("company") or {}
    asn_record = record.get("asn") or {}
    labels = [
        parse_risk_label(company.get("abuser_score")),
        parse_risk_label(asn_record.get("abuser_score")),
    ]
    label = max(labels, key=risk_penalty, default="")
    if label:
        score -= risk_penalty(label)
        if label in {"high", "very high", "extreme"}:
            hard_bad = True
            reasons.append(f"risk={label}")

    asn = asn_record.get("asn")
    if expected_asns and asn is not None:
        try:
            asn_number = int(asn)
            if asn_number not in expected_asns:
                score -= 1.5
                reasons.append(f"asn={asn_number}")
                hard_bad = hard_bad or require_expected_asn
        except (TypeError, ValueError):
            score -= 1.5
            reasons.append(f"asn={asn}")
            hard_bad = hard_bad or require_expected_asn

    score = max(0.0, round(score, 1))
    level = purity_level(score)
    if hard_bad or level in {"high_risk", "extreme_risk"}:
        status = "dirty"
    elif score < min_score:
        status = "warning"
    else:
        status = "clean"

    return {
        "status": status,
        "score": score,
        "level": level,
        "reasons": reasons,
        "risk_label": label,
    }


def write_ip_list(path, ips):
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        for ip in ips:
            file.write(f"{ip}\n")


def write_purity_outputs(ips, ip_sources, output_with_remarks):
    records = ipapi_lookup(ips)
    expected_asns = parse_expected_asns()

    rows = []
    clean_ips = []
    clean_output = []
    output_by_ip = {}
    for ip in ips:
        record = records.get(ip, {})
        purity = classify_purity(record, expected_asns)
        output_line = format_remark_line(ip, record, purity)
        output_by_ip[ip] = output_line
        if purity["status"] == "clean":
            clean_ips.append(ip)
            clean_output.append(output_line if output_with_remarks else ip)

        asn = record.get("asn") or {}
        location = record.get("location") or {}
        company = record.get("company") or {}
        region = format_region(location)
        rows.append(
            {
                "ip": ip,
                "remark": output_line,
                "region": region,
                "status": purity["status"],
                "purity_score": purity["score"],
                "purity_percent": purity_percent(purity),
                "purity_level": purity["level"],
                "risk_label": purity["risk_label"],
                "reasons": ";".join(purity["reasons"]),
                "asn": asn.get("asn", ""),
                "org": asn.get("org") or company.get("name", ""),
                "network_type": asn.get("type") or company.get("type", ""),
                "country": location.get("country_code", ""),
                "is_proxy": record.get("is_proxy", ""),
                "is_vpn": record.get("is_vpn", ""),
                "is_tor": record.get("is_tor", ""),
                "is_abuser": record.get("is_abuser", ""),
                "is_datacenter": record.get("is_datacenter", ""),
                "sources": ";".join(ip_sources.get(ip, [])),
            }
        )

    write_ip_list("ip_clean.txt", clean_output)
    write_ip_list("ip_plain.txt", clean_ips)
    with open("ip_purity.csv", "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()) if rows else ["ip", "status"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Purity: {len(clean_ips)}/{len(ips)} clean IPs")
    return clean_ips, output_by_ip


def main():
    sources = load_sources()
    ips, ip_sources = collect_ips(sources)
    if not ips:
        print("ERROR no IPs collected; refusing to overwrite ip.txt with an empty file", file=sys.stderr)
        return 1

    check_purity = env_bool("CHECK_PURITY")
    output_with_remarks = env_bool("OUTPUT_WITH_REMARKS", check_purity)

    if check_purity:
        clean_ips, output_by_ip = write_purity_outputs(ips, ip_sources, output_with_remarks)
        output_ips = clean_ips if env_bool("PURITY_FILTER") else ips
        if output_with_remarks:
            output_ips = [output_by_ip.get(ip, ip) for ip in output_ips]
    else:
        output_ips = ips

    write_ip_list("ip.txt", output_ips)
    print(f"Saved {len(output_ips)} IPs to ip.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

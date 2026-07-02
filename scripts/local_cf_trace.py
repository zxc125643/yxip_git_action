import argparse
import csv
import ipaddress
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


IP_RE = re.compile(r"^\s*((?:\d{1,3}\.){3}\d{1,3})")
PERCENT_RE = re.compile(r"(\d+%)")
SCORE_RE = re.compile(r"(?<!\d)([0-5](?:\.\d+)?)\s*(?:分|/5)")

COLO_COUNTRY_ZH = {
    "AMS": "荷兰",
    "ARN": "瑞典",
    "ATH": "希腊",
    "ATL": "美国",
    "BCN": "西班牙",
    "BKK": "泰国",
    "BLR": "印度",
    "BOM": "印度",
    "BRU": "比利时",
    "CDG": "法国",
    "CPH": "丹麦",
    "DFW": "美国",
    "DOH": "卡塔尔",
    "DUB": "爱尔兰",
    "DXB": "阿联酋",
    "EWR": "美国",
    "FCO": "意大利",
    "FRA": "德国",
    "GIG": "巴西",
    "GRU": "巴西",
    "HEL": "芬兰",
    "HKG": "香港",
    "IAD": "美国",
    "ICN": "韩国",
    "IST": "土耳其",
    "JFK": "美国",
    "JNB": "南非",
    "KIX": "日本",
    "KUL": "马来西亚",
    "LAX": "美国",
    "LHR": "英国",
    "MAD": "西班牙",
    "MAN": "英国",
    "MEL": "澳大利亚",
    "MEX": "墨西哥",
    "MNL": "菲律宾",
    "MRS": "法国",
    "MXP": "意大利",
    "NRT": "日本",
    "ORD": "美国",
    "OSL": "挪威",
    "PER": "澳大利亚",
    "PRG": "捷克",
    "SEA": "美国",
    "SFO": "美国",
    "SIN": "新加坡",
    "SJC": "美国",
    "SYD": "澳大利亚",
    "TLV": "以色列",
    "TPE": "台湾",
    "VIE": "奥地利",
    "WAW": "波兰",
    "YUL": "加拿大",
    "YVR": "加拿大",
    "YYZ": "加拿大",
    "ZRH": "瑞士",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test Cloudflare preferred IPs from this local network via /cdn-cgi/trace."
    )
    parser.add_argument("--host", required=True, help="Your Cloudflare hostname, for example example.com")
    parser.add_argument("--input", default="ip.txt", help="Input file containing IPs or ip#remarks")
    parser.add_argument("--output", default="ip_trace.csv", help="CSV output path")
    parser.add_argument("--purity-csv", default="ip_purity.csv", help="Optional purity CSV with raw scores")
    parser.add_argument(
        "--remark-output",
        default="ip_traced.txt",
        help="Optional remark list output, for example ip#SIN-4.8分. Use empty string to disable.",
    )
    parser.add_argument("--path", default="/cdn-cgi/trace", help="Trace path")
    parser.add_argument("--port", type=int, default=443, help="HTTPS port")
    parser.add_argument("--workers", type=int, default=16, help="Concurrent workers")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-IP timeout in seconds")
    parser.add_argument("--limit", type=int, default=0, help="Only test the first N IPs")
    return parser.parse_args()


def parse_purity_score(text):
    match = SCORE_RE.search(str(text or ""))
    if not match:
        return ""
    try:
        score = float(match.group(1))
    except ValueError:
        return ""
    if 0 <= score <= 5:
        return f"{score:.1f}"
    return ""


def load_purity_scores(path):
    scores = {}
    if not path:
        return scores
    try:
        with open(path, "r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                ip = str(row.get("ip", "")).strip()
                score = str(row.get("purity_score", "")).strip()
                if ip and score:
                    try:
                        scores[ip] = f"{float(score):.1f}"
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return scores


def parse_input(path, purity_csv=""):
    purity_scores = load_purity_scores(purity_csv)
    entries = []
    seen = set()
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            match = IP_RE.search(line)
            if not match:
                continue
            ip = match.group(1)
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                continue
            if ip in seen:
                continue
            seen.add(ip)
            percent_match = PERCENT_RE.search(line)
            score = parse_purity_score(line) or purity_scores.get(ip, "")
            entries.append(
                {
                    "ip": ip,
                    "input": line.strip(),
                    "purity_percent": percent_match.group(1) if percent_match else "",
                    "purity_score": score,
                }
            )
    return entries


def decode_chunked(body):
    pos = 0
    chunks = []
    while True:
        line_end = body.find(b"\r\n", pos)
        if line_end < 0:
            break
        size_text = body[pos:line_end].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            break
        pos = line_end + 2
        if size == 0:
            break
        chunks.append(body[pos : pos + size])
        pos += size + 2
    return b"".join(chunks) if chunks else body


def parse_http_response(raw):
    header_bytes, _, body = raw.partition(b"\r\n\r\n")
    headers_text = header_bytes.decode("iso-8859-1", errors="replace")
    header_lines = headers_text.splitlines()
    status_code = ""
    if header_lines:
        parts = header_lines[0].split()
        if len(parts) >= 2:
            status_code = parts[1]
    headers = {}
    for line in header_lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip().lower()
    if headers.get("transfer-encoding") == "chunked":
        body = decode_chunked(body)
    return status_code, body.decode("utf-8", errors="replace")


def parse_trace_body(text):
    trace = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        trace[key.strip()] = value.strip()
    return trace


def colo_region(colo):
    if not colo:
        return ""
    country = COLO_COUNTRY_ZH.get(colo.upper())
    return f"{country}-{colo.upper()}" if country else colo.upper()


def check_ip(entry, host, path, port, timeout):
    ip = entry["ip"]
    started = time.perf_counter()
    result = {
        "ip": ip,
        "ok": False,
        "status_code": "",
        "colo": "",
        "colo_region": "",
        "loc": "",
        "trace_ip": "",
        "http": "",
        "tls": "",
        "sni": "",
        "warp": "",
        "gateway": "",
        "elapsed_ms": "",
        "purity_percent": entry.get("purity_percent", ""),
        "purity_score": entry.get("purity_score", ""),
        "input": entry.get("input", ""),
        "error": "",
    }
    try:
        context = ssl.create_default_context()
        context.set_alpn_protocols(["http/1.1"])
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                tls_sock.settimeout(timeout)
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "User-Agent: local-cf-trace/1.0\r\n"
                    "Accept: text/plain,*/*;q=0.8\r\n"
                    "Connection: close\r\n\r\n"
                )
                tls_sock.sendall(request.encode("ascii"))
                chunks = []
                while True:
                    data = tls_sock.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        status_code, body = parse_http_response(b"".join(chunks))
        trace = parse_trace_body(body)
        result.update(
            {
                "ok": status_code == "200" and bool(trace.get("colo")),
                "status_code": status_code,
                "colo": trace.get("colo", ""),
                "colo_region": colo_region(trace.get("colo", "")),
                "loc": trace.get("loc", ""),
                "trace_ip": trace.get("ip", ""),
                "http": trace.get("http", ""),
                "tls": trace.get("tls", ""),
                "sni": trace.get("sni", ""),
                "warp": trace.get("warp", ""),
                "gateway": trace.get("gateway", ""),
            }
        )
        if not result["ok"]:
            result["error"] = "missing trace data"
    except Exception as exc:
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def trace_remark(row):
    if row["ok"]:
        region = row.get("colo_region") or row["colo"]
    else:
        region = "TRACE_FAIL"
    score = row.get("purity_score") or ""
    return f"{row['ip']}#{region}-{score}分" if score else f"{row['ip']}#{region}"


def write_outputs(results, output_path, remark_output):
    fieldnames = [
        "ip",
        "ok",
        "status_code",
        "colo",
        "colo_region",
        "loc",
        "trace_ip",
        "http",
        "tls",
        "sni",
        "warp",
        "gateway",
        "elapsed_ms",
        "purity_percent",
        "purity_score",
        "input",
        "error",
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)

    if remark_output:
        with open(remark_output, "w", encoding="utf-8", newline="\n") as file:
            for row in results:
                if row["ok"]:
                    file.write(trace_remark(row) + "\n")


def main():
    args = parse_args()
    entries = parse_input(args.input, args.purity_csv)
    if args.limit > 0:
        entries = entries[: args.limit]
    if not entries:
        raise SystemExit(f"No valid IPs found in {args.input}")

    results_by_ip = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(check_ip, entry, args.host, args.path, args.port, args.timeout)
            for entry in entries
        ]
        for future in as_completed(futures):
            row = future.result()
            results_by_ip[row["ip"]] = row
            status = "OK" if row["ok"] else "FAIL"
            print(
                f"{status} {row['ip']} colo={row['colo']} loc={row['loc']} "
                f"ms={row['elapsed_ms']} {row['error']}"
            )

    results = [results_by_ip[entry["ip"]] for entry in entries]
    write_outputs(results, args.output, args.remark_output)
    ok_count = sum(1 for row in results if row["ok"])
    print(f"Saved {len(results)} rows to {args.output}; {ok_count} successful traces.")
    if args.remark_output:
        print(f"Saved successful traced remarks to {args.remark_output}.")


if __name__ == "__main__":
    main()

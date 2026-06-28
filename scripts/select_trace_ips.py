import argparse
import csv
import re
import shlex


PERCENT_RE = re.compile(r"(\d{1,3})%")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Select Worker PROXYIP values from local Cloudflare trace results."
    )
    parser.add_argument("--input", default="ip_trace.csv", help="Input CSV from local_cf_trace.py")
    parser.add_argument("--count", type=int, default=5, help="Number of IPs to select")
    parser.add_argument(
        "--min-purity",
        type=int,
        default=80,
        help="Minimum purity percent when the trace row has purity data",
    )
    parser.add_argument(
        "--require-purity",
        action="store_true",
        help="Drop rows that do not contain a purity percent",
    )
    parser.add_argument("--env-output", default="cf_proxyip.env", help="Shell env output path")
    parser.add_argument("--list-output", default="cf_proxyip_list.txt", help="Comma-list output path")
    return parser.parse_args()


def truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok"}


def purity_percent(row):
    for key in ("purity_percent", "input"):
        text = str(row.get(key, ""))
        match = PERCENT_RE.search(text)
        if match:
            value = int(match.group(1))
            return max(0, min(100, value))
    return None


def elapsed_ms(row):
    try:
        return int(float(str(row.get("elapsed_ms", "")).strip()))
    except ValueError:
        return 999999999


def load_candidates(path, min_purity, require_purity):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if not truthy(row.get("ok")):
                continue
            ip = str(row.get("ip", "")).strip()
            if not ip:
                continue
            purity = purity_percent(row)
            if purity is None and require_purity:
                continue
            if purity is not None and purity < min_purity:
                continue
            rows.append(
                {
                    "ip": ip,
                    "elapsed_ms": elapsed_ms(row),
                    "purity_percent": purity,
                    "colo": str(row.get("colo", "")).strip(),
                    "colo_region": str(row.get("colo_region", "")).strip(),
                }
            )
    rows.sort(key=lambda row: (row["elapsed_ms"], -(row["purity_percent"] or 0), row["ip"]))
    return rows


def write_outputs(rows, count, env_output, list_output, source):
    selected = rows[:count]
    if not selected:
        raise SystemExit("No usable trace rows found")

    ips = [row["ip"] for row in selected]
    proxyip_list = ",".join(ips)
    best = ips[0]
    with open(list_output, "w", encoding="utf-8", newline="\n") as file:
        file.write(proxyip_list + "\n")

    env_values = {
        "PROXYIP": best,
        "PROXYIP_LIST": proxyip_list,
        "PROXYIP_COUNT": str(len(ips)),
        "PROXYIP_SOURCE": source,
    }
    with open(env_output, "w", encoding="utf-8", newline="\n") as file:
        for key, value in env_values.items():
            file.write(f"{key}={shlex.quote(value)}\n")

    print(f"Selected {len(ips)} IPs from {source}")
    for row in selected:
        purity = f"{row['purity_percent']}%" if row["purity_percent"] is not None else "n/a"
        region = row["colo_region"] or row["colo"] or "unknown"
        print(f"{row['ip']} ms={row['elapsed_ms']} purity={purity} colo={region}")


def main():
    args = parse_args()
    rows = load_candidates(args.input, args.min_purity, args.require_purity)
    write_outputs(rows, args.count, args.env_output, args.list_output, args.input)


if __name__ == "__main__":
    main()

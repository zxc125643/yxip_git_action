import argparse
import csv
import re
import shlex


PERCENT_RE = re.compile(r"(\d{1,3})%")
SCORE_RE = re.compile(r"(?<!\d)([0-5](?:\.\d+)?)\s*(?:分|/5)")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Select Worker PROXYIP values from local Cloudflare trace results."
    )
    parser.add_argument("--input", default="ip_trace.csv", help="Input CSV from local_cf_trace.py")
    parser.add_argument("--count", type=int, default=5, help="Number of IPs to select")
    parser.add_argument(
        "--min-purity",
        type=float,
        default=80,
        help="Backward-compatible minimum purity. Values above 5 are treated as legacy percent thresholds.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Minimum raw purity score on the 0-5 scale",
    )
    parser.add_argument(
        "--require-purity",
        action="store_true",
        help="Drop rows that do not contain a purity percent",
    )
    parser.add_argument("--env-output", default="cf_proxyip.env", help="Shell env output path")
    parser.add_argument("--list-output", default="cf_proxyip_list.txt", help="Comma-list output path")
    parser.add_argument("--labels-output", default="cf_proxyip_labels.txt", help="Node labels output path")
    parser.add_argument("--purity-csv", default="ip_purity.csv", help="Optional purity CSV with raw scores")
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


def purity_score(row):
    raw_score = str(row.get("purity_score", "")).strip()
    if raw_score:
        try:
            score = float(raw_score)
            if 0 <= score <= 5:
                return round(score, 1)
        except ValueError:
            pass

    for key in ("input", "colo_region"):
        match = SCORE_RE.search(str(row.get(key, "")))
        if match:
            try:
                score = float(match.group(1))
            except ValueError:
                continue
            if 0 <= score <= 5:
                return round(score, 1)
    return None


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
                if not ip or not score:
                    continue
                try:
                    value = float(score)
                except ValueError:
                    continue
                if 0 <= value <= 5:
                    scores[ip] = round(value, 1)
    except FileNotFoundError:
        pass
    return scores


def minimum_score(args):
    if args.min_score is not None:
        return args.min_score
    if args.min_purity > 5:
        return args.min_purity / 20
    return args.min_purity


def elapsed_ms(row):
    try:
        return int(float(str(row.get("elapsed_ms", "")).strip()))
    except ValueError:
        return 999999999


def load_candidates(path, min_score, require_purity, purity_csv):
    csv_scores = load_purity_scores(purity_csv)
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if not truthy(row.get("ok")):
                continue
            ip = str(row.get("ip", "")).strip()
            if not ip:
                continue
            score = purity_score(row)
            if score is None:
                score = csv_scores.get(ip)
            legacy_percent = purity_percent(row)
            if score is None and require_purity:
                continue
            if score is not None and score < min_score:
                continue
            rows.append(
                {
                    "ip": ip,
                    "elapsed_ms": elapsed_ms(row),
                    "purity_score": score,
                    "purity_percent": legacy_percent,
                    "colo": str(row.get("colo", "")).strip(),
                    "colo_region": str(row.get("colo_region", "")).strip(),
                }
            )
    rows.sort(key=lambda row: (row["elapsed_ms"], -(row["purity_score"] or 0), row["ip"]))
    return rows


def node_label(row):
    region = row["colo_region"] or row["colo"] or "unknown"
    score = f" {row['purity_score']:.1f}分" if row["purity_score"] is not None else ""
    return f"{row['ip']} {region}{score}"


def write_outputs(rows, count, env_output, list_output, labels_output, source):
    selected = rows[:count]
    if not selected:
        raise SystemExit("No usable trace rows found")

    ips = [row["ip"] for row in selected]
    labels = [node_label(row) for row in selected]
    proxyip_list = ",".join(ips)
    proxyip_labels = ",".join(labels)
    best = ips[0]
    with open(list_output, "w", encoding="utf-8", newline="\n") as file:
        file.write(proxyip_list + "\n")
    with open(labels_output, "w", encoding="utf-8", newline="\n") as file:
        for label in labels:
            file.write(label + "\n")

    env_values = {
        "PROXYIP": best,
        "PROXYIP_LIST": proxyip_list,
        "PROXYIP_LABELS": proxyip_labels,
        "PROXYIP_COUNT": str(len(ips)),
        "PROXYIP_SOURCE": source,
    }
    with open(env_output, "w", encoding="utf-8", newline="\n") as file:
        for key, value in env_values.items():
            file.write(f"{key}={shlex.quote(value)}\n")

    print(f"Selected {len(ips)} IPs from {source}")
    for row in selected:
        purity = f"{row['purity_score']:.1f}分" if row["purity_score"] is not None else "n/a"
        region = row["colo_region"] or row["colo"] or "unknown"
        print(f"{row['ip']} ms={row['elapsed_ms']} purity={purity} colo={region}")


def main():
    args = parse_args()
    rows = load_candidates(args.input, minimum_score(args), args.require_purity, args.purity_csv)
    write_outputs(rows, args.count, args.env_output, args.list_output, args.labels_output, args.input)


if __name__ == "__main__":
    main()

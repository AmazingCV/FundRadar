from __future__ import annotations

import argparse

from .backtest import run_backtest
from .pipeline import load_watchlist, market_scan, stage_return_compare
from .time_machine import run_time_machine, run_time_machine_batch
from .tracking import run_tracking
from .utils import load_config
from .weight_search import run_weight_search


def parse_horizons(text: str | None, default: dict[str, int]) -> dict[str, int]:
    if not text:
        return default
    mapping = {"1m": ("1月", 30), "3m": ("3月", 91), "6m": ("6月", 182), "12m": ("12月", 365)}
    out = {}
    for part in text.split(","):
        key = part.strip().lower()
        if key in mapping:
            name, days = mapping[key]
            out[name] = days
    return out or default


def main() -> None:
    parser = argparse.ArgumentParser(prog="fund_radar")
    parser.add_argument("--config", default="config/config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stage-compare")
    p.add_argument("--codes", default="")
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("market-scan")
    p.add_argument("--as-of", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-holdings", action="store_true")

    p = sub.add_parser("backtest")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)

    p = sub.add_parser("weight-search")
    p.add_argument("--train-start", default="2023-01-01")
    p.add_argument("--train-end", default="2025-06-18")
    p.add_argument("--valid-start", default="2025-06-18")
    p.add_argument("--valid-end", default=None)
    p.add_argument("--limit", type=int, default=None)

    p = sub.add_parser("tracking")
    p.add_argument("--as-of", default=None)
    p.add_argument("--limit", type=int, default=None)

    p = sub.add_parser("time-machine")
    p.add_argument("--as-of", required=True)
    p.add_argument("--horizon", default=None)
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)

    p = sub.add_parser("time-machine-batch")
    p.add_argument("--dates", default="")
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)

    p = sub.add_parser("run-full")
    p.add_argument("--as-of", default=None)
    p.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    config = load_config(args.config)
    if args.cmd == "stage-compare":
        codes = [c.strip() for c in args.codes.replace("，", ",").split(",") if c.strip()]
        if not codes:
            codes = load_watchlist()["基金代码"].tolist()
        res = stage_return_compare(codes, config=config, as_of=args.as_of)
    elif args.cmd == "market-scan":
        res = market_scan(config=config, as_of=args.as_of, limit=args.limit, with_holdings=not args.no_holdings)
    elif args.cmd == "backtest":
        res = run_backtest(config=config, start=args.start, end=args.end, top_n=args.top_n, limit=args.limit)
    elif args.cmd == "weight-search":
        res = run_weight_search(config=config, train_start=args.train_start, train_end=args.train_end, valid_start=args.valid_start, valid_end=args.valid_end, limit=args.limit)
    elif args.cmd == "tracking":
        res = run_tracking(config=config, as_of=args.as_of, limit=args.limit)
    elif args.cmd == "time-machine":
        horizons = parse_horizons(args.horizon, config.get("time_machine", {}).get("horizons", {}))
        res = run_time_machine(args.as_of, config=config, horizons=horizons, top_n=args.top_n, limit=args.limit)
    elif args.cmd == "time-machine-batch":
        dates = [d.strip() for d in args.dates.split(",") if d.strip()] or config.get("time_machine", {}).get("default_as_of_dates", [])
        res = {"summary": run_time_machine_batch(dates, config=config, top_n=args.top_n, limit=args.limit)}
    elif args.cmd == "run-full":
        stage_return_compare(load_watchlist()["基金代码"].tolist(), config=config, as_of=args.as_of)
        scan = market_scan(config=config, as_of=args.as_of, limit=args.limit)
        track = run_tracking(config=config, as_of=args.as_of, limit=args.limit)
        res = {"scan": scan, "tracking": track}
    else:
        raise SystemExit(f"unknown cmd {args.cmd}")
    out = res.get("output_dir") or res.get("excel_path") or res.get("report_path") or res
    print(f"完成，输出：{out}")


if __name__ == "__main__":
    main()

"""
Weekly retrain CLI for the KDE Adaptive Cascade strategy.

Run weekly (e.g. Sunday) to retrain on the latest panel:
    python3 -m atlas_v2.kde_train --tickers 500 --label default
"""

import argparse
from atlas_v2.kde_strategy import train_and_save


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="default",
                    help="Model bundle label (default produces adaptive_default.joblib).")
    ap.add_argument("--tickers", type=int, default=500,
                    help="Top-N most liquid tickers to train on.")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--include-bear", action="store_true",
                    help="Include BEAR regime in training (default skips).")
    args = ap.parse_args()

    meta = train_and_save(
        label=args.label,
        tickers_top_n=args.tickers,
        start_date=args.start,
        skip_bear=not args.include_bear,
    )
    print("\n=== Training meta ===")
    for k, v in meta.items():
        if k == "feature_cols":
            print(f"  {k}: {len(v)} features")
        elif isinstance(v, dict):
            print(f"  {k}: {len(v)} entries")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

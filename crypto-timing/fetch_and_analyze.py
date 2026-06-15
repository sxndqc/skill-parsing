"""
加密货币近60天波段分析
分析 BTC / ETH / SOL / ADA 的低点→高点时间与涨幅，以及随后的横盘与跌幅
依赖: pip install yfinance pandas numpy matplotlib
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# ── 配置 ──────────────────────────────────────────────
COINS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "ADA": "ADA-USD",
}
DAYS = 60
SWING_WINDOW = 5          # 判断局部高低点的左右窗口（天数）
SIDEWAYS_THRESHOLD = 0.04  # 横盘判定阈值：价格波动 < 4% 视为横盘


# ── 数据获取 ──────────────────────────────────────────
def fetch_ohlcv(ticker: str, days: int = 60) -> pd.DataFrame:
    end = datetime.today()
    start = end - timedelta(days=days + 5)
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                     end=end.strftime("%Y-%m-%d"), interval="1d", progress=False)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df.tail(days)


# ── 局部高低点检测 ────────────────────────────────────
def find_swing_points(df: pd.DataFrame, window: int = 5):
    highs, lows = [], []
    close = df["Close"].values
    dates = df.index

    for i in range(window, len(close) - window):
        segment = close[i - window: i + window + 1]
        if close[i] == segment.max():
            highs.append((dates[i], close[i]))
        if close[i] == segment.min():
            lows.append((dates[i], close[i]))

    return highs, lows


# ── 波段识别（低→高→横盘/跌） ────────────────────────
def find_swings(df: pd.DataFrame, window: int = 5):
    """
    返回每段波动结构：
    {low_date, low_price, high_date, high_price,
     rise_days, rise_pct,
     sideways_end_date, sideways_pct,
     drop_end_date, drop_pct}
    """
    highs, lows = find_swing_points(df, window)
    if not highs or not lows:
        return []

    swings = []
    close = df["Close"]

    for low_date, low_price in lows:
        # 找该低点之后最近的高点
        future_highs = [(d, p) for d, p in highs if d > low_date]
        if not future_highs:
            continue
        high_date, high_price = future_highs[0]

        rise_days = (high_date - low_date).days
        rise_pct = (high_price - low_price) / low_price * 100
        if rise_pct < 3:  # 忽略涨幅 < 3% 的噪声
            continue

        # 高点之后：检测横盘 or 直接下跌
        post = close[close.index > high_date]
        if post.empty:
            continue

        sideways_end = high_date
        sideways_pct = 0.0
        i = 0
        while i < len(post):
            window_prices = post.iloc[: i + 1]
            span = (window_prices.max() - window_prices.min()) / high_price
            if span > SIDEWAYS_THRESHOLD:
                break
            sideways_end = window_prices.index[-1]
            i += 1

        sideways_days = (sideways_end - high_date).days

        # 横盘结束后的跌幅（到下一个局部低点或数据末端）
        after_side = close[close.index > sideways_end]
        if after_side.empty:
            drop_pct = 0.0
            drop_days = 0
        else:
            drop_low = after_side.min()
            drop_low_date = after_side.idxmin()
            drop_pct = (drop_low - high_price) / high_price * 100
            drop_days = (drop_low_date - sideways_end).days

        swings.append({
            "low_date": low_date.strftime("%Y-%m-%d"),
            "low_price": round(low_price, 4),
            "high_date": high_date.strftime("%Y-%m-%d"),
            "high_price": round(high_price, 4),
            "rise_days": rise_days,
            "rise_pct": round(rise_pct, 2),
            "sideways_days": sideways_days,
            "sideways_pct": round(sideways_pct * 100, 2),
            "drop_days": drop_days,
            "drop_pct": round(drop_pct, 2),
        })

    return swings


# ── 图表绘制 ──────────────────────────────────────────
def plot_coin(ax, df: pd.DataFrame, swings: list, coin: str):
    ax.plot(df.index, df["Close"], color="#1f77b4", linewidth=1.5, label="收盘价")
    ax.set_title(f"{coin} — 近60天波段结构", fontsize=11, fontweight="bold")
    ax.set_ylabel("价格 (USD)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    colors = ["#e74c3c", "#2ecc71", "#f39c12"]
    for idx, s in enumerate(swings[:3]):  # 最多显示3段
        c = colors[idx % len(colors)]
        low_ts = pd.Timestamp(s["low_date"])
        high_ts = pd.Timestamp(s["high_date"])
        ax.annotate("", xy=(high_ts, s["high_price"]),
                    xytext=(low_ts, s["low_price"]),
                    arrowprops=dict(arrowstyle="->", color=c, lw=1.8))
        ax.scatter([low_ts, high_ts],
                   [s["low_price"], s["high_price"]],
                   color=c, zorder=5, s=40)
        mid_ts = low_ts + (high_ts - low_ts) / 2
        mid_price = (s["low_price"] + s["high_price"]) / 2
        ax.text(mid_ts, mid_price * 1.01,
                f"+{s['rise_pct']}%\n{s['rise_days']}天",
                fontsize=7, color=c, ha="center")

    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)


# ── 主函数 ───────────────────────────────────────────
def main():
    all_swings = {}
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"BTC / ETH / SOL / ADA  近60天波段分析\n(截至 {datetime.today().strftime('%Y-%m-%d')})",
                 fontsize=13, fontweight="bold")
    axes_flat = axes.flatten()

    print("=" * 70)
    print(f"加密货币波段分析  |  近60天  |  截至 {datetime.today().strftime('%Y-%m-%d')}")
    print("=" * 70)

    for idx, (coin, ticker) in enumerate(COINS.items()):
        print(f"\n{'─'*60}")
        print(f"  {coin} ({ticker})")
        print(f"{'─'*60}")

        df = fetch_ohlcv(ticker, DAYS)
        swings = find_swings(df, SWING_WINDOW)
        all_swings[coin] = swings

        plot_coin(axes_flat[idx], df, swings, coin)

        if not swings:
            print("  未检测到有效波段（数据不足或波动过小）")
            continue

        print(f"  {'低点日期':<12} {'低点价':<12} {'高点日期':<12} {'高点价':<12} "
              f"{'涨幅%':<8} {'涨天数':<6} {'横盘天':<7} {'跌幅%':<8} {'跌天数'}")
        for s in swings:
            print(f"  {s['low_date']:<12} {s['low_price']:<12} {s['high_date']:<12} "
                  f"{s['high_price']:<12} {s['rise_pct']:<8} {s['rise_days']:<6} "
                  f"{s['sideways_days']:<7} {s['drop_pct']:<8} {s['drop_days']}")

    plt.tight_layout()
    out_path = "swing_analysis.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\n\n图表已保存: {out_path}")

    # 输出 CSV
    rows = []
    for coin, swings in all_swings.items():
        for s in swings:
            rows.append({"coin": coin, **s})
    if rows:
        pd.DataFrame(rows).to_csv("swing_analysis.csv", index=False)
        print("数据已保存: swing_analysis.csv")

    print("\n分析完成。")


if __name__ == "__main__":
    main()

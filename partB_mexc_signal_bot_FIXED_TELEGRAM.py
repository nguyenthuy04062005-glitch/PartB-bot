"""
PART B - MEXC Futures Signal Bot
Đề Fintech giữa kỳ - Phần B: Robo-Advisor & Trading Futures

Mục tiêu:
- Quét tối thiểu 20 cặp USDT-M Futures trên MEXC.
- Tính tối thiểu 2 alpha độc lập: RSI, MACD, Volume Spike, Bollinger Bands.
- Chỉ phát tín hiệu/cảnh báo để sinh viên tự trade thủ công trên MEXC Futures Demo.
- KHÔNG đặt lệnh tự động, KHÔNG cần API key.

Cách chạy:
    pip install requests
    python partB_mexc_signal_bot.py

File log sinh ra:
    partB_signal_log.csv
    partB_market_snapshot_log.csv

Lưu ý:
- Bot dùng Public API, không đăng nhập tài khoản.
- Đây là bot hỗ trợ tín hiệu học tập, không phải lời khuyên đầu tư.
"""

import csv
import math
import os
import time
from datetime import datetime, timezone, timedelta
from statistics import mean, pstdev

import requests


# ============================================================
# 1. CONFIG - CÓ THỂ CHỈNH
# ============================================================

BASE_URL = "https://contract.mexc.com"

# Đề yêu cầu >= 20 cặp. Để 25 cho chắc.
SYMBOL_LIMIT = 25

# Quét mỗi 60 giây. Có thể giảm còn 30 nếu mạng khỏe.
SCAN_INTERVAL_SECONDS = 60

# Dùng nến 1 phút.
KLINE_INTERVAL = "Min1"

# Lấy 120 nến để tính chỉ báo ổn định hơn.
KLINE_LIMIT = 120

# Tránh báo trùng 1 symbol liên tục.
SIGNAL_COOLDOWN_SECONDS = 300

# Nếu muốn tự cố định danh sách cặp thì điền ở đây.
# Ví dụ:
# MANUAL_SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", ...]
# Nếu để rỗng, bot tự lấy top volume từ MEXC Futures.
MANUAL_SYMBOLS = []

# Danh sách dự phòng: dùng khi MEXC chặn request lấy danh sách top symbol lúc khởi động.
# Bot vẫn đạt yêu cầu >= 20 cặp nếu dùng danh sách này.
DEFAULT_SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT",
    "BNB_USDT", "ADA_USDT", "AVAX_USDT", "LINK_USDT", "LTC_USDT",
    "BCH_USDT", "DOT_USDT", "TRX_USDT", "NEAR_USDT", "APT_USDT",
    "SUI_USDT", "OP_USDT", "ARB_USDT", "WIF_USDT", "PEPE_USDT",
    "ORDI_USDT", "FIL_USDT", "ETC_USDT", "UNI_USDT", "AAVE_USDT"
]

HTTP_RETRY = 4
HTTP_RETRY_DELAY_SECONDS = 2


SIGNAL_LOG_FILE = "partB_signal_log.csv"
SNAPSHOT_LOG_FILE = "partB_market_snapshot_log.csv"

# ============================================================
# TELEGRAM ALERT - KHÔNG BẮT BUỘC
# ============================================================
# Nếu không muốn dùng Telegram, giữ TELEGRAM_ENABLED = False.
# Nếu muốn dùng Telegram:
# - Tạo bot bằng @BotFather để lấy TELEGRAM_BOT_TOKEN
# - Nhắn tin cho bot
# - Mở https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates để lấy chat_id
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = "8764068500:AAEQf3NHGQ2uD0vEp2Sah8wS7QVhNIFEc1Q"
TELEGRAM_CHAT_ID = "8390791024"


# Bật/tắt log toàn bộ snapshot. Nên để True để có bằng chứng bot chạy.
LOG_MARKET_SNAPSHOTS = True

# Ngưỡng tín hiệu
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
VOLUME_SPIKE_RATIO = 2.0
MIN_SCORE_TO_ALERT = 0


# ============================================================
# 2. UTILS
# ============================================================

def now_vn_str() -> str:
    """Thời gian Việt Nam dạng dễ đọc."""
    vn_time = datetime.now(timezone.utc) + timedelta(hours=7)
    return vn_time.strftime("%Y-%m-%d %H:%M:%S")


def now_iso_ms_vn() -> str:
    """ISO 8601 có milliseconds, múi giờ +07:00."""
    vn_time = datetime.now(timezone.utc) + timedelta(hours=7)
    return vn_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+07:00"


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def beep() -> None:
    """Cảnh báo âm thanh đơn giản trên terminal."""
    print("\a", end="")



def send_telegram_message(message: str) -> None:
    """Gửi tín hiệu lên Telegram nếu đã bật cấu hình. Lỗi Telegram không làm dừng bot."""
    if not TELEGRAM_ENABLED:
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"[WARN] Không gửi được Telegram: {e}")


def build_telegram_signal_message(result: dict) -> str:
    """Tạo nội dung tin nhắn Telegram từ tín hiệu."""
    rsi_text = f"{result['rsi14']:.2f}" if result.get("rsi14") is not None else "NA"
    return (
        "🚨 <b>MEXC Futures Signal</b>\n"
        f"Time VN: {result['timestamp_vn']}\n"
        f"Symbol: <b>{result['symbol']}</b>\n"
        f"Signal: <b>{result['side']}</b>\n"
        f"Score: {result['score']}\n"
        f"Price: {result['last_price']:.8f}\n"
        f"RSI14: {rsi_text}\n"
        f"Volume ratio: {result['volume_ratio']:.2f}x\n"
        f"Bollinger: {result['bb_position']}\n"
        "Reason: " + " | ".join(result["reasons"])
    )


def safe_float(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_div(a: float, b: float, default=0.0) -> float:
    try:
        if b == 0:
            return default
        return a / b
    except Exception:
        return default


def http_get(path: str, params=None, timeout=12) -> dict:
    """GET wrapper cho Public API MEXC Futures."""
    url = BASE_URL + path
    headers = {
        "User-Agent": "Mozilla/5.0 PartB-MEXC-Signal-Bot/1.0"
    }

    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response type from {url}")

    # MEXC thường trả {"success": true, "code": 0, "data": ...}
    if data.get("success") is False:
        raise RuntimeError(f"MEXC error: {data}")

    return data


# ============================================================
# 3. CSV LOGGING
# ============================================================

def ensure_csv_files() -> None:
    if not os.path.exists(SIGNAL_LOG_FILE):
        with open(SIGNAL_LOG_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_vn",
                "symbol",
                "side",
                "score",
                "last_price",
                "price_change_pct_1m",
                "rsi14",
                "macd",
                "macd_signal",
                "volume_ratio",
                "bb_position",
                "alpha_count",
                "reasons"
            ])

    if not os.path.exists(SNAPSHOT_LOG_FILE):
        with open(SNAPSHOT_LOG_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_vn",
                "symbol",
                "last_price",
                "price_change_pct_1m",
                "rsi14",
                "macd",
                "macd_signal",
                "volume_ratio",
                "bb_position",
                "status"
            ])


def write_signal_log(result: dict) -> None:
    with open(SIGNAL_LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            result["timestamp_vn"],
            result["symbol"],
            result["side"],
            result["score"],
            round(result["last_price"], 8),
            round(result["price_change_pct_1m"], 4),
            round(result["rsi14"], 4) if result["rsi14"] is not None else "",
            round(result["macd"], 8) if result["macd"] is not None else "",
            round(result["macd_signal"], 8) if result["macd_signal"] is not None else "",
            round(result["volume_ratio"], 4),
            result["bb_position"],
            result["alpha_count"],
            " | ".join(result["reasons"])
        ])


def write_snapshot_log(result: dict) -> None:
    if not LOG_MARKET_SNAPSHOTS:
        return

    with open(SNAPSHOT_LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            result["timestamp_vn"],
            result["symbol"],
            round(result["last_price"], 8),
            round(result["price_change_pct_1m"], 4),
            round(result["rsi14"], 4) if result["rsi14"] is not None else "",
            round(result["macd"], 8) if result["macd"] is not None else "",
            round(result["macd_signal"], 8) if result["macd_signal"] is not None else "",
            round(result["volume_ratio"], 4),
            result["bb_position"],
            result["status"]
        ])


# ============================================================
# 4. MARKET DATA
# ============================================================

def get_top_usdt_symbols(limit=25) -> list:
    """
    Lấy danh sách USDT-M Futures từ ticker.
    Chọn các cặp có thanh khoản cao để dễ trade demo.
    """
    data = http_get("/api/v1/contract/ticker")
    tickers = data.get("data", [])

    if isinstance(tickers, dict):
        tickers = [tickers]

    rows = []
    for item in tickers:
        symbol = item.get("symbol", "")
        if not symbol.endswith("_USDT"):
            continue

        last_price = safe_float(item.get("lastPrice"))
        volume24 = safe_float(item.get("volume24"))
        amount24 = safe_float(item.get("amount24"))

        if last_price <= 0:
            continue

        liquidity_score = amount24 if amount24 > 0 else volume24 * last_price

        rows.append({
            "symbol": symbol,
            "last_price": last_price,
            "volume24": volume24,
            "amount24": amount24,
            "liquidity_score": liquidity_score
        })

    rows.sort(key=lambda x: x["liquidity_score"], reverse=True)
    symbols = [row["symbol"] for row in rows[:limit]]

    if len(symbols) < 20:
        fallback = [
            "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT",
            "BNB_USDT", "ADA_USDT", "AVAX_USDT", "LINK_USDT", "LTC_USDT",
            "BCH_USDT", "DOT_USDT", "TRX_USDT", "NEAR_USDT", "APT_USDT",
            "SUI_USDT", "OP_USDT", "ARB_USDT", "WIF_USDT", "PEPE_USDT",
            "ORDI_USDT", "FIL_USDT", "ETC_USDT", "UNI_USDT", "AAVE_USDT"
        ]
        symbols = fallback[:limit]

    return symbols


def get_klines(symbol: str, interval="Min1", limit=120) -> list:
    """
    Lấy dữ liệu nến contract.
    Endpoint trả các mảng: time/open/close/high/low/vol.
    """
    seconds_per_candle = {
        "Min1": 60,
        "Min5": 5 * 60,
        "Min15": 15 * 60,
        "Min30": 30 * 60,
        "Min60": 60 * 60,
        "Hour4": 4 * 60 * 60,
        "Hour8": 8 * 60 * 60,
        "Day1": 24 * 60 * 60
    }.get(interval, 60)

    end_ts = int(time.time())
    start_ts = end_ts - limit * seconds_per_candle

    path = f"/api/v1/contract/kline/{symbol}"
    params = {
        "interval": interval,
        "start": start_ts,
        "end": end_ts
    }

    raw = http_get(path, params=params)
    data = raw.get("data", {})

    times = data.get("time", [])
    opens = data.get("open", [])
    closes = data.get("close", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    volumes = data.get("vol", data.get("volume", []))

    n = min(len(times), len(opens), len(closes), len(highs), len(lows), len(volumes))
    candles = []

    for i in range(n):
        candles.append({
            "time": int(times[i]),
            "open": safe_float(opens[i]),
            "high": safe_float(highs[i]),
            "low": safe_float(lows[i]),
            "close": safe_float(closes[i]),
            "volume": safe_float(volumes[i])
        })

    return candles


# ============================================================
# 5. INDICATORS
# ============================================================

def calculate_ema(values: list, period: int) -> list:
    if len(values) < period:
        return []

    k = 2 / (period + 1)
    output = [None] * (period - 1)

    first_ema = mean(values[:period])
    output.append(first_ema)

    previous = first_ema
    for price in values[period:]:
        current = price * k + previous * (1 - k)
        output.append(current)
        previous = current

    return output


def calculate_rsi(closes: list, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = mean(gains)
    avg_loss = mean(losses)

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = abs(min(diff, 0))

        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(closes: list):
    """
    Trả về:
    - macd hiện tại
    - signal hiện tại
    - macd trước
    - signal trước
    """
    if len(closes) < 40:
        return None, None, None, None

    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)

    macd_series = []
    for a, b in zip(ema12, ema26):
        if a is None or b is None:
            macd_series.append(None)
        else:
            macd_series.append(a - b)

    valid_macd = [x for x in macd_series if x is not None]
    if len(valid_macd) < 12:
        return None, None, None, None

    signal_valid = calculate_ema(valid_macd, 9)
    signal_series = [None] * (len(macd_series) - len(signal_valid)) + signal_valid

    macd_now = macd_series[-1]
    signal_now = signal_series[-1]
    macd_prev = macd_series[-2]
    signal_prev = signal_series[-2]

    if macd_now is None or signal_now is None or macd_prev is None or signal_prev is None:
        return None, None, None, None

    return macd_now, signal_now, macd_prev, signal_prev


def calculate_bollinger_position(closes: list, period=20, std_mult=2):
    """
    Trả về:
    - BELOW_LOWER: giá dưới band dưới
    - ABOVE_UPPER: giá trên band trên
    - INSIDE: nằm trong band
    """
    if len(closes) < period:
        return "UNKNOWN", None, None, None

    window = closes[-period:]
    ma = mean(window)
    std = pstdev(window)

    upper = ma + std_mult * std
    lower = ma - std_mult * std
    last = closes[-1]

    if last < lower:
        return "BELOW_LOWER", lower, ma, upper

    if last > upper:
        return "ABOVE_UPPER", lower, ma, upper

    return "INSIDE", lower, ma, upper


def calculate_volume_ratio(candles: list, period=20) -> float:
    if len(candles) < period + 1:
        return 0.0

    current_volume = candles[-1]["volume"]
    avg_volume = mean([c["volume"] for c in candles[-period-1:-1]])

    return safe_div(current_volume, avg_volume, 0.0)


# ============================================================
# 6. SIGNAL ENGINE
# ============================================================

def analyze_symbol(symbol: str, candles: list) -> dict:
    if len(candles) < 40:
        return {
            "timestamp_vn": now_iso_ms_vn(),
            "symbol": symbol,
            "status": "NOT_ENOUGH_DATA",
            "side": "NONE",
            "score": 0,
            "last_price": 0,
            "price_change_pct_1m": 0,
            "rsi14": None,
            "macd": None,
            "macd_signal": None,
            "volume_ratio": 0,
            "bb_position": "UNKNOWN",
            "alpha_count": 0,
            "reasons": ["Không đủ dữ liệu nến"]
        }

    closes = [c["close"] for c in candles]
    last_price = closes[-1]
    prev_price = closes[-2]
    price_change_pct_1m = safe_div(last_price - prev_price, prev_price, 0) * 100

    rsi14 = calculate_rsi(closes, 14)
    macd, macd_signal, macd_prev, macd_signal_prev = calculate_macd(closes)
    bb_position, bb_lower, bb_middle, bb_upper = calculate_bollinger_position(closes)
    volume_ratio = calculate_volume_ratio(candles)

    buy_score = 0
    sell_score = 0
    reasons = []

    # Alpha 1: RSI Mean Reversion
    if rsi14 is not None:
        if rsi14 <= RSI_OVERSOLD:
            buy_score += 1
            reasons.append(f"RSI quá bán {rsi14:.2f} <= {RSI_OVERSOLD}")
        elif rsi14 >= RSI_OVERBOUGHT:
            sell_score += 1
            reasons.append(f"RSI quá mua {rsi14:.2f} >= {RSI_OVERBOUGHT}")

    # Alpha 2: MACD Cross
    if macd is not None and macd_signal is not None and macd_prev is not None and macd_signal_prev is not None:
        if macd_prev <= macd_signal_prev and macd > macd_signal:
            buy_score += 1
            reasons.append("MACD cắt lên Signal")
        elif macd_prev >= macd_signal_prev and macd < macd_signal:
            sell_score += 1
            reasons.append("MACD cắt xuống Signal")

    # Alpha 3: Volume Spike + hướng nến
    if volume_ratio >= VOLUME_SPIKE_RATIO:
        if price_change_pct_1m > 0:
            buy_score += 1
            reasons.append(f"Volume spike {volume_ratio:.2f}x + nến tăng")
        elif price_change_pct_1m < 0:
            sell_score += 1
            reasons.append(f"Volume spike {volume_ratio:.2f}x + nến giảm")
        else:
            reasons.append(f"Volume spike {volume_ratio:.2f}x nhưng giá đi ngang")

    # Alpha 4: Bollinger Bands Mean Reversion
    if bb_position == "BELOW_LOWER":
        buy_score += 1
        reasons.append("Giá dưới Bollinger Lower Band")
    elif bb_position == "ABOVE_UPPER":
        sell_score += 1
        reasons.append("Giá trên Bollinger Upper Band")

    if buy_score >= MIN_SCORE_TO_ALERT and buy_score > sell_score:
        side = "LONG"
        score = buy_score
        status = "SIGNAL"
    elif sell_score >= MIN_SCORE_TO_ALERT and sell_score > buy_score:
        side = "SHORT"
        score = sell_score
        status = "SIGNAL"
    else:
        side = "NONE"
        score = max(buy_score, sell_score)
        status = "NO_SIGNAL"

    if not reasons:
        reasons.append("Không có tín hiệu đủ mạnh")

    return {
        "timestamp_vn": now_iso_ms_vn(),
        "symbol": symbol,
        "status": status,
        "side": side,
        "score": score,
        "last_price": last_price,
        "price_change_pct_1m": price_change_pct_1m,
        "rsi14": rsi14,
        "macd": macd,
        "macd_signal": macd_signal,
        "volume_ratio": volume_ratio,
        "bb_position": bb_position,
        "alpha_count": len([r for r in reasons if "Không có" not in r and "Không đủ" not in r]),
        "reasons": reasons
    }


# ============================================================
# 7. DASHBOARD
# ============================================================

def print_dashboard(symbols: list, results: list, signals: list, cycle_no: int) -> None:
    clear_screen()

    print("=" * 100)
    print("PART B - MEXC FUTURES SIGNAL BOT | Robo-Advisor, không tự đặt lệnh")
    print(f"Thời gian VN: {now_vn_str()} | Cycle: {cycle_no} | Số cặp quét: {len(symbols)}")
    print("=" * 100)
    print("Bot đang quét dữ liệu Public Futures MEXC và cảnh báo tín hiệu để bạn tự trade thủ công.")
    print("Alpha dùng: RSI + MACD Cross + Volume Spike + Bollinger Bands")
    print(f"Telegram alert: {'ON' if TELEGRAM_ENABLED else 'OFF'}")
    print("-" * 100)

    if signals:
        print("TÍN HIỆU MỚI:")
        for s in signals:
            print(
                f"[{s['side']}] {s['symbol']} | score={s['score']} | "
                f"price={s['last_price']:.8f} | RSI={s['rsi14'] if s['rsi14'] is not None else 'NA'}"
            )
            print("   Lý do:", " | ".join(s["reasons"]))
    else:
        print("Chưa có tín hiệu đủ mạnh trong vòng quét này.")

    print("-" * 100)
    print("BẢNG THEO DÕI NHANH:")
    print(f"{'SYMBOL':<14} {'PRICE':>14} {'1M%':>8} {'RSI':>8} {'VOLx':>8} {'BB':>14} {'STATUS':>12}")

    for r in results[:25]:
        rsi_text = f"{r['rsi14']:.2f}" if r["rsi14"] is not None else "NA"
        print(
            f"{r['symbol']:<14} "
            f"{r['last_price']:>14.8f} "
            f"{r['price_change_pct_1m']:>8.3f} "
            f"{rsi_text:>8} "
            f"{r['volume_ratio']:>8.2f} "
            f"{r['bb_position']:>14} "
            f"{r['status']:>12}"
        )

    print("-" * 100)
    print(f"Log tín hiệu: {SIGNAL_LOG_FILE}")
    print(f"Log snapshot: {SNAPSHOT_LOG_FILE}")
    print("Nhấn Ctrl + C để dừng bot.")
    print("=" * 100)


# Hàm format riêng để tránh lỗi f-string conditional trong một số terminal/Python cũ
def format_signal_line(s: dict) -> str:
    rsi_text = f"{s['rsi14']:.2f}" if s["rsi14"] is not None else "NA"
    return (
        f"[{s['side']}] {s['symbol']} | score={s['score']} | "
        f"price={s['last_price']:.8f} | RSI={rsi_text} | "
        f"VOL={s['volume_ratio']:.2f}x"
    )


# ============================================================
# 8. MAIN LOOP
# ============================================================

def main() -> None:
    ensure_csv_files()

    print("Đang khởi động Part B MEXC Signal Bot...")
    print("Không cần API key. Bot chỉ dùng Public API và không tự đặt lệnh.")
    time.sleep(1)

    if MANUAL_SYMBOLS:
        symbols = MANUAL_SYMBOLS[:]
    else:
        try:
            symbols = get_top_usdt_symbols(SYMBOL_LIMIT)
        except Exception as e:
            print("\n[WARN] Không lấy được danh sách top symbol từ MEXC.")
            print("[WARN] Nguyên nhân thường gặp: mạng/VPN/firewall/nhà mạng chặn hoặc MEXC reset kết nối.")
            print(f"[WARN] Chi tiết lỗi: {e}")
            print("[INFO] Bot sẽ dùng danh sách DEFAULT_SYMBOLS để vẫn quét đủ >= 20 cặp.\n")
            symbols = DEFAULT_SYMBOLS[:SYMBOL_LIMIT]

    if len(symbols) < 20:
        print("CẢNH BÁO: Số cặp lấy được < 20. Hãy kiểm tra mạng hoặc điền MANUAL_SYMBOLS.")
    else:
        print(f"Đã chọn {len(symbols)} cặp:", ", ".join(symbols))

    last_signal_time = {}
    cycle_no = 0

    while True:
        cycle_no += 1
        cycle_start = time.time()

        results = []
        signals_this_cycle = []

        for idx, symbol in enumerate(symbols, start=1):
            try:
                candles = get_klines(symbol, KLINE_INTERVAL, KLINE_LIMIT)
                result = analyze_symbol(symbol, candles)
                results.append(result)
                write_snapshot_log(result)

                if result["status"] == "SIGNAL":
                    last_time = last_signal_time.get(symbol, 0)
                    enough_cooldown = (time.time() - last_time) >= SIGNAL_COOLDOWN_SECONDS

                    if enough_cooldown:
                        write_signal_log(result)
                        signals_this_cycle.append(result)
                        last_signal_time[symbol] = time.time()
                        beep()
                        send_telegram_message(build_telegram_signal_message(result))

                # Tránh gọi API quá nhanh.
                time.sleep(0.15)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                error_result = {
                    "timestamp_vn": now_iso_ms_vn(),
                    "symbol": symbol,
                    "status": "ERROR",
                    "side": "NONE",
                    "score": 0,
                    "last_price": 0,
                    "price_change_pct_1m": 0,
                    "rsi14": None,
                    "macd": None,
                    "macd_signal": None,
                    "volume_ratio": 0,
                    "bb_position": "UNKNOWN",
                    "alpha_count": 0,
                    "reasons": [str(e)]
                }
                results.append(error_result)
                write_snapshot_log(error_result)

        # Sắp xếp: signal lên đầu, sau đó volume spike cao.
        results.sort(key=lambda x: (x["status"] == "SIGNAL", x["score"], x["volume_ratio"]), reverse=True)

        clear_screen()
        print("=" * 100)
        print("PART B - MEXC FUTURES SIGNAL BOT | Robo-Advisor, không tự đặt lệnh")
        print(f"Thời gian VN: {now_vn_str()} | Cycle: {cycle_no} | Số cặp quét: {len(symbols)}")
        print("=" * 100)
        print("Alpha dùng: RSI + MACD Cross + Volume Spike + Bollinger Bands")
        print(f"Telegram alert: {'ON' if TELEGRAM_ENABLED else 'OFF'}")
        print("Mục đích: cảnh báo tín hiệu để bạn tự trade thủ công trên MEXC Futures Demo.")
        print("-" * 100)

        if signals_this_cycle:
            print("TÍN HIỆU MỚI:")
            for s in signals_this_cycle:
                print(format_signal_line(s))
                print("   Lý do:", " | ".join(s["reasons"]))
        else:
            print("Chưa có tín hiệu đủ mạnh trong vòng quét này.")

        print("-" * 100)
        print(f"{'SYMBOL':<14} {'PRICE':>14} {'1M%':>8} {'RSI':>8} {'VOLx':>8} {'BB':>14} {'STATUS':>12}")

        for r in results[:25]:
            rsi_text = f"{r['rsi14']:.2f}" if r["rsi14"] is not None else "NA"
            price_text = f"{r['last_price']:.8f}" if r["last_price"] else "NA"
            print(
                f"{r['symbol']:<14} "
                f"{price_text:>14} "
                f"{r['price_change_pct_1m']:>8.3f} "
                f"{rsi_text:>8} "
                f"{r['volume_ratio']:>8.2f} "
                f"{r['bb_position']:>14} "
                f"{r['status']:>12}"
            )

        print("-" * 100)
        print(f"Log tín hiệu: {SIGNAL_LOG_FILE}")
        print(f"Log snapshot: {SNAPSHOT_LOG_FILE}")
        print("Nhấn Ctrl + C để dừng bot.")
        print("=" * 100)

        elapsed = time.time() - cycle_start
        sleep_time = max(5, SCAN_INTERVAL_SECONDS - elapsed)

        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nĐã dừng bot. Kiểm tra file log CSV trong cùng thư mục.")

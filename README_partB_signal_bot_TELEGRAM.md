# Part B MEXC Signal Bot - bản có Telegram tùy chọn

## Chạy bot
```bash
py partB_mexc_signal_bot_FIXED_TELEGRAM.py
```

## Telegram có bắt buộc không?
Không bắt buộc. Nếu `TELEGRAM_ENABLED = False`, bot vẫn chạy trên CMD và ghi log CSV bình thường.

## Cách bật Telegram

Đổi thành:

```python
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = "8764068500:AAEQf3NHGQ2uD0vEp2Sah8wS7QVhNIFEc1Q"
TELEGRAM_CHAT_ID = "8390791024"
TELEGRAM_ENABLED = True
```

Sau đó chạy lại bot.

## File log sinh ra
- `partB_signal_log.csv`
- `partB_market_snapshot_log.csv`

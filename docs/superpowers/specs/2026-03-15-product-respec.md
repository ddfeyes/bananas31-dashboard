# svc-dash — Переосмысление продукта

## Цель
Pattern research dashboard. Не просто показ данных — инструмент для понимания ПОЧЕМУ актив движется.

## Ключевые вопросы которые должен отвечать дашборд:
1. В какой фазе сейчас актив? (accumulation / distribution / markup / markdown / ranging)
2. Что предшествует движению? (OI build-up, funding extremes, orderbook imbalance, large trades)
3. Кто управляет ценой сейчас? (longs/shorts, whales, market makers)
4. Когда разворот? (divergences между ценой и CVD/OI, liquidation clusters)

## Обязательные данные (живые + исторические)
- Цена + OHLCV (Binance WS)
- Orderbook depth top 20 levels (Binance WS, обновление <500ms)
- Trades tape (Binance WS, каждая сделка)
- Open Interest (Binance futures REST, каждые 3с)
- Funding rate (Binance каждые 8ч + текущий)
- Liquidations (Binance WS forceOrder)

## Хранилище
- SQLite для истории (минимум 30 дней)
- 1-min OHLCV свечи агрегировать из trades
- OB snapshots каждые 10с
- Каждая сделка записывается

## Ключевые индикаторы (сделать заново, правильно)
- CVD (Cumulative Volume Delta) — правильный расчёт через taker side
- OI delta per candle — изменение OI за минуту
- Funding rate extremes + history
- Liquidation heatmap — где кластеры ликвидаций
- Orderbook imbalance — разница bid/ask volume в top 10 уровнях
- Large trades detector (>$10k) с направлением
- Phase detector — ML-like classifier на основе всего вышеперечисленного

## НЕ нужно
- Декоративные карточки
- Дублирующие индикаторы
- UI украшения

## Стек (не менять)
- FastAPI + asyncio + SQLite + aiosqlite
- TradingView Lightweight Charts для свечей
- Chart.js для остальных графиков
- Docker (без rebuild в runtime)

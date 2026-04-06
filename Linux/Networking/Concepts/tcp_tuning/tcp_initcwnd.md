# Настройка initcwnd

> **SSoT:** Полная документация по правилу 14 КБ, влиянию на загрузку веб-страниц, взаимодействию с TLS/HTTP — в [Networking/Protocols/TCP/congestion/tcp_initcwnd_and_optimization.md](../../../Networking/Protocols/TCP/congestion/tcp_initcwnd_and_optimization.md)

## Определения

**initcwnd (initial congestion window)** — начальное окно перегрузки, определяющее объём данных, отправляемых в первой «волне» после установки TCP-соединения. Измеряется в MSS (Maximum Segment Size).

**initrwnd (initial receive window)** — начальное окно приёма, ограничивающее объём данных, которые получатель готов принять в первой волне.

## Basic Concepts

### Значение по умолчанию

Согласно RFC 5681: `initcwnd = 10 MSS`. Для Ethernet (MTU 1500):

```
MSS = 1500 - 20 (IP) - 20 (TCP) = 1460 байт
initcwnd = 10 × 1460 = 14 600 байт (~14.3 КБ)
```

Это означает, что первые ~14 КБ данных отправляются одним блоком, после чего начинается фаза Slow Start.

### Связь с Slow Start

`initcwnd` задаёт отправную точку для алгоритма Slow Start. После исчерпания начального окна TCP ждёт ACK и удваивает cwnd каждый RTT (экспоненциальный рост до `ssthresh`).

### Почему увеличение безопасно

Современные веб-ресурсы (HTML + CSS + JS) часто превышают 14 КБ. Увеличение `initcwnd` до 20–40 MSS сокращает количество RTT до полной загрузки первых ресурсов без риска перегрузки — Slow Start продолжит работу с большего базового значения.

## Practical Scenarios

### Проверка текущего значения

```bash
# Показать initcwnd для маршрутов
ip route show | grep initcwnd

# Если параметр не указан — используется значение по умолчанию (10 MSS)
ip route show dev eth0
```

### Настройка initcwnd

**Временно (сбрасывается после перезагрузки):**

```bash
# Найти шлюз и интерфейс
GATEWAY=$(ip route | grep default | awk '{print $3}')
DEVICE=$(ip route | grep default | awk '{print $5}')

# Установить initcwnd=30 для маршрута по умолчанию
sudo ip route change default via "$GATEWAY" dev "$DEVICE" initcwnd 30
```

**Постоянно:**

`ip route` не поддерживает сохранение параметров в конфигурационных файлах. Для постоянной настройки используйте один из методов:

**NetworkManager** (`/etc/NetworkManager/dispatcher.d/99-initcwnd`):

```bash
#!/bin/bash
if [ "$2" = "up" ]; then
    ip route change default via "$(ip route | grep default | awk '{print $3}')" \
        dev "$1" initcwnd 30
fi
```

**systemd-networkd** (через `[Route]` секцию в `.network` файле):

```ini
[Route]
Gateway=192.168.1.1
InitialCongestionWindow=30
```

**Простой скрипт в rc.local или cron @reboot:**

```bash
#!/bin/bash
sleep 5  # дождаться поднятия интерфейса
ip route change default via "$(ip route | grep default | awk '{print $3}')" \
    dev "$(ip route | grep default | awk '{print $5}')" initcwnd 30
```

### initcwnd + BBR

При использовании BBR `initcwnd` менее критичен — BBR самостоятельно оценивает пропускную способность и может отправлять данные агрессивнее, чем стандартный Slow Start. Однако увеличение `initcwnd` всё ещё полезно для первых RTT, до того как BBR соберёт достаточно метрик.

### Рекомендации по размерам

| Сценарий | initcwnd | initrwnd | Обоснование |
| :--- | :--- | :--- | :--- |
| **Веб-сервер (общий)** | 20–30 MSS | 20–30 MSS | Большинство ресурсов ≤ 30–40 КБ |
| **API-сервер (JSON)** | 10 MSS (default) | 10 MSS | Ответы API обычно < 14 КБ |
| **CDN/статика** | 30–40 MSS | 30 MSS | Крупные ресурсы, критична латентность |
| **Прокси/балансировщик** | 20 MSS | 20 MSS | Умеренное увеличение без риска |

> **Внимание:** `initcwnd > 10` может конфликтовать с политикой некоторых провайдеров (RFC-совместимое значение — 10 MSS). Перед изменением протестируйте влияние на вашу сеть.

### Диагностика

```bash
# Проверить cwnd на активных соединениях
ss -ti | grep -o 'cwnd:[0-9]*'

# Сравнить cwnd до и после изменения initcwnd
ss -tin state established
```

## Additional Information

### Связанные темы

- **SSoT:** [Правило 14 КБ и оптимизация initcwnd](../../../Networking/Protocols/TCP/congestion/tcp_initcwnd_and_optimization.md) — расчёт, влияние на TLS/HTTP, CDN-провайдеры
- **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
- **Алгоритмы перегрузки:** [Алгоритмы управления перегрузкой](./tcp_congestion_algorithms.md) — взаимодействие initcwnd с Slow Start
- **ip route:** [Настройка маршрутов](../../Tools/iproute2/ip_route.md) — команда `ip route change` с параметрами маршрута

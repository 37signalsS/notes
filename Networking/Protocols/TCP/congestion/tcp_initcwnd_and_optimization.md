# Правило 14 КБ и оптимизация initcwnd

## Определения

**initcwnd (Initial Congestion Window)** — начальное значение окна перегрузки TCP при установлении соединения. Определяет объём данных, который можно отправить до получения первого ACK, не проходя фазу Slow Start.

**Правило 14 КБ** — эмпирическое название стандарта `initcwnd = 10 MSS` (RFC 5681). Для Ethernet с MTU 1500 байт это ~14.6 КБ данных в первом окне.

**Ключевая проблема:** ресурсы, превышающие initcwnd даже на 1 КБ, требуют дополнительного RTT, что удваивает время загрузки после handshake.

---

## Основные концепции

### Расчет initcwnd

**Стандарт (RFC 5681):** `initcwnd = 10 MSS`

**Для Ethernet:**

```
MTU = 1500 байт
IP Header = 20 байт
TCP Header = 20 байт
MSS = 1500 - 20 - 20 = 1460 байт

initcwnd = 10 × 1460 = 14 600 байт (~14.3 КБ)
```

### Влияние initcwnd на загрузку веб-страниц

**Ресурс ≤ 14 КБ — умещается в initcwnd:**

```
RTT 0: TCP Handshake (SYN, SYN-ACK, ACK)
RTT 1: Отправка всего ресурса (≤ initcwnd), получение ACK

Итого: 2 RTT до полной загрузки
```

**Ресурс > 14 КБ (например, 15 КБ) — не умещается:**

```
RTT 0: TCP Handshake
RTT 1: Отправка 14 КБ, ожидание ACK
RTT 2: Отправка оставшегося 1 КБ, получение ACK

Итого: 3 RTT (на 50% дольше)
```

Даже 1 лишний килобайт добавляет полный RTT к загрузке.

### Оптимизация initcwnd на сервере

**Проверка текущего значения:**

```bash
ip route show | grep initcwnd
```

**Увеличение (пример: initcwnd = 30):**

```bash
GATEWAY=$(ip route | grep default | awk '{print $3}')
DEVICE=$(ip route | grep default | awk '{print $5}')
ip route change default via $GATEWAY dev $DEVICE initcwnd 30
```

Для сохранения настройки добавить в `/etc/network/interfaces` или сетевой скрипт.

**Значения CDN-провайдеров:**

| Провайдер | initcwnd |
| :--- | :--- |
| **Cloudflare** | ≈ 30–40 MSS (~43–58 КБ) |
| **Fastly** | ≈ 30 MSS |
| **Google** | BBR с адаптивным initcwnd |

### Взаимодействие с TLS

initcwnd ограничивает объём данных, отправляемых после handshake. TLS добавляет дополнительные RTT до начала передачи полезных данных.

**TLS 1.2 — 3 RTT до данных:**

```
RTT 0: TCP Handshake
RTT 1: TLS ClientHello → ServerHello, Certificate
RTT 2: TLS ClientKeyExchange, Finished
RTT 3: Отправка данных (ограничена initcwnd)
```

**TLS 1.3 — 2 RTT до данных:**

```
RTT 0: TCP Handshake
RTT 1: TLS ClientHello (с ключами) → ServerHello, Certificate, Finished
       Отправка данных (ограничена initcwnd)
```

**TLS 1.3 0-RTT (повторное подключение) — 1 RTT:**

```
RTT 0: Клиент отправляет данные сразу с ClientHello
       Сервер отвечает
```

0-RTT несёт риск replay-атак — не использовать для критичных операций. Подробнее: [TLS Handshake](../../tls.md#процесс-рукопожатия-tls-handshake).

### HTTP/2 и HTTP/3 в контексте initcwnd

**HTTP/2 (поверх TCP):**

- Мультиплексирование запросов в одном TCP-соединении
- Устраняет head-of-line blocking на уровне приложения
- **Но:** первое соединение всё ещё ограничено TCP Slow Start и initcwnd

**HTTP/3 (QUIC поверх UDP):**

- Собственный congestion control (аналогичен TCP cwnd)
- Устраняет head-of-line blocking на транспортном уровне
- 0-RTT handshake (как TLS 1.3)
- Быстрее при потерях пакетов, не зависит от TCP initcwnd

---

## Практические сценарии

### Сценарий 1: Оптимизация веб-сервера под критический ресурс

**Проблема:** CSS/JS-файл размером 18 КБ загружается за 3 RTT вместо 2.

**Решение:**

- Увеличить `initcwnd` до 30 MSS (~43 КБ) — ресурс уместится в одно окно
- Или: сжать ресурс (gzip/brotli) до ≤14 КБ
- Или: разбить на критический (inline, ≤14 КБ) и остальной (lazy load)

### Сценарий 2: Анализ производительности CDN

**Проблема:** TTFB от CDN выше ожидаемого.

**Диагностика:**

- Проверить initcwnd CDN-провайдера (Cloudflare: 30–40 MSS, Fastly: 30 MSS)
- Убедиться, что сервер origin не ограничивает `initcwnd` (должен быть ≥10 MSS)
- Проверить RTT до ближайшего edge-сервера

### Сценарий 3: Выбор между увеличением initcwnd и переходом на BBR

**Увеличение initcwnd:**

- Простая настройка, быстрый эффект
- Риск: краткосрочная перегрузка сети (burst 30 пакетов вместо 10)
- Подходит: стабильные каналы, малые RTT

**Переход на BBR:**

- Адаптивный initcwnd, pacing, лучшая утилизация канала
- Требует: ядро 4.9+, `net.core.default_qdisc = fq`
- Подходит: нестабильные каналы, высокие RTT, мобильные сети

### Сценарий 4: Packet Pacing при увеличенном initcwnd

**Проблема:** `initcwnd = 30` вызывает burst из 30 пакетов, кратковременную перегрузку и потери.

**Решение:** включить pacing — равномерную отправку пакетов во времени:

```bash
# BBR включает pacing автоматически (ядро 4.x+)
sysctl -w net.ipv4.tcp_congestion_control=bbr
echo "net.core.default_qdisc = fq" >> /etc/sysctl.conf

# Для других алгоритмов — tc с fq
tc qdisc add dev eth0 root fq
```

---

## Дополнительная информация

### Связанные темы

**Обзор и базовые алгоритмы** ([tcp_congestion_control_overview.md](./tcp_congestion_control_overview.md)) — Slow Start, AIMD. **Алгоритмы congestion control** ([tcp_congestion_algorithms.md](./tcp_congestion_algorithms.md)) — CUBIC, BBR, Reno. **Диагностика congestion control** ([tcp_congestion_diagnostics.md](./tcp_congestion_diagnostics.md)) — практические сценарии. **Оптимизация TCP** ([tcp_tuning_overview.md](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)) — практическая настройка. **TLS Handshake** ([tls.md](../../tls.md)) — процесс рукопожатия.

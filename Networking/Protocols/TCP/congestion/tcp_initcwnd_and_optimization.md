# Правило 14 КБ и оптимизация initcwnd

## 1. Расчет initcwnd

**Стандарт (RFC 5681):** `initcwnd = 10 MSS`

**Для Ethernet:**

```
MTU = 1500 байт
IP Header = 20 байт (см. [Структура IP-пакета](../../../OSI_TCP_IP_Model/Network_layer/Protocols/ip_packet_structure.md))
TCP Header = 20 байт
MSS = 1500 - 20 - 20 = 1460 байт

initcwnd = 10 × 1460 = 14 600 байт (~14.3 КБ)
```

---

## 2. Влияние на загрузку веб-страниц

### Сценарий 1: Ресурс ≤ 14 КБ

```
RTT 0: TCP Handshake (SYN, SYN-ACK, ACK)
RTT 1: Отправка всего ресурса (14 КБ ≤ initcwnd)
       Получение ACK

Итого: 2 RTT до полной загрузки
```

### Сценарий 2: Ресурс > 14 КБ (например, 15 КБ)

```
RTT 0: TCP Handshake
RTT 1: Отправка 14 КБ, ожидание ACK
RTT 2: Отправка оставшегося 1 КБ, получение ACK

Итого: 3 RTT (на 50% дольше!)
```

**Вывод:** даже 1 лишний килобайт удваивает время загрузки после handshake.

---

## 3. Оптимизация initcwnd

### Увеличение на сервере

```bash
# Проверка текущего значения
ip route show | grep initcwnd

# Установка initcwnd = 30 для маршрута по умолчанию
GATEWAY=$(ip route | grep default | awk '{print $3}')
DEVICE=$(ip route | grep default | awk '{print $5}')
ip route change default via $GATEWAY dev $DEVICE initcwnd 30
```

**Постоянная настройка:** добавить в `/etc/network/interfaces` или скрипт сети.

### Настройка CDN-провайдеров

| Провайдер | initcwnd |
| :--- | :--- |
| **Cloudflare** | ≈ 30-40 MSS (~43-58 КБ) |
| **Fastly** | ≈ 30 MSS |
| **Google** | использует BBR с адаптивным initcwnd |

---

## 4. Взаимодействие с TLS

### TLS 1.2

```
RTT 0: TCP Handshake
RTT 1: TLS ClientHello → ServerHello, Certificate
RTT 2: TLS ClientKeyExchange, Finished
RTT 3: Отправка данных (ограничена initcwnd)

Итого: 3 RTT до данных
```

### TLS 1.3

```
RTT 0: TCP Handshake
RTT 1: TLS ClientHello (с ключами) → ServerHello, Certificate, Finished
       Отправка данных (ограничена initcwnd)

Итого: 2 RTT до данных
```

### TLS 1.3 0-RTT (повторное подключение)

```
RTT 0: Клиент отправляет данные сразу с ClientHello
       Сервер отвечает

Итого: 1 RTT (но есть риск replay-атак)
```

См. также: [TLS Handshake](../../tls.md#процесс-рукопожатия-tls-handshake)

---

## 5. HTTP/2 и HTTP/3

### HTTP/2 (поверх TCP)

- Мультиплексирование запросов в одном соединении
- Устраняет head-of-line blocking на уровне приложения
- **Но:** первое соединение всё ещё ограничено TCP Slow Start

### HTTP/3 (QUIC поверх UDP)

- Собственный congestion control (аналогичен TCP cwnd)
- Устраняет head-of-line blocking на транспортном уровне
- 0-RTT handshake (как TLS 1.3)
- Быстрее при потерях пакетов

---

## 6. Связанные документы

- **[Обзор и базовые алгоритмы](./tcp_congestion_control_overview.md)** — Slow Start, AIMD
- **[Алгоритмы congestion control](./tcp_congestion_algorithms.md)** — CUBIC, BBR
- **[Диагностика](./tcp_congestion_diagnostics.md)** — практические сценарии
- **[TLS Handshake](../../tls.md)** — процесс рукопожатия

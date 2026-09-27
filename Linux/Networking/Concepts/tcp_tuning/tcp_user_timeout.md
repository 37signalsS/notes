# TCP_USER_TIMEOUT — Production настройка

## Определения

**TCP_USER_TIMEOUT** — sysctl-параметр ядра Linux (`net.ipv4.tcp_user_timeout`), определяющий максимальное время (в миллисекундах) ожидания подтверждения (ACK) данных до закрытия соединения. По умолчанию `0` (= RTO × tcp_retries2, обычно ~13-30 мин).

**Отличие от tcp_retries2:** `tcp_user_timeout` контролирует время только для ESTABLISHED соединений с данными, ожидающими ACK. `tcp_retries2` контролирует общее количество RTO-ретрансмиссий.

**Отличие от tcp_keepalive:** Keepalive работает на «пустых» соединениях (нет данных). `TCP_USER_TIMEOUT` работает когда есть отправленные данные без подтверждения.

---

## Теоретический блок

### Когда применяется TCP_USER_TIMEOUT

```
Отправитель                     Получатель
    │                               │
    │  Данные (seq=1000, len=500)   │
    │ ─────────────────────────────►│
    │                               │
    │  ... потеря в сети ...        │
    │                               │
    │  Данные (seq=1000, len=500)   │  Ретрансмиссия
    │ ─────────────────────────────►│
    │                               │
    │  ... потеря again ...         │
    │                               │
    │  ... RTO × retries ...        │
    │                               │
    │  TCP_USER_TIMEOUT = 300000    │  (300 сек = 5 мин)
    │  → Закрытие соединения       │
    │  → ETIMEDOUT                  │
```

### Сравнение механизмов таймаутов

| Механизм | Контролирует | По умолчанию | Сценарий |
|---|---|---|---|
| `tcp_user_timeout` | Время ожидания ACK данных | ~13-30 мин (RTO×retries) | Мёртвые соединения с данными |
| `tcp_retries2` | Количество RTO-попыток | 15 (~30 мин) | Мёртвые соединения (общее) |
| `tcp_keepalive_time` | Простой перед first probe | 7200 сек (2 ч) | Мёртвые соединения без данных |
| `tcp_fin_timeout` | FIN-WAIT-2 таймаут | 60 сек | Зависшие закрытия |

### sysctl-параметр

| Параметр | Значение | Описание |
|---|---|---|
| `net.ipv4.tcp_user_timeout` | `0` | По умолчанию (отключено, использует retries2) |
| | `300000` | 5 минут (рекомендуется для production) |
| | `60000` | 1 минута (агрессивное) |
| | `120000` | 2 минуты (умеренное) |

### Когда использовать

| Сценарий | Рекомендация | Обоснование |
|---|---|---|
| **Высоколатентные каналы** | `tcp_user_timeout=0` (default) | Дать время для ретрансмиссий |
| **Datacenter (low latency)** | `tcp_user_timeout=60000` | Быстрое закрытие мёртвых соединений |
| **Mobile/wireless** | `tcp_user_timeout=300000` | Компенсация packet loss |
| **VPN** | `tcp_user_timeout=120000` | Баланс между надёжностью и скоростью |
| **Database connections** | `tcp_user_timeout=60000` | Быстрое переключение на реплику |
| **Load balancer** | `tcp_user_timeout=60000` | Быстрое обнаружение мёртвых бэкендов |

---

## Практический блок

### Проверка текущего значения

```bash
sysctl net.ipv4.tcp_user_timeout
# → net.ipv4.tcp_user_timeout = 0

# Значение 0 = используется формула RTO × tcp_retries2
# Типичное время: ~13-30 мин
```

### Настройка

```bash
# /etc/sysctl.d/99-tcp-user-timeout.conf
net.ipv4.tcp_user_timeout = 300000

# Применение
sudo sysctl --system
```

### Per-route настройка

```bash
# Установить для конкретного маршрута
ip route change 10.0.0.0/24 via 10.0.0.1 tcp_user_timeout 300000

# Проверка
ip route show | grep tcp_user_timeout
```

### Diagnostics

```bash
# Проверить соединения с длинным RTT (кандидаты на tcp_user_timeout)
ss -tin state established | awk '/rtt/ {
    match($0, /rtt:([0-9.]+)/, a);
    if (a[1]+0 > 100) print $0
}'

# Мониторинг через nstat
watch -n1 'nstat -az | grep TCPTimeouts'

# Через ss: проверить таймеры
ss -tin dst 10.0.0.1 | grep -E 'rto|ato|retrans'
# → rto:204 rtt:1.23/0.45 ato:40 retrans:0/3
# rto:204 = текущий RTO = 204 мс
# Если rto растёт → данные не подтверждаются
```

### Prometheus alerting

```yaml
groups:
  - name: tcp_user_timeout_alerts
    rules:
      - alert: HighTCPTimeouts
        expr: rate(node_netstat_TcpExt_TCPTimeouts[5m]) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High TCP timeouts: {{ $value }}/s — проверьте tcp_user_timeout"
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Production Tuning](../../../Networking/Protocols/TCP/production_tuning.md) — keepalive и timeout настройка
- [TCP Retransmission](tcp_retransmission_rack.md) — RTO и ретрансмиссии
- [TCP Connection States](tcp_states_practical.md) — состояния соединений
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — полная диагностика

### Важные замечания

1. **`tcp_user_timeout=0` = disabled** — используется `tcp_retries2` (по умолчанию ~13-30 мин).
2. **Значение должно быть > RTO** — иначе соединение закроется до завершения первой ретрансмиссии.
3. **Для mobile/wireless** используйте агрессивные значения (300 сек) из-за нестабильности канала.
4. **Для datacenter** используйте 60 сек для быстрого обнаружения мёртвых соединений.
5. **tcp_user_timeout не влияет на keepalive** — это разные механизмы для разных сценариев.

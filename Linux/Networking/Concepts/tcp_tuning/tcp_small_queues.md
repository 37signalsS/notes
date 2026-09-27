# TCP Small Queues (TSQ) — Ограничение исходящих данных

## Определения

**TCP Small Queues (TSQ)** — механизм ядра Linux, ограничивающий количество байт данных в исходящих TCP-очередях (qdisc и driver) на одно соединение. Предотвращает starvation low-priority traffic и снижает latency при большом количестве соединений.

**tcp_limit_output_bytes** — sysctl-параметр, определяющий максимальное количество байт в исходящих TCP-очерёдях на одно соединение. По умолчанию `131072` (128 КБ).

**TSQ (TCP Small Queues)** — неформальное название механизма, также известного как `tcp_limit_output_bytes`. Ограничивает данные в стеке между TCP и qdisc.

---

## Теоретический блок

### Проблема, которую решает TSQ

Без TSQ одно соединение может занять все буферы qdisc и NIC, блокируя другие соединения:

```
Без TSQ:
┌─────────────────────────────────────────────────┐
│ Connection A: [==============================]  │  ← 100% qdisc
│ Connection B: [                                ] │  ← 0% qdisc
│ Connection C: [                                ] │  ← 0% qdisc
└─────────────────────────────────────────────────┘
→ Connection A доминирует, B и C голодают

С TSQ (tcp_limit_output_bytes=128KB):
┌─────────────────────────────────────────────────┐
│ Connection A: [=========]                      │  ← 128KB limit
│ Connection B: [=========]                      │  ← 128KB limit
│ Connection C: [=========]                      │  ← 128KB limit
└─────────────────────────────────────────────────┘
→ Справедливое распределение
```

### Где работает TSQ

```
[App write()] → [TCP Stack] → [TSQ Limit] → [qdisc] → [NIC Driver]
                   ↑                ↑
              tcp_sendmsg     tcp_limit_output_bytes
              allocates sk_buff  limits bytes in queue
```

TSQ ограничивает количество данных между TCP-стеком и qdisc. Данные выше лимита буферизируются в socket send buffer.

### sysctl-параметр

| Параметр | Значение | Описание |
|---|---|---|
| `net.ipv4.tcp_limit_output_bytes` | `131072` (128 КБ) | По умолчанию |
| | `65536` (64 КБ) | Более агрессивное ограничение |
| | `262144` (256 КБ) | Менее агрессивное |
| | `0` | Отключено (не рекомендуется) |

### Когда настраивать

| Сценарий | Рекомендация | Обоснование |
|---|---|---|
| **Смешанный трафик (web + background)** | `65536` | Предотвращает starvation |
| **Только interactive** | `131072` (default) | Достаточно |
| **Bulk transfer (CDN)** | `262144` | Увеличить throughput |
| **Только latency-sensitive** | `131072` (default) | Баланс |
| **Много соединений (10K+)** | `65536` | Предотвращает congestion |

---

## Практический блок

### Проверка текущего значения

```bash
sysctl net.ipv4.tcp_limit_output_bytes
# → net.ipv4.tcp_limit_output_bytes = 131072
```

### Настройка

```bash
# /etc/sysctl.d/99-tcp-small-queues.conf
net.ipv4.tcp_limit_output_bytes = 131072

# Применение
sudo sysctl --system
```

### Diagnostics

```bash
# Проверка qdisc queue length
tc -s qdisc show dev eth0
# → qdisc fq 0: root refcnt 2 limit 10000p ...
#    Sent 1234567890 bytes 1234567 pkt
#    dropped 0 overlimits 0 requeues 5
#    backlog 0b 0p requeues 5

# Мониторинг через ss
ss -tin state established | grep -E 'snd_wnd|wmem_queued'
# → snd_wnd:65536 wmem_queued:131072
# Если wmem_queued приближается к buffers — TSQ может ограничивать

# Мониторинг TCP queues через /proc
cat /proc/net/sockstat
# → TCP: mem 100 (rows), orphan 0, tw 0, alloc 5200, mem 100
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Buffer Tuning](tcp_buffer_tuning.md) — буферы сокетов
- [TCP Queueing Disciplines](tcp_queueing_disciplines.md) — qdisc
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — диагностика

### Важные замечания

1. **TSQ应当 включён всегда** — отключение (`0`) приводит к starvation.
2. **tcp_limit_output_bytes=131072** — хорошее значение по умолчанию для большинства сценариев.
3. **TSQ не влияет на throughput** одного соединения — только на fairness между соединениями.
4. **Влияет на latency** — ограничивает буферизацию в стеке, снижая tail latency.
5. **Для containerized workloads** параметр настраивается на уровне node (sysctl).

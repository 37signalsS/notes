# Практика анализа заголовка TCP

## Определения

**Анализ заголовка TCP** — диагностика и проверка параметров TCP-соединений через tcpdump и ss.

---

## Основные понятия

### Флаги TCP в выводе tcpdump

| Обозначение | Флаг | Назначение |
| :--- | :--- | :--- |
| `[S]` | SYN | Установка соединения (handshake) |
| `[S.]` | SYN+ACK | Подтверждение handshake |
| `[.]` | ACK | Подтверждение данных |
| `[P]` | PSH | Немедленная доставка приложению |
| `[F]` | FIN | Завершение соединения |
| `[R]` | RST | Сброс соединения (ошибка/отказ) |

### Опции TCP в выводе ss

Опции отображаются в сокращенном формате:

- `cubic` — алгоритм congestion control
- `ts` — timestamps включены
- `sack` — SACK разрешен
- `wscale:X,Y` — window scale отправителя (X) и получателя (Y)
- `mss:N` — согласованный MSS

**Расшифровка wscale:** `wscale:7,7` означает множитель 2^7 = 128 для обеих сторон. Реальное окно = Window Size × 128.

**Подробнее о опциях:** [Опции TCP](./options.md) | **Подробнее о флагах:** [Формат заголовка TCP](./index.md)

---

## Практические сценарии

### Анализ заголовка через tcpdump

```bash
# Показать заголовки TCP с флагами
tcpdump -i eth0 -nn -v tcp

# Пример вывода:
# IP 192.168.1.10.45678 > 93.184.216.34.80: Flags [S], seq 1234567890, win 65535,
# options [mss 1460,sackOK,TS val 1234567890 ecr 0,nop,wscale 7], length 0
```

**Расшифровка:**

- `Flags [S]` — SYN-пакет (начало handshake)
- `seq 1234567890` — Initial Sequence Number (ISN)
- `win 65535` — максимальное окно без scaling (64 КБ)
- `mss 1460` — MSS = 1460 байт (стандарт для Ethernet MTU 1500)
- `sackOK` — поддержка SACK разрешена
- `TS val 1234567890 ecr 0` — timestamp отправителя, echo = 0 (первый пакет)
- `wscale 7` — window scale = 2^7 = 128
- `length 0` — только заголовок, без данных (характерно для handshake)

**Диагностика handshake:**

```bash
# Перехват только SYN-пакетов
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0 and not tcp[tcpflags] & tcp-ack != 0'

# Перехват RST-пакетов (сброс соединений)
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0'
```

---

### Проверка опций через ss

```bash
# Показать TCP-сокеты с опциями
ss -tno

# Вывод:
# State    Recv-Q   Send-Q     Local Address:Port     Peer Address:Port
# ESTAB    0        0          192.168.1.10:443      10.0.0.5:54321
#          cubic ts sack wscale:7,7 mss:1460
```

**Диагностика проблем:**

| Симптом | Возможная причина | Команда проверки |
| :--- | :--- | :--- |
| Малое окно без scaling | Window scale не согласован | `ss -tno` → проверить `wscale` |
| Отсутствие `sack` | SACK отключен в ядре | `sysctl net.ipv4.tcp_sack` |
| Отсутствие `ts` | Timestamps отключены | `sysctl net.ipv4.tcp_timestamps` |
| Низкий MSS | Проблемы MTU на пути | `ss -tno` → проверить `mss` |

**Подробнее о диагностике надежности:** [Диагностика надежности TCP](../reliability_mechanisms/diagnostics.md)

---

## Дополнительная информация

### Эволюция заголовка TCP

| RFC | Год | Добавленные опции |
| :--- | :--- | :--- |
| **RFC 793** | 1981 | Базовый заголовок |
| **RFC 1323** | 1992 | Window Scale, Timestamps |
| **RFC 2018** | 1996 | SACK |
| **RFC 3168** | 2001 | ECN |
| **RFC 7323** | 2014 | Обновление RFC 1323 |

### Связанные темы

Для анализа TCP-трафика используются инструменты [tcpdump](../../../../Linux/Diagnostics/Networking/tcpdump.md) (перехват пакетов) и [ss](../../../../Linux/Diagnostics/Networking/ss.md) (информация о сокетах). Графический анализатор Wireshark предоставляет расширенную визуализацию заголовков. Влияние параметров заголовка на производительность описано в [Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md), использование флагов при установке соединения — в [Handshake](../connection/tcp_connection_overview.md).

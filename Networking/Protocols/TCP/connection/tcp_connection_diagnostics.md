# Диагностика TCP-соединений

## 1. Диагностика состояний через ss

```bash
# Все TCP-соединения с состояниями
ss -tan

# Состояния с процессами
ss -tanp

# Подсчёт по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c

# Пример вывода:
#   1500 ESTAB
#     50 TIME-WAIT
#     10 CLOSE-WAIT
#      5 SYN-RECV
```

---

## 2. Анализ handshake через tcpdump

```bash
# Перехват TCP-handshake
tcpdump -i eth0 -nn 'tcp port 80' -v

# Пример вывода handshake:
# 10:15:30.123456 IP 192.168.1.10.54321 > 93.184.216.34.80: Flags [S], seq 1234567890
# 10:15:30.130000 IP 93.184.216.34.80 > 192.168.1.10.54321: Flags [S.], seq 987654321, ack 1234567891
# 10:15:30.135000 IP 192.168.1.10.54321 > 93.184.216.34.80: Flags [.], ack 987654322
```

**Обозначения флагов:**

- `[S]` — SYN
- `[S.]` — SYN-ACK
- `[.]` — ACK
- `[F.]` — FIN-ACK
- `[R]` — RST

---

## 3. TIME_WAIT на клиенте vs сервере

| Сценарий | Кто в TIME_WAIT | Почему |
| :--- | :--- | :--- |
| **Браузер загружает страницу** | Клиент | Клиент инициирует закрытие |
| **HTTP-сервер отдаёт файл** | Сервер (при active close) | Сервер закрывает после отдачи |
| **Keep-alive соединения** | Реже | Соединение переиспользуется |

**Оптимизация для клиентских соединений:**

```bash
# Для исходящих соединений (клиенты)
sysctl -w net.ipv4.tcp_tw_reuse=1
```

**Подробнее:** [Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning.md#управление-состоянием-time_wait-и-ephemeral-портами).

---

## 4. Связанные документы

- **[Обзор и handshake](./tcp_connection_management_overview.md)** — установка соединения
- **[Завершение соединения](./tcp_connection_termination.md)** — четырёхэтапное завершение
- **[Состояния TCP](./tcp_connection_states.md)** — полная таблица состояний
- **[Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — управление TIME_WAIT, SYN backlog

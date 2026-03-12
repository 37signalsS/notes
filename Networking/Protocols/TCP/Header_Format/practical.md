# Практика анализа заголовка TCP

## Определения

**Анализ заголовка TCP** — диагностика и проверка параметров TCP-соединений через tcpdump и ss.

> **Навигация:** [Главная Header Format](./index.md) | [Опции](./options.md)

---

## Practical Scenarios

### Анализ заголовка tcpdump

```bash
# Показать заголовки TCP с флагами
tcpdump -i eth0 -nn -v tcp

# Пример вывода:
# IP 192.168.1.10.45678 > 93.184.216.34.80: Flags [S], seq 1234567890, win 65535,
# options [mss 1460,sackOK,TS val 1234567890 ecr 0,nop,wscale 7], length 0
```

**Расшифровка:**

- `Flags [S]` — SYN-пакет (handshake)
- `win 65535` — максимальное окно без scaling
- `mss 1460` — MSS = 1460 байт
- `wscale 7` — window scale = 2^7 = 128
- `length 0` — только заголовок, без данных

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

**Опции:**

- `cubic` — алгоритм congestion control
- `ts` — timestamps включены
- `sack` — SACK разрешен
- `wscale:7,7` — scale отправителя и получателя
- `mss:1460` — согласованный MSS

---

## Additional Information

### Эволюция заголовка TCP

| RFC | Год | Добавленные опции |
| :--- | :--- | :--- |
| **RFC 793** | 1981 | Базовый заголовок |
| **RFC 1323** | 1992 | Window Scale, Timestamps |
| **RFC 2018** | 1996 | SACK |
| **RFC 3168** | 2001 | ECN |
| **RFC 7323** | 2014 | Обновление RFC 1323 |

### Связанные темы

- **[Надежность TCP](./reliability_mechanisms.md)** — как поля заголовка обеспечивают надежность
- **[Handshake](./connection_management.md)** — использование SYN, ACK, Sequence Number
- **[Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — влияние параметров на заголовок

### Инструменты анализа

- **[tcpdump](../../../../Linux/Diagnostics/Networking/tcpdump.md)** — перехват и анализ пакетов
- **[ss](../../../../Linux/Diagnostics/Networking/ss.md)** — информация о сокетах
- **Wireshark** — графический анализатор трафика

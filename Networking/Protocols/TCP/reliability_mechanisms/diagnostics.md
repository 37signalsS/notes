# Диагностика механизмов надежности TCP

## Мониторинг ретрансмиссий

### Статистика TCP

```bash
# Общая статистика
netstat -s | grep -i retrans

# Пример вывода:
#     1234567 segments retransmitted (0.5% of total)
#     8901 retransmits due to timeout
#     234567 fast retransmits
```

**Интерпретация:**

* `retransmits due to timeout` — потери, обнаруженные по RTO (серьезно)
* `fast retransmits` — потери, обнаруженные по DupACK (нормально при высокой нагрузке)

### Детальная информация о сокетах

```bash
# Информация о сокетах с TCP-параметрами
ss -tmo

# Пример вывода:
# cubic wscale:7,7 rto:204 rtt:0.5/0.25
# ato:40 mss:1460 cwnd:10
# bytes_acked:10000 bytes_received:5000
# segs_out:100 segs_in:50
# retrans: 5
```

**Поля:**

| Поле | Описание |
| :--- | :--- |
| `rto:204` | Текущий RTO (204 мс) |
| `rtt:0.5/0.25` | RTT среднее/отклонение (0.5 ± 0.25 мс) |
| `retrans: 5` | Количество ретрансмиссий для этого сокета |
| `cwnd:10` | Congestion window (в сегментах) |

## Мониторинг в реальном времени

```bash
# Счетчики TCP-событий
watch -n1 'netstat -s | grep -E "segments retrans|retransmits due"'

# Пер-сокет статистика
watch -n1 'ss -tmo | grep -c "retrans:"'

# Соединения с ретрансмиссиями
ss -tmo | awk '/retrans: [1-9]/'
```

## Анализ через tcpdump

### Перехват TCP с последовательностями

```bash
# Базовый перехват
tcpdump -i eth0 -nn 'tcp port 80' -v

# С подробной информацией
tcpdump -i eth0 -nn 'tcp' -vvv -X
```

**Пример анализа потерь:**

```
10:15:30.123 IP 192.168.1.10.54321 > 93.184.216.34.80: seq 1001:2000
10:15:30.130 IP 192.168.1.10.54321 > 93.184.216.34.80: seq 2001:3000
10:15:30.135 IP 93.184.216.34.80 > 192.168.1.10.54321: ack 2001
10:15:30.140 IP 192.168.1.10.54321 > 93.184.216.34.80: seq 3001:4000
10:15:30.150 IP 93.184.216.34.80 > 192.168.1.10.54321: ack 2001  # DupACK!
10:15:30.155 IP 93.184.216.34.80 > 192.168.1.10.54321: ack 2001  # DupACK!
10:15:30.160 IP 93.184.216.34.80 > 192.168.1.10.54321: ack 2001  # DupACK!
10:15:30.165 IP 192.168.1.10.54321 > 93.184.216.34.80: seq 2001:3000  # Fast Retransmit
```

**Анализ:**

* seq 2001:3000 потерян (нет ACK 3001)
* 3 DupACK → Fast Retransmit
* Ретрансмиссия через 25 мс (быстрее RTO)

### Анализ SACK

```bash
# Перехват с SACK
tcpdump -i eth0 -nn 'tcp' -vvv | grep -i sack

# Пример вывода:
# SACK 3001:4001 (получено [3001-4000])
```

## Настройка параметров RTO

```bash
# Минимальное RTO (мс), по умолчанию 200
sysctl -w net.ipv4.tcp_rto_min=200

# Количество SYN-ретрансмиссий перед отказом
sysctl -w net.ipv4.tcp_syn_retries=5

# Просмотр текущих значений
sysctl net.ipv4.tcp_rto_min
sysctl net.ipv4.tcp_syn_retries
```

**Важно:** уменьшение `tcp_rto_min` может вызвать избыточные ретрансмиссии в сетях с высокой задержкой.

## Типичные проблемы и решения

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Высокий % ретрансмиссий** | >1% сегментов ретранслируется | Проверить сеть, перегрузку, MTU |
| **Частые RTO** | Много `retransmits due to timeout` | Серьезная перегрузка, потеря связи |
| **SACK не работает** | Нет SACK blocks в tcpdump | Проверить `net.ipv4.tcp_sack=1` |
| **Дубликаты сегментов** | Получатель отбрасывает дубликаты | Нормально, Sequence Numbers фильтруют |

## Проверка SACK

```bash
# Проверка включения SACK
sysctl net.ipv4.tcp_sack
# 1 — включено, 0 — отключено

# Включение
sysctl -w net.ipv4.tcp_sack=1

# Постоянное включение (/etc/sysctl.conf)
net.ipv4.tcp_sack=1
```

## Полезные метрики для мониторинга

* **Retransmission rate:** `retransmits / total_segments`
* **RTO rate:** `rto_retransmits / total_retransmits`
* **SACK efficiency:** `sack_retransmits / total_retransmits`
* **Average RTT:** из `ss -tmo` или tcpdump

## Связанные темы

* **[Retransmission](./retransmission.md)** — механизмы повторной передачи
* **[Acknowledgments](./acknowledgments.md)** — DupACK и SACK
* **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — анализ трафика
* **[Congestion Control](./congestion_control.md)** — реакция на потери

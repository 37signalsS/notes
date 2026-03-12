# Практика управления потоком TCP

## Определения

**Диагностика Flow Control** — анализ состояния TCP-окон и буферов для выявления проблем производительности.

> **Навигация:** [Главная Flow Control](./index.md) | [Механизмы](./mechanisms.md)

---

## Practical Scenarios

### Диагностика через ss

```bash
# Показать окна отправителя и получателя
ss -tmo

# Пример вывода:
# ESTAB  0  0  192.168.1.10:443  10.0.0.5:54321
#   cubic wscale:7,7 rto:204 rtt:0.5/0.25
#   ato:40 mss:1460 pmtu:1500 rcvmss:1460 advmss:1460 cwnd:10
#   bytes_acked:1000 bytes_received:2000
#   segs_out:10 segs_in:5
#   send 100.0Mbps  rcvspace:262640  rcv_rtt:0.5
```

**Поля:**

- `rcvspace` — размер receive buffer (влияет на rwnd)
- `cwnd` — текущее окно перегрузки
- `advmss` — объявленный MSS

---

### Zero Window в production

**Симптом:** приложение медленно читает данные, TCP-окно падает до 0.

**Диагностика:**

```bash
# Поиск сокетов с нулевым окном
ss -tmo | grep 'window:0'

# Мониторинг в реальном времени
watch -n1 'ss -tmo | grep -c "window:0"'
```

**Причины:**

- Приложение не успевает читать из сокета
- Блокировка на уровне приложения (GC, locks, I/O)
- Недостаточный размер буфера (`SO_RCVBUF`)

**Решение:**

1. Оптимизировать приложение (быстрее читать)
2. Увеличить буфер:

   ```bash
   sysctl -w net.ipv4.tcp_rmem='4096 87380 16777216'
   ```

---

### Настройка буферов TCP

**Параметры Linux:**

```bash
# Максимальный размер receive buffer
sysctl -w net.core.rmem_max=16777216

# Максимальный размер send buffer
sysctl -w net.core.wmem_max=16777216

# Min, default, max для TCP receive
sysctl -w net.ipv4.tcp_rmem='4096 87380 16777216'

# Min, default, max для TCP send
sysctl -w net.ipv4.tcp_wmem='4096 65536 16777216'
```

**Автотюнинг:** современные ядра Linux автоматически настраивают размер буфера в пределах указанных значений.

---

### Window Scaling в действии

**Проверка поддержки:**

```bash
# Проверка wscale на активных соединениях
ss -tno | grep wscale

# Пример:
# wscale:7,7  (отправитель:7, получатель:7)
```

**Расчет реального окна:**

```
Window Size в заголовке: 65535
Window Scale: 7 (2^7 = 128)
Реальное окно: 65535 × 128 = 8 388 480 байт (~8 МБ)
```

**Без window scaling:**

```
Максимум: 65535 байт (~64 КБ)
При RTT=100ms: 64KB / 0.1s = 640 KB/s (~5 Мбит/с)
```

**С window scaling:**

```
Максимум: ~1 ГБ
При RTT=100ms: 1GB / 0.1s = 10 GB/s (~80 Гбит/с)
```

---

## Additional Information

### Связанные темы

- **[Congestion Control](./congestion/congestion_control.md)** — управление перегрузкой сети
- **[Header Format](../Header_Format/header_format.md#7-размер-окна-window-size-16-бит)** — поле Window Size
- **[Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_buffer_tuning.md)** — настройка буферов
- **[Wireshark: Диагностика производительности](../../../ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md)** — диагностика Zero Window и проблем клиента

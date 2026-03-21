# Диагностика сокетов TCP

## Основные команды

### Проверка сокетов в TIME_WAIT

```bash
# Количество сокетов в TIME_WAIT
ss -tan 'state time-wait' | wc -l

# Общая статистика
ss -s
```

### Проверка текущего алгоритма перегрузки

```bash
# Просмотр доступных алгоритмов
cat /proc/sys/net/ipv4/tcp_available_congestion_control

# Текущий алгоритм
sysctl net.ipv4.tcp_congestion_control

# Проверка BBR в действии
ss -ti | grep bbr
```

### Диагностика TFO

```bash
# Проверка поддержки TFO в ядре
cat /proc/sys/net/ipv4/tcp_fastopen

# Проверка TFO в действии (tcpdump)
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0'

# Статистика TFO (ядро 4.10+)
nstat -az | grep -i tfo
# TcpExtTCPFastOpenActive — активные соединения с TFO
# TcpExtTCPFastOpenPassive — пассивные соединения с TFO
# TcpExtTCPFastOpenCookieSent — отправлено cookie
```

## Связанные темы

* **[`ss`](../../../Diagnostics/Networking/ss.md)** — детальная диагностика сокетов
* **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)

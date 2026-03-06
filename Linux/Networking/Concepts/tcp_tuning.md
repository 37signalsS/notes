# Оптимизация TCP в Linux

## Определения

* **Оптимизация TCP** — процесс настройки параметров сетевого стека ядра Linux для улучшения производительности TCP-соединений, снижения задержек и повышения пропускной способности.
* **`TIME_WAIT`** — состояние TCP-соединения после закрытия для обеспечения надежной доставки последних пакетов и предотвращения проблем с новыми соединениями.
* **BBR (Bottleneck Bandwidth and Round-trip time)** — алгоритм контроля перегрузки от Google, оптимизирующий пропускную способность и минимизирующий задержки путем моделирования характеристик канала.
* **TCP Backlog** — очередь входящих TCP-подключений:
  * **SYN backlog** — очередь полуоткрытых соединений (`SYN_RECV`), контролируется `net.ipv4.tcp_max_syn_backlog`.
  * **Accept backlog** — очередь установленных соединений (`ESTABLISHED`), ожидающих `accept()`, размер определяется `net.core.somaxconn`.
* **initcwnd** — начальное окно перегрузки (initial congestion window), определяющее объем данных, отправляемых в первой "волне" после установки соединения.

## Основные концепции

### Зависимость от нагрузки

Производительность TCP/IP стека ядра Linux критично зависит от настроек при высоких нагрузках (тысячи одновременных подключений). Стандартные параметры могут стать узким местом.

### Механизмы настройки

Все параметры настраиваются через [`sysctl`](../../Core/kernel/sysctl.md):

* Временно: `sudo sysctl -w <параметр>=<значение>`
* Постоянно: `/etc/sysctl.conf` или `/etc/sysctl.d/99-network.conf`, затем `sudo sysctl -p`

### Алгоритмы управления перегрузкой

* **CUBIC** — алгоритм по умолчанию в большинстве дистрибутивов. Универсальный, но может создавать очереди при высокой нагрузке.
* **BBR (Bottleneck Bandwidth and Round-trip time)** — минимизирует очереди, удерживая скорость близкой к пропускной способности канала. Эффективен на каналах с потерями (мобильные сети).
* **BBRv2** — улучшенная версия BBR с лучшей справедливостью (fairness) по отношению к CUBIC и лучшими характеристиками в сетях с потерями. Доступен в ядре 5.18+ (не во всех дистрибутивах).
* **BBRv3** — latest версия от Google, **НЕ включена в mainline Linux kernel** (2026). Доступна через патчи.
* **Reno** — классический алгоритм, основанный на потерях. Устарел для современных сетей.

### Доступные алгоритмы в системе

```bash
# Просмотр доступных алгоритмов
cat /proc/sys/net/ipv4/tcp_available_congestion_control

# Текущий алгоритм
sysctl net.ipv4.tcp_congestion_control
```

### Дисциплины очередей (Queueing Disciplines)

> Детальная настройка дисциплин выполняется через [`tc`](../Tools/iproute2/tc.md).

* **fq_codel** — снижает латентность при смешанных нагрузках, борется с bufferbloat. Устанавливается по умолчанию через `net.core.default_qdisc`.
* **fq (Fair Queuing)** — полезен для точного pacing с BBR при крупных передачах.

### Влияние переполнения backlog

* Переполнение `SYN backlog` → отбрасывание SYN-пакетов (SYN drop) → задержки установления соединения.
* Переполнение `Accept backlog` → сброс соединений с отправкой `RST` → отказы в обслуживании.

## Практические сценарии

### Комплексная настройка для низкой латентности

```bash
# Дисциплина очереди по умолчанию (требует поддержки в ядре)
sysctl -w net.core.default_qdisc=fq_codel

# Алгоритм контроля перегрузки
sysctl -w net.ipv4.tcp_congestion_control=bbr

# TCP Fast Open для сокращения handshake
sysctl -w net.ipv4.tcp_fastopen=3

# Увеличение очередей для предотвращения отказов при всплесках
sysctl -w net.core.somaxconn=4096
sysctl -w net.core.netdev_max_backlog=4096

# Включение SACK и timestamps
sysctl -w net.ipv4.tcp_sack=1
sysctl -w net.ipv4.tcp_timestamps=1
```

### Управление очередями соединений

```bash
# Увеличить accept backlog (максимум ожидающих соединений)
sudo sysctl -w net.core.somaxconn=65535

# Увеличить SYN backlog (полуоткрытые соединения). Это помогает предотвратить отбрасывание SYN-пакетов (SYN drop).
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096

# Увеличить очередь пакетов от NIC(сетевой карты). Помогает не терять пакеты при кратковременных всплесках трафика, когда ядро не успевает их обработать.
sudo sysctl -w net.core.netdev_max_backlog=30000
```

### Управление состоянием TIME_WAIT

На серверах с большим количеством короткоживущих соединений (веб-серверы, API-шлюзы) скапливается много сокетов в состоянии `TIME_WAIT`, занимая порты и память.

```bash
# Разрешить повторное использование сокетов TIME_WAIT (исходящие соединения). Этот параметр не затрагивает входящие соединения.
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Уменьшить время нахождения сокета в состоянии FIN-WAIT-2
sudo sysctl -w net.ipv4.tcp_fin_timeout=15

# Расширить диапазон эфемерных портов для исходящих соединений
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
```

> **Важно:** `net.ipv4.tcp_tw_recycle` удален в ядре 4.12+ из-за проблем с NAT. Не использовать.

### Оптимизация буферов TCP

```bash
# Максимальный размер буфера приема и передачи для всех типов соединений.
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216

# Минимальный, начальный, максимальный размеры для TCP
sudo sysctl -w net.ipv4.tcp_rmem='4096 87380 16777216'
sudo sysctl -w net.ipv4.tcp_wmem='4096 65536 16777216'
```

### Включение BBR

Требования: ядро Linux 4.9+

```ini
# /etc/sysctl.conf
# Включить Fair Queuing (обязательно для BBR)
net.core.default_qdisc = fq
# Установить BBR как алгоритм контроля перегрузки
net.ipv4.tcp_congestion_control = bbr
```

```bash
sudo sysctl -p
# Проверка
ss -ti | grep bbr
```

### Включение BBRv2

Требования: ядро Linux 5.18+

```ini
# /etc/sysctl.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr2
```

**Преимущества BBRv2 по сравнению с BBRv1:**

* Лучшая справедливость (fairness) при совместной работе с CUBIC
* Улучшенная производительность в сетях с потерями пакетов
* Более стабильная работа с WiFi и мобильными сетями
* Поддержка ECN (Explicit Congestion Notification)

```bash
# Проверка поддержки BBRv2
modprobe tcp_bbr2
cat /proc/sys/net/ipv4/tcp_available_congestion_control | grep bbr2
```

> **Примечание:** BBRv2 может быть недоступен в старых дистрибутивах. Требуется ядро 5.18+.

### Включение BBRv3 (experimental)

> **Внимание:** BBRv3 **НЕ** включен в mainline Linux kernel (2026). Требует патчей или сборки ядра.

```ini
# /etc/sysctl.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr3
```

### Настройка initcwnd

> Подробнее о настройке через `ip route` см. в [`ip route`](../Tools/iproute2/ip_route.md).

По умолчанию: 10 MSS (~14 КБ). Увеличение до 20-40 безопасно для большинства веб-серверов.

Это изменение не будет постоянным и сбросится после перезагрузки. Для постоянной настройки его нужно применять через скрипты управления сетью

```bash
# Чтобы увидеть cwnd, ищем параметр 'initcwnd'. Если он не указан, используется значение по умолчанию.
ip route show | grep 'initcwnd'

# Установить initcwnd=30 для всех новых соединений, идущих через шлюз по умолчанию
# Сначала найдем шлюз по умолчанию
GATEWAY=$(ip route | grep default | awk '{print $3}')
DEVICE=$(ip route | grep default | awk '{print $5}')
sudo ip route change default via $GATEWAY dev $DEVICE initcwnd 30
```

### Защита от [SYN-флуд](../../../Networking/Concepts/dos_ddos_overview.md#syn-флуд)

```bash
# Включение SYN cookies (обычно включено по умолчанию)
sudo sysctl -w net.ipv4.tcp_syncookies=1
```

Активируется автоматически при риске переполнения SYN backlog.

## Дополнительная информация

### Принцип работы BBR

В отличие от классических алгоритмов, основанных на потерях (таких как CUBIC), BBR не ждет потери пакетов, чтобы снизить скорость. Вместо этого он постоянно моделирует сеть, измеряя два ключевых параметра:

1. **Пропускную способность узкого места** (Bottleneck Bandwidth)
2. **Время кругового пути** (RTT)

На основе этих данных BBR старается поддерживать объем передаваемых данных на уровне, который точно соответствует произведению `Bandwidth * RTT` (Bandwidth-Delay Product), не создавая при этом лишних очередей на маршрутизаторах (bufferbloat).

### Диагностика сокетов

```bash
# Количество сокетов в TIME_WAIT
ss -tan 'state time-wait' | wc -l

# Общая статистика
ss -s
```

> Детальная диагностика: [`ss`](../../Diagnostics/Networking/ss.md)

### Связанные темы

* **[`tc`: Управление трафиком](../Tools/iproute2/tc.md)** — детальная настройка дисциплин очередей (HTB, fq_codel)
* **[`sysctl`](../../Core/kernel/sysctl.md)** — управление параметрами ядра
* **[RSS, RPS, RFS](./rss_rps_rfs.md)** — многопоточная обработка сетевого трафика
* **[`ip route`](../Tools/iproute2/ip_route.md)** — настройка initcwnd для маршрутов
* **[Wireshark: Диагностика производительности](../../../Networking/ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md)** — анализ проблем производительности

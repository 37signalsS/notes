# Оптимизация TCP в Linux: Обзор

## Определения

* **Оптимизация TCP** — процесс настройки параметров сетевого стека ядра Linux для улучшения производительности TCP-соединений, снижения задержек и повышения пропускной способности.
* **`TIME_WAIT`** — состояние TCP-соединения после закрытия для обеспечения надежной доставки последних пакетов. Подробнее: [Управление TIME_WAIT](./tcp_time_wait_management.md).
* **BBR (Bottleneck Bandwidth and Round-trip time)** — алгоритм контроля перегрузки от Google. Подробнее: [Алгоритмы управления перегрузкой](./tcp_congestion_algorithms.md).
* **TCP Backlog** — очередь входящих TCP-подключений. Подробнее: [Управление очередями соединений](./tcp_connection_queues.md).
* **initcwnd (Initial Congestion Window)** — начальное окно перегрузки, определяющее объем данных в первой "волне". Подробнее: [Настройка initcwnd](./tcp_initcwnd.md).
* **TCP Fast Open (TFO)** — расширение TCP, позволяющее передавать данные в SYN-пакете. Подробнее: [TCP Fast Open](./tcp_fast_open.md).

## Основные концепции

### Зависимость от нагрузки

Производительность TCP/IP стека ядра Linux критично зависит от настроек при высоких нагрузках (тысячи одновременных подключений). Стандартные параметры могут стать узким местом.

### Механизмы настройки

Все параметры настраиваются через [`sysctl`](../../../Core/kernel/sysctl.md):

* Временно: `sudo sysctl -w <параметр>=<значение>`
* Постоянно: `/etc/sysctl.conf` или `/etc/sysctl.d/99-network.conf`, затем `sudo sysctl -p`

### Влияние переполнения backlog

* Переполнение **SYN backlog** → отбрасывание SYN-пакетов (SYN drop) → задержки установления соединения.
* Переполнение **Accept backlog** → сброс соединений с отправкой `RST` → отказы в обслуживании.
* Детали настройки очередей: [Управление очередями соединений](./tcp_connection_queues.md).

### Разделение теории и практики

* **Теоретические основы** (алгоритмы congestion control, формулы BDP, фазы BBR): [`Networking/Protocols/TCP/congestion/`](../../../../Networking/Protocols/TCP/congestion/tcp_congestion_control_overview.md)
* **Linux-специфика** (sysctl, команды, диагностика): текущая директория.

## Практические сценарии

### Высоконагруженный веб-сервер (Nginx/HAProxy)

* **Проблема:** тысячи коротких HTTP-соединений, накопление `TIME_WAIT`, переполнение backlog.
* **Решение:**
  * Увеличить `net.core.somaxconn` до 4096–65535.
  * Включить `net.ipv4.tcp_tw_reuse=1`. См. [Управление TIME_WAIT](./tcp_time_wait_management.md).
  * Расширить диапазон ephemeral ports: `net.ipv4.ip_local_port_range=1024 65535`.
  * Настроить `net.ipv4.tcp_max_syn_backlog=8192`.
  * Сохранить окно перегрузки для keep-alive соединений при долгом простое: `net.ipv4.tcp_slow_start_after_idle=0`.
  * Увеличить размер таблицы соединений Netfilter: `net.netfilter.nf_conntrack_max`.
* **Дополнительно:** рассмотреть [алгоритм BBR](./tcp_congestion_algorithms.md) и дисциплину очереди `fq` ([Дисциплины очередей](./tcp_queueing_disciplines.md)).

### Оптимизация доставки и задержек

* **Уменьшение фрагментации:** Включение `net.ipv4.tcp_mtu_probing=1` снижает фрагментацию пакетов на длинных расстояниях.
* **HTTP/2 приоритизация:** Регулирование буферизации `net.ipv4.tcp_notsent_lowat` позволяет лучше управлять приоритизацией стримов в HTTP/2.

### Микросервисная архитектура (service mesh)

* **Проблема:** большое количество короткоживущих соединений между сервисами, задержки установления соединения.
* **Решение:**
  * Включить [TCP Fast Open](./tcp_fast_open.md) (`net.ipv4.tcp_fastopen=3`).
  * Увеличить [initcwnd](./tcp_initcwnd.md) до 10–30 сегментов для уменьшения Slow Start.
  * Использовать `fq` qdisc для packet pacing. См. [Дисциплины очередей](./tcp_queueing_disciplines.md).
* **Дополнительно:** мониторинг через `ss -ti` для контроля RTT и retransmits.

### Высокая пропускная способность (CDN, streaming)

* **Проблема:** необходимость передачи больших объемов данных на большие расстояния.
* **Решение:**
  * Включить BBR: `net.ipv4.tcp_congestion_control=bbr`.
  * Настроить автонастройку буферов: `net.ipv4.tcp_moderate_rcvbuf=1`.
  * Увеличить `net.core.rmem_max` и `net.core.wmem_max`. Детали: [Оптимизация буферов TCP](./tcp_buffer_tuning.md).
  * Рассчитать оптимальный размер буфера по формуле BDP.
* **Дополнительно:** отключить TCP timestamps для снижения overhead (`net.ipv4.tcp_timestamps=0`).

### Диагностика проблем

Для глубокого анализа состояния сокетов и параметров TCP используйте [диагностику сокетов](./tcp_socket_diagnostics.md).

* **Переполнение backlog:** `nstat -az | grep -E 'ListenDrops|Syncookies'`
* **Перегрузка congestion control:** `ss -ti | grep -E 'cwnd|rto|retrans'`
* **Накопление TIME_WAIT:** `ss -tan state time-wait | wc -l`
* **Проверка TFO:** `nstat -az | grep -E 'TcpExtTCPFastOpen|TcpExtTCPFastOpenCookie'`

## Дополнительная информация

### Версионность ядра

* **BBR v1:** ядро 4.9+
* **BBR v2:** ядро 5.4+ (поддержка DCPC-style policing)
* **BBR v3:** ядро 5.19+ (multi-mode, per-flow policing)
* **TCP Fast Open:** ядро 3.6+ (клиент), 3.7+ (сервер)

### См. также

* [Оптимизация буферов TCP](./tcp_buffer_tuning.md)
* [Управление очередями соединений](./tcp_connection_queues.md)
* [Алгоритмы управления перегрузкой](./tcp_congestion_algorithms.md)

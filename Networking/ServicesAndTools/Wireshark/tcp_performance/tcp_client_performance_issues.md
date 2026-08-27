# Диагностика проблем производительности клиента TCP

> **SSoT:** Определения базовых терминов (RTT, iRTT, Window Size, Expert Info) — в **[Определения](../definitions.md)**. Концепции захвата и offloading — в **[Основные концепции](../core_concepts.md)**. tshark-команды — в **[Использование tshark](../tshark_usage.md)**. Обзор диагностики — в **[Обзор диагностики](./tcp_performance_diagnostics.md)**. Проблемы сервера — в **[Серверные проблемы](./tcp_server_performance_issues.md)**. Потери и offloading — в **[Сетевые потери](./tcp_network_losses_and_offloading.md)**. Графики — в **[Инструменты анализа](./tcp_performance_analysis_tools.md)**. Flow Control — в **[Flow Control в TCP](../../Protocols/TCP/Flow_Control/index.md)**.

## Определения

**TCP Zero Window** — состояние, при котором получатель (клиент) объявляет размер окна равным нулю (`rwnd = 0`). Это жесткий сигнал отправителю о переполнении приемного буфера (`SO_RCVBUF`) и требование немедленно остановить передачу данных.

**TCP Window Full** — диагностическое событие в Wireshark, означающее, что отправитель заполнил всё анонсированное окно получателя и вынужден ожидать подтверждения (ACK). В отличие от Zero Window, это состояние «потолка» текущей пропускной способности, а не ошибка приложения.

**Bytes in Flight (Байты в полете)** — объем данных, отправленных, но еще не подтвержденных получателем. Если это значение равно `Window Size`, наступает событие `Window Full`.

**Window Scaling (Масштабирование окна)** — опция TCP (RFC 7323), позволяющая увеличить максимальное окно с 64 КБ до 1 ГБ через коэффициент масштабирования (`Shift count`). В 2026 году для эффективной работы на скоростях 10G+ в сетях LFN (Long Fat Networks) требует обязательного включения **TCP Timestamps** для защиты от наложения Seq-номеров (PAWS).

## Quick-Start: Чек-лист диагностики клиентских проблем

Быстрый старт при подозрении на проблемы на стороне клиента:

| Шаг | Действие | Как проверить | Норма |
| :--- | :--- | :--- | :--- |
| **1** | Zero Window | `tcp.analysis.zero_window` | 0 пакетов |
| **2** | Window Full | `tcp.analysis.window_full` | 0 пакетов |
| **3** | Window Probe | `tcp.analysis.zero_window_probe` | 0 пакетов |
| **4** | Bytes in Flight vs Window | `tcp.analysis.bytes_in_flight` < `tcp.window_size` | Всегда |
| **5** | Window Scale согласован | SYN → `Options: Window Scale` | В SYN и SYN-ACK |
| **6** | Timestamps включены | SYN → `Options: Timestamps` | В SYN и SYN-ACK |
| **7** | Автотюнинг буферов | `sysctl net.ipv4.tcp_rmem` | max >= 16 МБ |

## Основные концепции

### Механизм возникновения задержек на стороне клиента

Проблема «тормозит клиент» обычно связана с тем, что приложение медленнее считывает данные из сокета через системные вызовы (`read`, `recv`, `copy_to_user`), чем сетевой стек их доставляет.

1. **Заполнение буфера приема**: Данные накапливаются в `SO_RCVBUF`. В современных ядрах Linux (6.x+) механизм **DRS (Dynamic Receiver Sizing)** пытается автоматически расширить буфер на основе BDP, если приложение активно вычитывает данные.
2. **Снижение анонсированного окна (Advertised Window)**: Клиент в каждом ACK-пакете сообщает серверу об остатке свободного места в буфере.
3. **Zero Window**: Свободное место заканчивается. Сервер прекращает передачу и запускает **Persist Timer**.
4. **Window Probe**: Сервер периодически отправляет проверочные пакеты (1 байт), чтобы спровоцировать клиента на отправку ACK с актуальным размером окна.
5. **Window Update**: Как только приложение освобождает место в буфере, клиент отправляет пакет с обновленным окном (Window Update) для возобновления потока.

### Проблема отсутствия Window Scaling (LFN)

В сетях с большой задержкой и высокой пропускной способностью (LFN — Long Fat Networks) отсутствие масштабирования окна является критической проблемой.
- Без `wscale` максимальное окно — 64 КБ.
- При RTT 100 мс максимальная скорость будет: `65535 байт / 0.1 сек = 5.2 Мбит/с`, независимо от того, что канал имеет 1 Гбит/с.
- **Диагностика:** Ищите отсутствие `Window Scale` в пакетах SYN и SYN-ACK.

### DRS (Dynamic Receiver Sizing) — автотюнинг буферов

Механизм DRS (появился в Linux 4.12, значительно улучшен в 5.x+) автоматически изменяет размер приемного буфера на основе наблюдаемого BDP:

```bash
# Проверка включенного автотюнинга
sysctl net.ipv4.tcp_moderate_rcvbuf
# → net.ipv4.tcp_moderate_rcvbuf = 1  (включен)

# Текущий размер буфера для конкретного соединения
ss -tin dst 10.0.0.1 | grep rcv_space
# → rcv_space:131072  ← текущий размер (в байтах)
```

DRS работает только если `net.ipv4.tcp_moderate_rcvbuf = 1` и приложение активно читает из сокета (не блокируется). Если приложение медленное, DRS не может компенсировать его узкое место — буфер растет, но данные в нем «протухают».

### Влияние tcp_adv_win_scale на реальный размер окна

Параметр `net.ipv4.tcp_adv_win_scale` определяет, какая доля буфера `SO_RCVBUF` доступна для данных приложения:

| Значение | Формула | Доступно данных при `SO_RCVBUF = 16 МБ` |
| :--- | :--- | :--- |
| `1` | `buffer / 2` | 8 МБ |
| `2` | `buffer / 4` | 4 МБ |
| `0` | `buffer - buffer/1` | 0 МБ (только overhead) |

По умолчанию `tcp_adv_win_scale = 1` (с ядра 6.x), что означает 50% буфера под данные. На ранних ядрах (4.x) было значение 2 (25% данных).

```bash
# Проверка текущего значения
sysctl net.ipv4.tcp_adv_win_scale
# → net.ipv4.tcp_adv_win_scale = 1

# Для максимальной емкости данных (рекомендуется)
sudo sysctl -w net.ipv4.tcp_adv_win_scale=1
```

### Типичные паттерны клиентских проблем

| Паттерн | Причина | Симптом в Wireshark |
| :--- | :--- | :--- |
| **Single-thread recv()** | Приложение читает данные в основном потоке, блокируясь на БД/API | Zero Window → Window Probe → Window Update → Zero Window (циклически) |
| **Backpressure отсутствует** | Внутренняя очередь приложения переполнена | Bytes in Flight = Window Size, Zero Window через N секунд после начала |
| **Нет autotuning** | `tcp_moderate_rcvbuf = 0` или `SO_RCVBUF` зафиксирован | Window Size не растет при росте RTT/пропускной способности |
| **LFN без Window Scale** | Клиент не поддерживает опцию Window Scale | Window Size ограничен 64 КБ, через 1-2 МБ данных → Zero Window |
| **Overhead tcp_adv_win_scale** | Малый `tcp_adv_win_scale` снижает доступный размер данных | `SO_RCVBUF` большой, но Window Size маленький |

## Практические сценарии

### Сценарий 1: Поиск Zero Window и определение его длительности

Zero Window — самый явный признак проблемы на стороне клиента.

```bash
# tshark: все Zero Window с указанием длительности
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields \
  -e frame.number -e frame.time_relative -e ip.src -e tcp.srcport \
  -e ip.dst -e tcp.dstport -e tcp.window_size_value

# tshark: время между Zero Window и следующим Window Update
tshark -r capture.pcap -Y "tcp.analysis.zero_window || tcp.analysis.window_update" \
  -T fields -e frame.time_relative -e tcp.analysis.zero_window \
  -e tcp.analysis.window_update -e tcp.window_size_value
```

**Интерпретация:**
- Пауза > 100 мс между Zero Window и Window Update → приложение медленно вычитывает данные
- Пауза > 1 с → критическая проблема (зависание приложения или deadlock)
- Нет Window Update вообще → приложение упало или заблокировано навсегда

### Сценарий 2: Визуализация Window Scaling через графики

Используйте `Statistics → TCP Stream Graphs → Window Scaling`:
- **Норма:** Линия окна находится выше линии `Bytes in Flight`.
- **Аномалия:** Линия окна падает и пересекается с `Bytes in Flight` — классический симптом медленного приложения.

```bash
# tshark: экстракт данных для построения графика
tshark -r capture.pcap -Y "tcp.stream eq 0" -T fields \
  -e frame.time_relative -e tcp.window_size_value -e tcp.analysis.bytes_in_flight \
  > window_data.csv

# gnuplot: график Window Size vs Bytes in Flight
gnuplot -e "
set datafile separator '\t';
set xlabel 'Time (s)';
set ylabel 'Bytes';
set title 'Window Size vs Bytes in Flight';
plot 'window_data.csv' using 1:2 with lines title 'Window Size', \
     'window_data.csv' using 1:3 with lines title 'Bytes in Flight'"
```

### Сценарий 3: Анализ Window Probe — Persist Timer

Window Probe возникает после Zero Window, когда сервер проверяет, освободилось ли окно:

```bash
# tshark: поиск Window Probe и ответов на них
tshark -r capture.pcap -Y "tcp.analysis.zero_window_probe || tcp.analysis.zero_window_probe_ack" \
  -T fields -e frame.number -e frame.time_relative \
  -e tcp.analysis.zero_window_probe -e tcp.analysis.zero_window_probe_ack \
  -e tcp.window_size_value -e ip.src -e tcp.srcport

# tshark: время от Zero Window до первого Probe
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields \
  -e frame.time_relative -e tcp.stream | \
  awk '{print $1, $2}' | while read t stream; do
    probe=$(tshark -r capture.pcap -Y "tcp.analysis.zero_window_probe && tcp.stream eq $stream" \
      -T fields -e frame.time_relative 2>/dev/null | head -1)
    echo "Stream $stream: Zero Window at ${t}s, first Probe at ${probe}s"
  done
```

**Persist Timer по умолчанию:** 5-60 секунд (экспоненциальная.backoff от 5с до 60с).

### Сценарий 4: Автотюнинг буферов — проверка и настройка

```bash
# Проверка автотюнинга
sysctl net.ipv4.tcp_moderate_rcvbuf  # должно быть 1
sysctl net.ipv4.tcp_rmem             # min, default, max
sysctl net.core.rmem_max             # должен быть >= tcp_rmem max

# Текущее использование буферов для активных соединений
ss -tin | grep -E "rcv_space|rcv_ssthresh"
# → rcv_space:131072 rcv_ssthresh:131072  ← норма
# → rcv_space:4096 rcv_ssthresh:4096      ← проблема (буфер не растет)

# Мониторинг в реальном времени
watch -n 1 'ss -tin | grep -E "rcv_space|rcv_ssthresh" | head -5'
```

**Нормальные значения для разных сетей:**

| Тип сети | Рекомендуемый `tcp_rmem` max | Ожидаемый `rcv_space` |
| :--- | :--- | :--- |
| 100 Мбит/с, RTT 10 мс | 4 МБ | 2-4 МБ |
| 1 Гбит/с, RTT 10 мс | 16 МБ | 8-16 МБ |
| 10 Гбит/с, RTT 1 мс | 64 МБ | 32-64 МБ |
| LFN (1 Гбит/с, RTT 100 мс) | 64 МБ | 32-64 МБ |

### Сценарий 5: Настройка операционной системы (Linux 2026)

Увеличьте лимиты автотюнинга буферов, чтобы стек мог адаптироваться к BDP:
```bash
# Глобальный лимит памяти для всех TCP-буферов (в страницах памяти)
sudo sysctl -w net.ipv4.tcp_mem='1048576 1572864 2097152'

# Лимиты для буфера приема (min, default, max)
# В 2026 году max 64МБ считается нормой для 100G+ сетей
sudo sysctl -w net.ipv4.tcp_rmem='4096 131072 67108864'

# Максимальный размер буфера сокета (должен быть >= tcp_rmem max)
sudo sysctl -w net.core.rmem_max=67108864

# Управление соотношением полезных данных к служебным в буфере
# Значение 1 означает 50% буфера под данные, 50% под структуру sk_buff
sudo sysctl -w net.ipv4.tcp_adv_win_scale=1
```

**Валидация после настройки:**
```bash
# Проверка примененных значений
sysctl net.ipv4.tcp_rmem net.core.rmem_max net.ipv4.tcp_adv_win_scale

# Проверка через ss для конкретного соединения
ss -tin dst 10.0.0.1
# → rcv_space:67108864  ← подтвердился max из tcp_rmem
```

### Сценарий 6: Оптимизация приложения

1. **io_uring:** Стандарт высокопроизводительного ввода-вывода в 2026 году. Позволяет избежать переключений контекста и лишнего копирования при вычитывании данных из сокета.

```bash
# tshark: сравнение io_uring vs обычного read()
# Для io_uring: smaller delta between packets, more uniform
tshark -r capture.pcap -Y "tcp.stream eq 0 && tcp.len > 0" -T fields \
  -e frame.time_relative -e tcp.time_delta -e tcp.len | head -20
# → Стабильные delta ~0.001s = io_uring
# → Неравномерные delta = обычный read()
```

2. **Backpressure:** В языках с управляемой памятью (Go, Java) событие Zero Window часто вызвано блокировкой основной бизнес-логики или переполнением внутренних очередей (Channels/BlockingQueues). Необходимо внедрять механизмы обратного давления для замедления источника данных.

3. **Zero-copy (splice/mmap):** Передача данных напрямую в файловую систему или GPU без промежуточного копирования в User-space.

### Сценарий 7: Клиентские проблемы в Docker/Kubernetes

В контейнерных средах проблемы с клиентским буфером имеют специфику:

```bash
# Проверка буферов внутри контейнера
docker exec <container> sysctl net.ipv4.tcp_rmem
# → net.ipv4.tcp_rmem = 4096 87380 6291456  ← стандартные значения

# Увеличение буферов для контейнера
docker run --sysctl net.ipv4.tcp_rmem="4096 131072 67108864" ...

# В Kubernetes: через SecurityContext
# securityContext:
#   sysctls:
#   - name: net.ipv4.tcp_rmem
#     value: "4096 131072 67108864"
```

**Типичные проблемы в Kubernetes:**
- **Sidecar-proxy (Envoy/Istio):** Proxy может成為 bottleneck если его буферы меньше, чем у приложения
- **Network Policy:** Файрволы могут замедлять ACK, вызывая ложные Zero Window
- **Service Mesh:** Дополнительный hop увеличивает RTT, что требует больших буферов

## Дополнительная информация

### Диагностика через nstat

```bash
# Счетчики ядра для клиентских проблем
nstat -az TcpExtTCPWindowFull TcpExtTCPWindowProbe TcpExtTCPAutoCork
# → TcpExtTCPWindowFull    42  0.0  ← отправитель заблокирован (zero window)
# → TcpExtTCPWindowProbe   15  0.0  ← Persist Timer сработал
# → TcpExtTCPAutoCork      128 0.0  ← corking (нативная оптимизация)
```

### Таблица типичных проблем

| Проблема | Симптом в Wireshark | Фильтр | Решение |
| :--- | :--- | :--- | :--- |
| **Zero Window** | Получатель объявляет rwnd=0 | `tcp.analysis.zero_window` | Увеличить SO_RCVBUF, оптимизировать чтение |
| **Window Full** | Отправитель уперся в rwnd | `tcp.analysis.window_full` | Проверить autotuning, увеличить буферы |
| **Window Probe** | Сервер проверяет окно | `tcp.analysis.zero_window_probe` | Приложение не читает данные |
| **Нет Window Scale** | Окно ограничено 64 КБ | `tcp.window_size < 65536` | Включить Window Scaling на клиенте |
| **LFN без Timestamps** | Соединение сбрасывается | `tcp.analysis.reset` + LFN | Включить TCP Timestamps |
| **DRS не работает** | rcv_space не растет | `ss -tin \| grep rcv_space` | `tcp_moderate_rcvbuf = 1` |
| **Overhead tcp_adv_win_scale** | Малый window при большом buffer | `tcp.window_size < SO_RCVBUF/2` | `tcp_adv_win_scale = 1` |

### См. также

- **[Flow Control в TCP](../../Protocols/TCP/Flow_Control/index.md)** — теоретические основы управления потоком, autotuning, DRS.
- **[Серверные проблемы](./tcp_server_performance_issues.md)** — диагностика задержек на стороне отправителя.
- **[Обзор диагностики производительности](./tcp_performance_diagnostics.md)** — методология и ключевые метрики.

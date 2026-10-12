# JVM и GC тюнинг для Apache Kafka

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft), OpenJDK 17 LTS / 21 LTS

**JVM и GC тюнинг** — это комплексная оптимизация параметров виртуальной машины Java (JVM), подсистемы управления памятью и сборщика мусора (Garbage Collector) для обеспечения максимальной пропускной способности (throughput), предсказуемых задержек (latency) и отказоустойчивости брокеров и контроллеров Apache Kafka. Некорректное конфигурирование кучи (heap) и алгоритмов GC является ведущей причиной аварийных остановок брокеров из-за Linux OOM Killer, выпадения узлов из синхронных реплик (ISR) и деградации сетевых очередей.

---

## Определения

- **JVM Heap (Куча JVM):** Область оперативной памяти процесса JVM (`-Xms`, `-Xmx`), выделяемая для размещения объектов Java-приложения: метаданных топиков и партиций, очередей запросов, сетевых буферов кадров и структур ожидания Purgatory.
- **Page Cache (Кэш страниц ОС):** Кэш виртуальной файловой системы ядра Linux в свободной оперативной памяти хоста. Kafka использует Page Cache для удержания сегментов журналов (`.log`) и индексных файлов (`.index`, `.timeindex`), выполняя чтение и запись через системные вызовы ядра минуя структуры JVM Heap.
- **Off-Heap / Direct Memory:** Память процесса за пределами JVM Heap, выделяемая под прямые буферы (`java.nio.ByteBuffer.allocateDirect()`). Применяется сетевыми процессорами Kafka для передачи сокетных данных без промежуточного копирования через кучу Java.
- **Garbage Collector (GC):** Автоматическая подсистема JVM, выполняющая отслеживание ссылок, компактификацию и очистку памяти от неиспользуемых объектов.
- **Stop-the-World (STW) Pause:** Фаза работы сборщика мусора, во время которой выполнение всех потоков приложения (`KafkaRequestHandler`, сетевые процессоры, фоновые таймеры) приостанавливается на безопасных точках (Safepoints).
- **Time-To-Safepoint (TTSP):** Интервал времени от инициации паузы GC координатором до момента, когда последний рабочий поток приложения остановится на точке безопасного останова (Safepoint).
- **G1GC (Garbage-First GC):** Поколенческий региональный сборщик мусора, принятый стандартом по умолчанию в Apache Kafka. Делит кучу на равные регионы (от 1 до 32 МБ) и в первую очередь очищает регионы с наибольшим объемом мертвого мусора.
- **ZGC (Generational ZGC):** Низколатентный масштабируемый сборщик мусора OpenJDK (поколенческий режим доступен в JDK 21+), выполняющий маркировку, перемещение и компактификацию объектов конкурентно с исполнением потоков приложения, удерживая паузы STW на уровне менее 1 миллисекунды.
- **Metaspace:** Область нативной памяти JVM для хранения метаданных классов, пулов констант и скомпилированных методов.
- **Humongous Allocations:** Выделение памяти под объекты, чей размер превышает 50% размера одного региона G1 (`G1HeapRegionSize`). Размещаются напрямую в непрерывной последовательности регионов старого поколения (Old Generation) и могут вызывать преждевременные смешанные сборки.
- **Evacuation Failure (To-space Exhaustion):** Критическая ситуация в G1GC, когда сборщик мусора во время эвакуации выживших объектов не находит свободных регионов в куче, что приводит к деградации цикла сборки до медленного однопоточного Full GC.
- **Allocation Stall:** Ситуация в конкурентных сборщиках (ZGC), когда скорость создания новых объектов потоками приложения превышает скорость очистки памяти сборщиком, из-за чего потоки Kafka блокируются в ожидании свободной памяти.
- **Native Memory Tracking (NMT):** Внутренний механизм диагностики JVM для детального аудита потребления оперативной памяти подсистемами виртуальной машины вне кучи (Metaspace, CodeCache, Thread Stacks, Direct Buffers).

---

## Архитектура памяти и принципы работы JVM в Kafka

### Модель распределения RAM на узле Kafka

Производительность Kafka-брокера критически зависит от объема доступной системной памяти для ядра Linux, а не от гигантского размера JVM Heap. Процесс Kafka разделяет память физического хоста или виртуальной машины на четыре основных сегмента:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                          Общая оперативная память сервера (RAM)                             │
├────────────────────────────────┬────────────────────────────────────────────────────────────┤
│         Процесс JVM            │                    Операционная система Linux              │
├───────────────┬────────────────┼───────────────────────────────────────────┬────────────────┤
│   JVM Heap    │  Off-Heap /    │                Page Cache                 │  Ядро и службы │
│   (-Xms/-Xmx) │  Native Memory │          (60–75% всей памяти хоста)       │    системы     │
│   (4–8 ГБ)    │   (2–4 ГБ)     │                                           │   (2–4 ГБ)     │
├───────────────┼────────────────┼───────────────────────────────────────────┼────────────────┤
│ - Метаданные  │ - Direct       │ - Горячие сегменты данных (*.log)         │ - systemd      │
│   топиков     │   ByteBuffers  │ - Индексы смещений (*.index)              │ - Сетевые      │
│ - RequestQueue│   (сетевой I/O)│ - Временные индексы (*.timeindex)         │   буферы TCP   │
│ - Purgatory   │ - Metaspace    │ - Буферы чтения репликации                │ - Мониторинг   │
│ - Кэш записей │ - Стек потоков │ - Отправка клиентам через sendfile(2)     │   (Node        │
│   контроллера │   (-Xss1m)     │   (Zero-Copy I/O)                         │    Exporter)   │
│ - Объекты     │ - CodeCache    │                                           │                │
│   метрик JMX  │ - glibc malloc │                                           │                │
└───────────────┴────────────────┴───────────────────────────────────────────┴────────────────┘
```

### Почему Kafka не нужен большой Heap

В архитектуре большинства enterprise-приложений на Java кэш данных организуется внутри кучи приложения. В Apache Kafka архитектурное решение принципиально противоположное:

1. **Издержки на заголовки объектов Java:** Любой объект в JVM на 64-битной архитектуре имеет заголовок (Object Header) размером 12–16 байт, а выравнивание адресов увеличивает накладные расходы. Хранение сотен гигабайт сообщений в куче удвоило бы потребление памяти по сравнению с бинарными байтами на диске.
2. **Паузы Stop-the-World:** Чем больше размер кучи G1GC (16–64 ГБ и более), тем выше время на сканирование графа ссылок, обновление таблиц Remembered Sets (RSet) и эвакуацию объектов. Всплески STW-пауз до сотен миллисекунд приводят к нарушению heartbeat-таймаутов и развалу кворума.
3. **Zero-Copy передача через `sendfile(2)`:** При передаче записей сетевым клиентам данные читаются из дискового Page Cache напрямую в сетевой сокет Linux через системный вызов `sendfile(2)` (в Java — `FileChannel.transferTo()`). Байты сообщений вообще не загружаются в адресное пространство JVM Heap.
4. **Устойчивость к перезапускам процесса (Warm Cache):** При падении или перезапуске процесса JVM весь Page Cache остается валидным в оперативной памяти ядра Linux. Перезапущенный брокер сразу готов обслуживать запросы с минимальной задержкой дискового ввода-вывода.

### Рекомендации по размеру Heap по типам узлов

| Роль узла | Рекомендуемый Heap (`-Xms`/`-Xmx`) | Page Cache / Окружение | Назначение и специфика нагрузки |
|---|---|---|---|
| **KRaft Controller (Dedicated)** | `2G` – `4G` | 8–16 ГБ RAM на узел | Узел изолированного кворума метаданных. Не обслуживает клиентский трафик данных, хранит лог метаданных `@metadata` в памяти. |
| **Kafka Broker (Стандартный)** | `6G` – `8G` | 40–56 ГБ (при 64 ГБ RAM) | Стандартный рабочий узел: до 3000–4000 разделов, трафик до 100–300 МБ/с. Оптимальный баланс для G1GC. |
| **Kafka Broker (High Throughput)** | `8G` (максимум `10G`) | 100–240 ГБ (при 128–256 ГБ RAM) | Плотность более 5000 разделов, высокий параллелизм fetch-запросов и Purgatory. Heap свыше 10 ГБ не рекомендуется. |
| **Kafka Connect Worker** | `4G` – `8G` | 16–32 ГБ RAM на узел | Обработка буферов сериализации/десериализации коннекторов и задач трансформации (SMT). |

### Сравнение сборщиков мусора: G1GC vs Generational ZGC

| Критерий | G1GC (OpenJDK 17 / 21) | Generational ZGC (OpenJDK 21 LTS) |
|---|---|---|
| **Статус в Apache Kafka** | Проверенный production-стандарт по умолчанию | Рекомендован для SLA с ультра-низкой задержкой (Low-Latency) |
| **Паузы Stop-the-World** | 10–50 мс (в зависимости от `MaxGCPauseMillis`) | < 1 мс (обычно 0.2–0.5 мс независимо от объема кучи) |
| **Накладные расходы CPU** | Умеренные (3–5% процессорного времени) | Повышенные (на 5–12% выше из-за барьеров памяти Load Barriers) |
| **Требования к объему Heap** | Эффективно работает при 4–8 ГБ | Требует запас по памяти (от 8–12 ГБ), чтобы исключить Allocation Stalls |
| **Устойчивость к пиковым всплескам** | Высокая (регулируется `G1ReservePercent`) | Чувствителен к темпу аллокации (Allocation Rate) при нехватке ядер CPU |
| **Поддерживаемые платформы** | Linux x86_64, AArch64 | Linux x86_64, AArch64 (требуется ядро Linux 5.10+) |

---

## Конфигурация и практические сценарии тюнинга

Управление параметрами JVM брокера Kafka осуществляется через переменные окружения в конфигурационном файле сервиса (`/etc/default/kafka` или файл шаблона systemd):
- `KAFKA_HEAP_OPTS`: Базовые лимиты размера кучи (`-Xms`, `-Xmx`). Всегда задаются одинаковыми для исключения задержек на динамическое выделение памяти у ядра ОС.
- `KAFKA_JVM_PERFORMANCE_OPTS`: Флаги выбора сборщика мусора, тюнинга регионов, safepoint-диагностики и оптимизации компилятора.
- `KAFKA_GC_LOG_OPTS`: Параметры унифицированного логирования GC (Unified JVM GC Logging, JEP 271).
- `EXTRA_ARGS`: Дополнительные флаги виртуальной машины, параметры JMX и Java-агентов мониторинга.

### Сценарий 1: Базовая производственная конфигурация G1GC (Bare-Metal / VM)

Конфигурационный файл `/etc/default/kafka` для брокера с 64–128 ГБ оперативной памяти под управлением OpenJDK 17 или 21:

```bash
# Ограничения памяти JVM Heap
export KAFKA_HEAP_OPTS="-Xms6g -Xmx6g"

# Параметры оптимизации сборщика мусора G1GC
export KAFKA_JVM_PERFORMANCE_OPTS="
  -server
  -XX:+UseG1GC
  -XX:MaxGCPauseMillis=20
  -XX:InitiatingHeapOccupancyPercent=35
  -XX:G1ReservePercent=15
  -XX:G1HeapRegionSize=16M
  -XX:G1MixedGCCountTarget=8
  -XX:G1ConfidencePercent=85
  -XX:+ExplicitGCInvokesConcurrent
  -XX:+AlwaysPreTouch
  -XX:MaxDirectMemorySize=4g
  -XX:MetaspaceSize=256m
  -XX:MaxMetaspaceSize=512m
  -XX:+UnlockDiagnosticVMOptions
  -XX:+DebugNonSafepoints
  -XX:+HeapDumpOnOutOfMemoryError
  -XX:HeapDumpPath=/var/log/kafka/kafka_oom.hprof
  -XX:+ExitOnOutOfMemoryError
  -Djava.awt.headless=true
"

# Унифицированное логирование GC (OpenJDK 17/21)
export KAFKA_GC_LOG_OPTS="-Xlog:gc*,gc+phases=debug:file=/var/log/kafka/kafkaServer-gc.log:time,uptime,pid:filecount=10,filesize=100M"
```

**Разбор ключевых флагов:**
- `-XX:+AlwaysPreTouch`: При старте JVM выполняет запись нулей во все страницы выделенного heap, принуждая ядро Linux выделить реальные физические фреймы оперативной памяти (page table commit). Исключает page fault задержки в процессе обслуживания пользовательских запросов.
- `-XX:MaxGCPauseMillis=20`: Директива эвристике G1 стремиться к паузам не выше 20 мс. Установка значения ниже 10 мс не рекомендуется, так как сборщик не успеет эвакуировать молодые поколения и начнет расширять паузы.
- `-XX:InitiatingHeapOccupancyPercent=35`: Снижение порога запуска фазы конкурентной маркировки (дефолт в JDK 17 — 45%). Ранний старт предотвращает переход в аварийный режим эвакуации при резком всплеске трафика.
- `-XX:G1ReservePercent=15`: Увеличивает резервный пул свободных регионов с 10% до 15% для снижения риска `to-space exhausted`.
- `-XX:G1HeapRegionSize=16M`: Размер региона в 16 МБ предотвращает классификацию крупных сетевых пакетов (до 8 МБ) как Humongous-объектов.
- `-XX:MaxDirectMemorySize=4g`: Фиксирует жесткий лимит на выделение прямой памяти подсистемы NIO, защищая хост от бесконтрольного роста Off-Heap и OOM Killer ядра.
- `-XX:+ExitOnOutOfMemoryError`: При возникновении фатальной ошибки памяти брокер немедленно завершает работу, передавая лидерство партиций репликам, вместо зависания в частично неработоспособном «зомби»-состоянии.

### Сценарий 2: Конфигурация для выделенного KRaft Controller узла

Узлы кворума метаданных KRaft не обслуживают пользовательские потоки сообщений и дисковые сегменты топиков данных, однако они поддерживают реплицированный журнал `@metadata` и генерируют снимки (snapshots):

```bash
# Конфигурация для /etc/default/kafka-controller
export KAFKA_HEAP_OPTS="-Xms4g -Xmx4g"

export KAFKA_JVM_PERFORMANCE_OPTS="
  -server
  -XX:+UseG1GC
  -XX:MaxGCPauseMillis=15
  -XX:InitiatingHeapOccupancyPercent=40
  -XX:G1HeapRegionSize=8M
  -XX:+AlwaysPreTouch
  -XX:MaxDirectMemorySize=1g
  -XX:MetaspaceSize=128m
  -XX:MaxMetaspaceSize=256m
  -XX:+HeapDumpOnOutOfMemoryError
  -XX:HeapDumpPath=/var/log/kafka/kafka_controller_oom.hprof
  -XX:+ExitOnOutOfMemoryError
  -Djava.awt.headless=true
"

export KAFKA_GC_LOG_OPTS="-Xlog:gc*:file=/var/log/kafka/kafkaController-gc.log:time,uptime,pid:filecount=5,filesize=50M"
```

### Сценарий 3: Миграция на Generational ZGC для критичных к задержкам сервисов (OpenJDK 21 LTS)

При строгих требованиях SLA к задержкам (p99 / p99.9 < 5 мс) на узлах под управлением Java 21 LTS рекомендуется переход на поколенческий ZGC:

```bash
# Проверка версии Java перед запуском
java -version
# → openjdk version "21.0.4" 2024-07-16 LTS
# → OpenJDK Runtime Environment (build 21.0.4+7-LTS)
# → OpenJDK 64-Bit Server VM (build 21.0.4+7-LTS, mixed mode, sharing)

# Параметры в /etc/default/kafka
export KAFKA_HEAP_OPTS="-Xms8g -Xmx8g"

export KAFKA_JVM_PERFORMANCE_OPTS="
  -server
  -XX:+UseZGC
  -XX:+ZGenerational
  -XX:+AlwaysPreTouch
  -XX:SoftMaxHeapSize=8g
  -XX:MaxDirectMemorySize=4g
  -XX:MetaspaceSize=256m
  -XX:MaxMetaspaceSize=512m
  -XX:+UnlockDiagnosticVMOptions
  -XX:+DebugNonSafepoints
  -XX:+HeapDumpOnOutOfMemoryError
  -XX:HeapDumpPath=/var/log/kafka/kafka_oom.hprof
  -XX:+ExitOnOutOfMemoryError
  -Djava.awt.headless=true
"

export KAFKA_GC_LOG_OPTS="-Xlog:gc*:file=/var/log/kafka/kafkaServer-gc.log:time,uptime,pid:filecount=10,filesize=100M"
```

> [!WARNING]
> ZGC не использует флаги `MaxGCPauseMillis`, `InitiatingHeapOccupancyPercent` и `G1HeapRegionSize`. Их указание приведет к предупреждениям в логе старта JVM. ZGC требует резерв производительности CPU (не менее 4–8 свободных ядер) для эффективной конкурентной сборки мусора в фоновых потоках.

### Сценарий 4: Настройка параметров памяти для контейнеризированных сред (Docker / Podman)

При развертывании брокеров внутри контейнеров cgroups (v1/v2) ядро Linux учитывает общее потребление памяти процессом (Heap + Off-Heap + Page Cache). Если суммарное потребление превышает установленный лимит контейнера, процесс уничтожается сигналом `SIGKILL` (код завершения 137).

**Формула расчета лимитов контейнера:**
$$\text{Memory Limit} \ge \text{Heap} + \text{MaxDirectMemorySize} + \text{Metaspace} + (\text{Потоки} \times \text{Xss}) + \text{Page Cache Буфер}$$

Пример рабочего файла `docker-compose.yml`:

```yaml
services:
  kafka-broker:
    image: apache/kafka:3.9.0
    container_name: kafka-broker
    restart: unless-stopped
    network_mode: host
    environment:
      # JVM выделяет 6 ГБ под Heap
      KAFKA_HEAP_OPTS: "-Xms6g -Xmx6g"
      KAFKA_JVM_PERFORMANCE_OPTS: >-
        -XX:+UseG1GC
        -XX:MaxGCPauseMillis=20
        -XX:InitiatingHeapOccupancyPercent=35
        -XX:G1ReservePercent=15
        -XX:G1HeapRegionSize=16M
        -XX:MaxDirectMemorySize=2g
        -XX:MetaspaceSize=256m
        -XX:MaxMetaspaceSize=512m
        -XX:+AlwaysPreTouch
        -XX:+ExitOnOutOfMemoryError
      KAFKA_GC_LOG_OPTS: "-Xlog:gc*:file=/var/log/kafka/kafkaServer-gc.log:time,uptime,pid:filecount=5,filesize=50M"
      KAFKA_NODE_ID: "1"
      KAFKA_PROCESS_ROLES: "broker"
    volumes:
      - /var/lib/kafka/data:/var/lib/kafka/data
      - /var/log/kafka:/var/log/kafka
    deploy:
      resources:
        limits:
          # Лимит контейнера: 6G Heap + 2G Direct + 0.5G Meta + 7.5G Page Cache = 16G
          memory: 16Gi
          cpus: '8.0'
        reservations:
          memory: 16Gi
          cpus: '4.0'
```

### Сценарий 5: Интеграция службы с Systemd на production-хосте

Юнит `/etc/systemd/system/kafka.service` с изоляцией окружения, лимитами дескрипторов и управлением памятью:

```ini
[Unit]
Description=Apache Kafka Distributed Message Broker
Documentation=https://kafka.apache.org/documentation/
After=network.target network-online.target systemd-sysctl.service
Wants=network-online.target

[Service]
Type=simple
User=kafka
Group=kafka
EnvironmentFile=-/etc/default/kafka
ExecStart=/opt/kafka/bin/kafka-server-start.sh /etc/kafka/server.properties
ExecStop=/opt/kafka/bin/kafka-server-stop.sh

Restart=on-failure
RestartSec=10s
TimeoutStopSec=120s
KillMode=control-group

# Системные лимиты для предотвращения OOM и блокировок
LimitNOFILE=1000000
LimitNPROC=65536
LimitMEMLOCK=infinity
TasksMax=infinity

[Install]
WantedBy=multi-user.target
```

Применение и валидация статуса службы:

```bash
sudo systemctl daemon-reload
# → (успешное применение изменений конфигурации)

sudo systemctl restart kafka.service
# → (перезапуск процесса брокера)

sudo systemctl status kafka.service
# → ● kafka.service - Apache Kafka Distributed Message Broker
# →      Loaded: loaded (/etc/systemd/system/kafka.service; enabled; preset: enabled)
# →      Active: active (running) since Mon 2026-10-12 14:00:00 UTC; 15s ago
# →    Main PID: 42105 (java)
# →       Tasks: 184 (limit: infinity)
# →      Memory: 7.2G (peak: 7.4G)
# →         CPU: 18.210s
# →      CGroup: /system.slice/kafka.service
# →              └─42105 /usr/lib/jvm/java-17-openjdk/bin/java -Xms6g -Xmx6g ...
```

---

## Эксплуатация и команды диагностики

### 1. Мониторинг утилизации памяти и фаз GC через `jstat`

Утилита `jstat` позволяет в режиме реального времени отслеживать процентное заполнение областей памяти и длительность сборок:

```bash
# Получение PID процесса Kafka
KAFKA_PID=$(pgrep -f "kafka.Kafka")
echo $KAFKA_PID
# → 42105

# Мониторинг утилизации сегментов (интервал 1 секунда, 5 выборок)
jstat -gcutil $KAFKA_PID 1000 5
# →   S0     S1     E      O      M     CCS    YGC     YGCT    FGC    FGCT    CGC    CGCT     GCT   
# →   0.00 100.00  34.50  42.10  96.40  92.10     84    1.250     0    0.000    12    0.180    1.430
# →   0.00 100.00  68.20  42.10  96.40  92.10     84    1.250     0    0.000    12    0.180    1.430
# → 100.00   0.00  12.10  44.80  96.40  92.10     85    1.265     0    0.000    12    0.180    1.445
# → 100.00   0.00  45.30  44.80  96.40  92.10     85    1.265     0    0.000    12    0.180    1.445
# → 100.00   0.00  81.00  44.80  96.40  92.10     85    1.265     0    0.000    12    0.180    1.445
```

**Интерпретация колонок:**
- `S0`, `S1`: Процент заполнения пространств Survivor.
- `E`: Процент заполнения пространства Eden (молодое поколение).
- `O`: Процент заполнения Old Generation (старое поколение). Рост `O` выше 80% после сборок указывает на утечку памяти.
- `M`: Процент заполнения Metaspace.
- `YGC` / `YGCT`: Количество сборок молодого поколения и суммарное затраченное время в секундах.
- `FGC` / `FGCT`: Количество пауз Full GC и суммарное время. В стабильном кластере значение `FGC` строго равно `0`.
- `CGC` / `CGCT`: Количество циклов конкурентной маркировки (Concurrent GC) и их время.

### 2. Проверка состояния памяти через `jcmd`

Утилита `jcmd` выполняет безопасные низкоуровневые диагностические запросы к работающей JVM:

```bash
# Получение сводной информации о регионах кучи
jcmd $KAFKA_PID GC.heap_info
# → 42105:
# →  garbage-first heap   total 6291456K, used 2842104K [0x0000000640000000, 0x00000007c0000000)
# →   region size 16384K, 35 young (573440K), 2 survivors (32768K)
# →  Metaspace       used 68420K, committed 70208K, reserved 1048576K
# →   class space    used 8120K, committed 8512K, reserved 1048576K

# Просмотр реально примененных флагов JVM в рантайме
jcmd $KAFKA_PID VM.flags -all | grep -E "UseG1GC|MaxGCPauseMillis|InitiatingHeapOccupancyPercent|AlwaysPreTouch"
# → -XX:+AlwaysPreTouch=true
# → -XX:G1HeapRegionSize=16777216
# → -XX:InitiatingHeapOccupancyPercent=35
# → -XX:MaxGCPauseMillis=20
# → -XX:+UseG1GC=true
```

### 3. Аудит Native Memory Tracking (NMT)

Для расследования утечек нативной памяти (Off-Heap, потоки, прямые буферы):

1. Включите отслеживание флагом в `KAFKA_JVM_PERFORMANCE_OPTS`: `-XX:NativeMemoryTracking=summary`.
2. Выполните запрос отчета через `jcmd`:

```bash
jcmd $KAFKA_PID VM.native_memory summary
# → 42105:
# → Native Memory Tracking:
# → Total: reserved=9124152KB, committed=7421840KB
# → -                 Java Heap (reserved=6291456KB, committed=6291456KB)
# →                             (mmap: reserved=6291456KB, committed=6291456KB)
# → -                    Class (reserved=1084210KB, committed=78210KB)
# →                             (classes #14210)
# →                             (malloc=4210KB #24510)
# →                             (mmap: reserved=1080000KB, committed=74000KB)
# → -                   Thread (reserved=210420KB, committed=210420KB)
# →                             (thread #204)
# →                             (stack: reserved=209420KB, committed=209420KB)
# → -            Internal/Other (reserved=512400KB, committed=512400KB)
```

### 4. Парсинг и анализ унифицированного лога GC

Быстрый поиск критических пауз в файле `/var/log/kafka/kafkaServer-gc.log`:

```bash
# Поиск пауз эвакуации, превышающих 50 миллисекунд
grep "Pause Young" /var/log/kafka/kafkaServer-gc.log | awk -F' ' '{for(i=1;i<=NF;i++) if($i ~ /ms/) {val=$(i-1); if(val>50) print $0}}' | tail -n 5
# → [2026-10-12T14:15:22.410+0000][124.512s][info][gc] GC(142) Pause Young (Normal) (G1 Evacuation Pause) 2814M->1240M(6144M) 54.120ms

# Поиск признаков деградации до Full GC или отказов эвакуации
grep -E "Full GC|to-space exhausted|Allocation Stall" /var/log/kafka/kafkaServer-gc.log
# → (пустой вывод подтверждает отсутствие деградации и отказов эвакуации)
```

---

## Устранение неисправностей (Troubleshooting)

### Сводная матрица типовых неисправностей JVM и GC

| Симптом / Ошибка | Первопричина | Метод верификации | Способ устранения |
|---|---|---|---|
| **В логах GC запись `to-space exhausted` (Evacuation Failure)** | Нехватка свободных регионов для перемещения выживших объектов во время фазы эвакуации | `grep "to-space exhausted" /var/log/kafka/kafkaServer-gc.log` | 1. Увеличить `-XX:G1ReservePercent` до 15–20%.<br>2. Снизить `-XX:InitiatingHeapOccupancyPercent` до 30–35%.<br>3. Увеличить Heap до 8G. |
| **Всплеск `Pause Young (Concurrent Start)` и падение пропускной способности** | Массовое выделение крупных объектов (Humongous Allocations) размером > 50% региона | Проверить флаг `gc+alloc=debug` в логе на наличие записей `G1 Humongous Allocation` | Увеличить размер региона: `-XX:G1HeapRegionSize=16M` или `32M`. Проверить продюсеры на `max.message.bytes`. |
| **Выпадение брокера из кворума / ISR (Disconnect heartbeat)** | STW-пауза GC превысила таймаут сессии (`session.timeout.ms` или `controller.quorum.fetch.timeout.ms`) | Сопоставить таймштампы отключения в `server.log` с длительностью паузы в `kafkaServer-gc.log` | 1. Тюнинг G1GC (снижение `MaxGCPauseMillis`).<br>2. Увеличение таймаутов сессии в конфигурации.<br>3. Рассмотреть переход на Generational ZGC. |
| **Процесс завершается с кодом 137 (OOMKilled)** | Linux OOM Killer уничтожил JVM из-за превышения суммарного лимита cgroups хоста/контейнера | `dmesg -T \| grep -i "killed process.*java"` или проверка `systemctl status kafka` | 1. Задать жесткий лимит `-XX:MaxDirectMemorySize=2g`.<br>2. Выделить контейнеру RAM с запасом $\ge 1.5 \times \text{Heap}$. |
| **`java.lang.OutOfMemoryError: Metaspace`** | Утечка загрузчиков классов из-за динамической загрузки коннекторов или скриптов SMT | `jcmd $PID VM.class_loaders` или `jstat -gcutil $PID` (колонка `M` равна 100%) | 1. Установить `-XX:MaxMetaspaceSize=512m`.<br>2. Локализовать проблемный коннектор в Kafka Connect. |
| **`Allocation Stall` в логах ZGC** | Скорость генерации сообщений превышает производительность параллельной очистки ZGC | `grep "Allocation Stall" /var/log/kafka/kafkaServer-gc.log` | 1. Выделить процессу дополнительные CPU-ядра.<br>2. Увеличить кучу с 8G до 10–12G. |

### Диагностический сценарий: Расследование аварийного завершения брокера Linux OOM Killer (код 137)

#### Шаг 1. Проверка системных журналов ядра

```bash
sudo dmesg -T | grep -E -i "oom[-_]killer|killed process" | tail -n 5
# → [Mon Oct 12 14:20:10 2026] Out of memory: Killed process 42105 (java) total-vm:14820140kB, anon-rss:8120440kB, file-rss:4100kB, shmem-rss:0kB, UID:1001 pgtables:18204kB oom_score_adj:0
```

#### Шаг 2. Анализ причин нехватки памяти

Процесс `java` потребил 8.1 ГБ анонимной памяти (RSS) при лимите `-Xmx6g`. Причина: неконтролируемый рост прямых сетевых буферов (Direct ByteBuffers) и стеков потоков при отсутствии директивы `-XX:MaxDirectMemorySize`.

#### Шаг 3. Решение проблемы

1. Отредактируйте `/etc/default/kafka`, явно ограничив прямую память и стек:
   ```bash
   export KAFKA_JVM_PERFORMANCE_OPTS="$KAFKA_JVM_PERFORMANCE_OPTS -XX:MaxDirectMemorySize=2g -Xss1m"
   ```
2. Проверьте параметр ядра `vm.overcommit_memory`:
   ```bash
   sysctl vm.overcommit_memory
   # → vm.overcommit_memory = 0
   ```
3. Перезапустите службу брокера:
   ```bash
   sudo systemctl restart kafka.service
   # → (служба успешно перезапущена)
   ```

---

## Рекомендации и Best Practices

### Архитектурные правила управления памятью (DevOps / SRE)

1. **Никогда не выделяйте брокеру кучу свыше 8–10 ГБ:**
   Большой размер Heap не ускоряет обработку сообщений. Лишняя память должна отдаваться дисковому Page Cache ядра Linux.
2. **Всегда фиксируйте одинаковые значения `-Xms` и `-Xmx`:**
   Динамическое расширение кучи во время производственной нагрузки вызывает блокировки потоков аллокации и провоцирует всплески задержек.
3. **Всегда включайте `-XX:+AlwaysPreTouch` в production:**
   Инициализация физических страниц памяти при старте сервиса предотвращает накладные расходы ядра на обработку soft page faults в моменты пикового трафика.
4. **Всегда задавайте `-XX:+ExitOnOutOfMemoryError`:**
   В распределенных кластерах брокер, столкнувшийся с OOM, должен немедленно упасть. Попытка продолжить работу приводит к повреждению кэша метаданных и «зависанию» клиентских запросов.
5. **Всегда ограничивайте `-XX:MaxDirectMemorySize`:**
   По умолчанию лимит прямой памяти в JVM равен размеру кучи `-Xmx`. На брокере с `-Xmx8g` процесс может занять 8 ГБ Heap + 8 ГБ Direct Memory = 16 ГБ, что приведет к OOM-падению хоста.
6. **Отключайте Transparent Huge Pages (THP) на уровне ОС:**
   Механизм THP дефрагментирует память ядра в фоновом режиме, вызывая кратковременные системные блокировки (I/O latency spikes), ошибочно принимаемые за проблемы JVM:
   ```bash
   cat /sys/kernel/mm/transparent_hugepage/enabled
   # → [never] madvise always
   ```
7. **Устанавливайте системный параметр `vm.swappiness=1`:**
   Защищает Page Cache и страницы процесса Kafka от выгрузки в раздел подкачки (swap) при сохранении аварийного механизма swap для экстренных ситуаций.

### Ключевые JMX-метрики для мониторинга и алертинга

Для экспорта метрик в Prometheus используется `jmx_prometheus_javaagent` (версии 1.0.x), подключаемый через переменную `EXTRA_ARGS`:

```bash
export EXTRA_ARGS="-javaagent:/opt/kafka/libs/jmx_prometheus_javaagent-1.0.1.jar=9102:/etc/kafka/jmx-exporter.yaml"
```

| MBean имя / Имя метрики в Prometheus | Нормальное значение | Порог предупреждения (Warning) | Порог аварии (Critical) | Описание метрики |
|---|---|---|---|---|
| `jvm_gc_collection_seconds_sum{gc="G1 Young Generation"}` | Рост $\le 1$ с/мин | Рост $> 5$ с/мин | Рост $> 15$ с/мин | Суммарное время, затраченное на сборку молодого поколения. |
| `jvm_gc_collection_seconds_max{gc="G1 Old Generation"}` | `0` | $> 0.1$ с | $> 0.5$ с | Максимальная длительность фазы Full GC. Любое значение $> 0$ требует расследования. |
| `jvm_memory_bytes_used{area="heap"} / jvm_memory_bytes_max` | $0.3 - 0.6$ | $> 0.75$ | $> 0.85$ | Относительное заполнение кучи после завершения циклов сборки. |
| `jvm_buffer_pool_used_bytes{pool="direct"}` | $< 2$ ГБ | $> 3$ ГБ | $> 3.8$ ГБ (при лимите 4G) | Объем выделенной прямой памяти (Direct Memory) для сокетных каналов NIO. |

---

## Связанные материалы

- **[OS тюнинг для Apache Kafka](./kafka_os_tuning.md)** — параметры ядра Linux (`vm.swappiness`, `vm.dirty_ratio`, отключение THP, оптимизация дисковых планировщиков и файловых систем XFS).
- **[Thread Model брокера Apache Kafka](./kafka_broker_thread_model.md)** — архитектура пулов потоков (`num.network.threads`, `num.io.threads`), обработка очередей `RequestQueue` и Purgatory.
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — настройка JMX Exporter, Prometheus алерты по времени пауз GC и утилизации кучи.
- **[Развертывание кластера через Ansible](./kafka_ansible_deployment.md)** — автоматизация развертывания параметров `KAFKA_JVM_PERFORMANCE_OPTS` и systemd-сервисов.
- **[Capacity Planning и Disaster Recovery](./kafka_capacity_dr.md)** — расчет требований к оперативной памяти и дисковой подсистеме кластера.
- **[Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md)** — алгоритмы диагностики деградации очередей, отставания реплик и зависаний брокеров.

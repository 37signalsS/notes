# Управление и тюнинг Java (JVM) в Linux

## Определения

*   **JVM (Java Virtual Machine):** Изолированная среда исполнения байт-кода, управляющая памятью, потоками и взаимодействием с ОС.
*   **JDK (Java Development Kit):** Полный инструментарий разработчика. Включает компилятор (`javac`), среду рантайма и инструменты диагностики (`jcmd`, `jdb`, `jstack`, `jmap`).
*   **JRE (Java Runtime Environment):** Минимальный набор для запуска приложений. В современных версиях (Java 11+) заменен модульными сборками, создаваемыми через `jlink`.
*   **Куча (Heap):** Основная область памяти для объектов. Делится на Young Generation (Eden + Survivor) и Old Generation.
*   **Сжатые указатели (Compressed OOPs):** Техника экономии RAM (использование 32-битных указателей на 64-битных системах). Эффективна при Heap **до ~31.5 ГБ**. Превышение лимита отключает оптимизацию, увеличивая потребление памяти на 20-30%.
*   **Virtual Threads (Java 21+):** Легковесные потоки (Project Loom), работающие поверх ограниченного пула системных потоков (Carrier Threads). Позволяют масштабировать приложения до миллионов конкурентных запросов.
*   **Class Data Sharing (CDS):** Механизм ускорения старта путем создания архива `.jsa` с предварительно загруженными метаданными классов.
*   **GraalVM Native Image:** Технология AOT-компиляции (Ahead-Of-Time) в нативный бинарный файл. Обеспечивает мгновенный старт и низкое потребление RAM ценой отсутствия динамического JIT-тюнинга.
*   **JFR (Java Flight Recorder):** Встроенный низкооюерходный профайлер (Java 11+). Записывает события (GC, методы, блокировки, Thread Dumps) в файл `.jfr` для последующего анализа в JDK Mission Control (JMC).
*   **JMX (Java Management Extensions):** Механизм мониторинга и управления JVM в runtime через MBean-сервер. Позволяет получать метрики (память, потоки, GC) и изменять параметры без перезапуска.
*   **Safepoint:** Точка в выполнении потока, где JVM может безопасно остановить все потоки для операций типа GC, JIT-компиляции или деоптимизации. Рост времени safepoint приводит к паузам, не связанным напрямую с GC.
*   **Biased Locking:** Оптимизация JVM, снижающая overhead синхронизации для неконкурентных объектов. В Java 15+ отключен по умолчанию из-за накладных расходов на размотку (revocation) при переходе к реальной конкуренции.
*   **Arthas:** Инструмент онлайн-диагностики Java-приложений. Позволяет отслеживать вызовы методов, анализировать память, получать дампы потоков и перезагружать классы без перезапуска JVM.

## Основные концепции

### Версионирование и байт-код

Версия байт-кода (`class file version`) определяет совместимость. Попытка запустить новый байт-код на старой JRE вызывает `UnsupportedClassVersionError`.

| Версия Java | Major version | Статус (2025/2026) | Рекомендация |
| :--- | :--- | :--- | :--- |
| 8 | 52 | Legacy | Миграция обязательна |
| 11 | 55 | Old LTS | Поддержка на исходе |
| 17 | 61 | Stable LTS | Стандарт для многих Enterprise проектов |
| 21 | 65 | Modern LTS | **Основной выбор для новых проектов** |
| 23/24 | 67/68 | Feature | Для тестирования новых фич (Vector API и т.д.) |
| 25 | 69 | Next LTS | Подготовка к переходу (Compact Headers) |

### Структура памяти (Non-Heap)

Потребление памяти процессом (`RSS`) = `Heap` + `Non-Heap`.
1.  **Metaspace:** Метаданные классов (заменил PermGen в Java 8). Не лимитирован по умолчанию, рекомендуется `-XX:MaxMetaspaceSize`. Рост без ограничения приводит к `OutOfMemoryError: Metaspace`.
2.  **Code Cache:** Память для кода, оптимизированного JIT-компилятором. При заполнении (`CodeHeap 'non-nmethods'` или `'non-profiled nmethods'`) JIT перестает компилировать код, что деградирует производительность. Размер по умолчанию: 240 МБ (Java 8+).
3.  **Compressed Class Space:** Область для указателей на классы (включен при `-XX:+UseCompressedClassPointers`). Размер ограничен 3 ГБ (в отличие от Metaspace).
4.  **Thread Stacks:** Память под каждый поток. По умолчанию ~1 МБ. *Важно:* Virtual Threads хранят свои стэки в Heap, снижая давление на системную память. Лимит на количество потоков регулируется через `ulimit -u` (max user processes).
5.  **Direct Memory:** Используется NIO (например, в Netty, Kafka). Лимитируется через `-XX:MaxDirectMemorySize`. Если не задан, по умолчанию равен `-Xmx`. Выделяется вне управления GC, но учитывается в RSS.

### Контейнеризация и Container Awareness

JVM 10+ (и бэкпорты в 8u) умеет читать лимиты `cgroups` (CPU и RAM).

*   **RAM Awareness:** Если не задать `-Xmx`, JVM выделит ~25% от лимита памяти контейнера (MaxRAMPercentage).
*   **CPU Awareness:** JVM определяет количество ядер для Garbage Collector и ForkJoinPool на основе лимитов (CPU Quota).
*   **Троттлинг:** Если лимит CPU (например, 2 ядра) намного меньше количества ядер хоста (например, 64), JVM может запустить слишком много потоков GC, что приведет к жесткому троттлингу со стороны ядра Linux.
*   **Решение (Java 19+):** `-XX:PreferContainerQuotaForCPUCount=true` (активен по умолчанию) для более точного расчета ядер.
*   **cgroups v2:** Начиная с Java 12+, JVM поддерживает унифицированную иерархию cgroups v2. JVM читает `memory.max` и `cpu.max` напрямую из `/sys/fs/cgroup`. В средах с cgroups v2 (Ubuntu 22.04+, RHEL 9+, Kubernetes 1.25+) container awareness работает корректно без дополнительных флагов.
*   **Pressure Stall Information (PSI):** JVM не читает PSI напрямую, но SRE может коррелировать GC-паузы с давлением на CPU/Memory через `/proc/pressure/`. Рост `some` или `full` на CPU одновременно с GC Thrashing указывает на ресурсный contention на уровне узла.

### OS-интеграция и systemd

Стабильная работа Java-сервиса на Linux требует корректной настройки лимитов ОС и systemd-юнита.

**Лимиты процессов (ulimit):**
```bash
# Проверка текущих лимитов для процесса
cat /proc/<PID>/limits | grep -E "Max open files|Max processes"

# Ключевые лимиты для Java:
# - nofile (open files): 65536+ (сеть, файлы, сокеты)
# - nproc (max user processes): 65536+ (много потоков, Virtual Threads)
# - memlock: unlimited (если используется libmemcached или аналогичные)
```

**systemd-юнит для Java-сервиса:**
```ini
# /etc/systemd/system/java-app.service
[Unit]
Description=Java Application
After=network.target

[Service]
Type=simple
User=appuser
Group=appgroup
WorkingDirectory=/opt/java-app

# JVM-флаги (через переменную окружения или аргументы)
Environment="JAVA_OPTS=-XX:+UseG1GC -XX:MaxRAMPercentage=75.0 -XX:+ExitOnOutOfMemoryError"
ExecStart=/usr/bin/java $JAVA_OPTS -jar app.jar

# Graceful shutdown
TimeoutStopSec=30
KillSignal=SIGTERM
SendSIGKILL=no

# Лимиты
LimitNOFILE=65536
LimitNPROC=65536

# Авто-перезапуск
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Transparent Huge Pages (THP):**
THP может вызывать latency spikes при GC из-за fragmentation. Для production-серверов отключайте:
```bash
# Проверка текущего режима
cat /sys/kernel/mm/transparent_hugepage/enabled
# → [always] madvise never

# Отключение (временно)
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Постоянное отключение через systemd
# /etc/systemd/system/disable-thp.service
[Unit]
Description=Disable Transparent Huge Pages (THP)

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'

[Install]
WantedBy=multi-user.target
```

**sysctl для Java-хостинга:**
```bash
# /etc/sysctl.d/99-java-tuning.conf
# Предотвращает swap для JVM-процессов (критично для latency)
vm.swappiness = 1

# Увеличивает количество разрешенных файловых дескрипторов
fs.file-max = 100000

# Улучшает TCP-производительность для Netty/WebFlux
net.core.somaxconn = 4096
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# Применение
sysctl --system
```

## Сборщики мусора (Garbage Collectors)

### Сравнение

| GC | Стратегия | Плюсы | Минусы | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Serial GC** | Однопоточный | Минимальный оверхед | Длинные паузы (STW) | Только для однопоточных CLI-утилит и embedded |
| **Parallel GC** | Пропускная способность | Максимальный Throughput | Значительные паузы на больших Heap | Batch-обработка, ETL, наукоемкие вычисления |
| **G1GC** | Балансировка | Универсальность, предсказуемые паузы | Требует тюнинга для экстремальных SLA | Стандарт для большинства production-сервисов |
| **ZGC (Generational)** | Низкие задержки | Паузы < 1 мс при любом размере Heap | Выше потребление CPU (5-10%) | Latency-critical API, высоконагруженные микросервисы (Java 21+) |
| **Shenandoah** | Низкие задержки | Компактная куча, эффективен при большом heap | Выше потребление CPU | Альтернатива ZGC, Red Hat生态 |

### Выбор GC для production

*   **G1GC** — универсальный выбор для большинства сервисов. Подходит если P99 < 500 мс. Используйте `-XX:MaxGCPauseMillis=200` для целевого ограничения пауз.
*   **ZGC** — выбирайте для latency-critical систем, где паузы > 50 мс недопустимы. Требует Java 21+ дляgenerational ZGC. Эффективен при Heap > 16 ГБ.
*   **Shenandoah** — альтернатива ZGC в экосистеме Red Hat. Аналогичная производительность, но требует OpenJDK от Red Hat или Azul.
*   **Parallel GC** — только для фоновых задач, где throughput важнее latency.

**Важно:** При использовании ZGC/Shenandoah увеличивайте `-XX:ConcGCThreads` при наличии свободных CPU-ядер, так как конкурентные фазы потребляют дополнительно 1-2 ядра.

## Практические сценарии

### Идеальный старт в Kubernetes (Java 21+)

Рекомендуемые флаги для стабильной работы и диагностики:

```bash
java -XX:+UseContainerSupport \
     -XX:MaxRAMPercentage=75.0 \
     -XX:SoftMaxHeapSize=1G \
     -XX:+ExitOnOutOfMemoryError \
     -XX:+HeapDumpOnOutOfMemoryError \
     -XX:HeapDumpPath=/var/log/app/dumps/ \
     -Xlog:gc*:file=/var/log/app/gc.log:time,uptime:filecount=5,filesize=20M \
     -jar app.jar
```
* `# → SoftMaxHeapSize заставляет GC активнее возвращать память ОС при низкой нагрузке`
* `# → ExitOnOutOfMemoryError критичен для Kubernetes, чтобы Pod перешел в CrashLoopBackOff`

### Оптимизация запуска через CDS

Для ускорения холодного старта (актуально для Serverless и быстрого масштабирования):

```bash
# 1. Генерация архива (при выключении приложения)
java -XX:ArchiveClassesAtExit=app.jsa -jar app.jar

# 2. Запуск с использованием архива
java -XX:SharedArchiveFile=app.jsa -jar app.jar
# → Снижает время загрузки классов на 20-40%
```

### Диагностика производительности

**Проверка Container Awareness:**
```bash
jcmd <PID> VM.info | grep -i "container"
# → Выведет лимиты памяти и CPU, которые видит JVM
```

**Анализ Native Memory Leak:**
Если RSS растет, а Heap стабилен — ищите утечку в Native Memory:
```bash
# Включить трекинг (требует перезапуска)
java -XX:NativeMemoryTracking=summary -jar app.jar

# Снять отчет
jcmd <PID> VM.native_memory summary
# → Покажет расход на Thread Stacks, Code Cache, Metaspace
```

### JDK-утилиты диагностики (cheatsheet)

| Утилита | Назначение | Пример |
| :--- | :--- | :--- |
| **jcmd** | Универсальная диагностика живого процесса | `jcmd <PID> VM.flags` |
| **jinfo** | Просмотр и изменение флагов JVM | `jinfo -flags <PID>` |
| **jstat** | Статистика GC и компиляции в реальном времени | `jstat -gcutil <PID> 1000` |
| **jmap** | Дамп кучи и гистограмма объектов | `jmap -histo:live <PID> \| head -20` |
| **jstack** | Дамп потоков (thread dump) | `jstack -l <PID> > /tmp/threaddump.txt` |
| **jps** | Список Java-процессов | `jps -lmv` |

**Примеры использования:**

```bash
# Мониторинг GC в реальном времени (G1GC, ZGC)
jstat -gcutil <PID> 1000 10
# S0 S1 E O M CCS Y GC YGCT FGCT GCT
# 0.0 0.0 12.3 45.2 98.1 95.0 42 42 1.234 3 4.567

# Анализ утечки памяти (объекты в куче)
jmap -histo:live <PID> | head -20
# num #instances #bytes class name
# 1: 15000 2400000 byte[]
# 2: 5000 800000 com.example.Request

# Полный дамп кучи для offline-анализа (Eclipse MAT, JVisualVM)
jmap -dump:format=b,file=/tmp/heapdump.hprof <PID>
# → Файл можно открыть в MAT для анализа dominator tree

# Thread dump для анализа deadlock
jstack -l <PID> > /tmp/threaddump.txt
# → Ищите "Found one Java-level deadlock"

# Изменение флага без перезапуска (только для Diagnostic флагов)
jinfo -XX:+UnlockDiagnosticVMOptions <PID>
jinfo -XX:+PrintSafepointStatistics <PID>

# Просмотр всех флагов JVM
jcmd <PID> VM.flags
# → -XX:+UseG1GC -XX:MaxGCPauseMillis=200 ...
```

### JFR (Java Flight Recorder) — практические сценарии

JFR включен по умолчанию в OpenJDK 11+ и имеет оверхед < 1%.

**Запуск записи:**
```bash
# Запись на 60 секунд с настройкой profile
jcmd <PID> JFR.start name=MyRecording settings=profile duration=60s filename=/tmp/output.jfr

# Запись с кастомным размером буфера (для долгих записей)
jcmd <PID> JFR.start name=LongRunning settings=profile maxsize=200M maxage=1h filename=/tmp/output.jfr

# Остановка записи
jcmd <PID> JFR.stop name=MyRecording

# Дамп при остановке JVM
java -XX:StartFlightRecording=dumponexit=true,filename=/tmp/dump.jfr ...
```

**Анализ:**
```bash
# Просмотр информации о записи
jfr print --events GC,Pause /tmp/output.jfr | head -50

# Конвертация в CSV для анализа
jfr print --events GC /tmp/output.jfr > /tmp/gc_events.csv
```

**Критические события для мониторинга:**
*   `jdk.GarbageCollection` — паузы GC
*   `jdk.SafepointBegin` / `jdk.SafepointSynchronize` — время safepoint
*   `jdk.JavaMonitorEnter` — блокировки ( contention)
*   `jdk.ThreadPark` — park/unpark потоков
*   `jdk.CPULoad` / `jdk.JVMInformation` — системные метрики

### Arthas — онлайн-диагностика без перезапуска

Arthas позволяет выполнять диагностику в production без перезапуска и изменения кода.

**Установка и подключение:**
```bash
# Скачать arthas-boot.jar
curl -O https://arthas.aliyun.com/arthas-boot.jar

# Запуск (подключится к первому найденному Java-процессу)
java -jar arthas-boot.jar

# Или подключиться к конкретному PID
java -jar arthas-boot.jar <PID>
```

**Полезные команды:**
```bash
# Просмотр всех загруженных классов
dashboard
classloader -a

# Мониторинг метода (какие аргументы передаются, время выполнения)
trace com.example.Service processRequest

# Просмотр стека вызовов метода
stack com.example.Service processRequest

# Дамп кучи (inline)
heap dump /tmp/arthas-heap.hprof

# Просмотр JVM-флагов
vmflag

# Thread dump через Arthas
thread -b  # блокированные потоки
thread -n 3  # топ-3 по CPU
```

### JVM-логирование

Unified JVM Logging (Java 9+) позволяет настраивать вывод через единый флаг `-Xlog`:

```bash
# GC + safepoint + метаданные классов
java -Xlog:gc*:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=10,filesize=50M \
     -XX:+UnlockDiagnosticVMOptions -XX:+PrintSafepointStatistics \
     -jar app.jar

# Синтаксис: -Xlog:<tag>[+]<levels>:<output>:<decorators>
# - gc* — все GC-события
# - safepoint — safepoint-статистика
# - class+load — загрузка классов
# - method* — JIT-компиляция
```

**Safepoint-статистика:**
```bash
# Включить в лог (требует Diagnostic VMOptions)
-XX:+UnlockDiagnosticVMOptions -XX:+PrintSafepointStatistics -XX:+PrintSafepointStatisticsCount=1

# В логе появится:
# SafepointSynchronize: 12.345ms (подготовка)
# SafepointCleanup: 0.123ms (очистка)
# Total: 12.468ms
```

### Тюнинг сетевого стека для Java (NIO)

Для высоконагруженных API на базе Netty/Spring WebFlux:
*   Используйте **Epoll** вместо стандартного NIO (`-Djava.net.preferIPv4Stack=true`).
*   Включайте **TCP Keepalive** на уровне ОС и приложения.
*   Следите за Direct Memory (`-XX:MaxDirectMemorySize`).

### Типичные проблемы и решения

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **OOMKilled** | Pod завершен с exit code 137 | `kubectl describe pod` → OOMKilled; `jcmd <PID> VM.native_memory summary` | Увеличить `limits.memory`; проверить Direct Memory и Native Memory |
| **GC Thrashing** | Высокий CPU, низкий throughput | `jstat -gcutil <PID> 1000`; GC log | Увеличить `-Xmx`; проверить аллокации; перейти на ZGC |
| **Safepoint stall** | Паузы > 1с при малом Heap | `-XX:+PrintSafepointStatistics` в логе | Найти длинные synchronized-блоки; использовать biased locking lock eliminations |
| **Metaspace OOM** | `OutOfMemoryError: Metaspace` | `jcmd <PID> VM.metaspace` | Увеличить `-XX:MaxMetaspaceSize`; проверить утечки ClassLoader |
| **Thread exhaustion** | `OutOfMemoryError: unable to create new native thread` | `cat /proc/<PID>/limits \| grep processes`; `ulimit -u` | Увеличить `ulimit -u`; проверить утечки потоков |
| **Direct Memory OOM** | `OutOfMemoryError: Direct buffer memory` | `jcmd <PID> VM.native_memory summary` | Увеличить `-XX:MaxDirectMemorySize`; проверить ByteBuffer allocation |

### Spring Boot: источники конфигурации

Spring Boot поддерживает несколько уровней источников конфигурации (от низшего к высшему приоритету). Понимание этой иерархии критично для отладки, когда приложение читает значение не из того места, которое ожидает DevOps.

1.  **`application.yml` / `application.properties`** (в классеpath или внешний файл).
2.  **`application-{profile}.yml`** (активируется через `spring.profiles.active`).
3.  **Переменные окружения** (`SPRING_APPLICATION_JSON`, `VAR_NAME`).
4.  **Аргументы командной строки** (`java -jar app.jar --server.port=8080`).
5.  **Внешние конфигурационные файлы** (подключаются через `spring.config.additional-location`).
6.  **HashiCorp Vault** (через `spring-cloud-starter-vault-config`).
7.  **Config Tree (Spring Boot 2.4+):** механизм `spring.config.import` позволяет импортировать конфигурацию из директорий, где каждый файл или поддиректория соответствует имени переменной. Например:
    ```
    config/
    ├── spring.datasource.url
    └── spring.datasource.username
    ```
    Значение файла становится значением переменной. Это альтернатива монолитному `application.yml` для разделения секретов.

**Практика:** в контейнерах и Kubernetes переменные окружения (ConfigMap/Secret) часто используются вместо `application.yml`, потому что YAML рендерится через Helm и попадает в репозиторий. Если доступ к Vault или Config Tree невозможен (ограничения InfoSec), параметры подставляются как `env` в манифесте Deployment.

## Дополнительная информация

### См. также
* **[Диагностика OOMKilled](../../Kubernetes/Troubleshooting/Common_Errors/oomkilled_pods.md)** — что делать, если Java убивает ядро Linux.
* **[Механизмы cgroups](../../Linux/Core/cgroups.md)** — как работают лимиты ресурсов.
* **[Троттлинг процессора](../../Kubernetes/Troubleshooting/Common_Errors/cpu_throttling.md)** — почему Java может тормозить при наличии лимитов.

### Справочные ресурсы
* [JDK Bug System](https://bugs.openjdk.org/): поиск специфичных багов JVM.
* [Adoptium (Eclipse Temurin)](https://adoptium.net/): рекомендуемые сборки OpenJDK.
* [Arthas](https://arthas.aliyun.com/): мощный инструмент онлайн-диагностики Java-приложений.
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
1.  **Metaspace:** Метаданные классов (заменил PermGen в Java 8). Не лимитирован по умолчанию, рекомендуется `-XX:MaxMetaspaceSize`.
2.  **Code Cache:** Память для кода, оптимизированного JIT-компилятором.
3.  **Thread Stacks:** Память под каждый поток. По умолчанию ~1 МБ. *Важно:* Virtual Threads хранят свои стэки в Heap, снижая давление на системную память.
4.  **Direct Memory:** Используется NIO (например, в Netty, Kafka). Лимитируется через `-XX:MaxDirectMemorySize`.

### Контейнеризация и Container Awareness

JVM 10+ (и бэкпорты в 8u) умеет читать лимиты `cgroups` (CPU и RAM).

*   **RAM Awareness:** Если не задать `-Xmx`, JVM выделит ~25% от лимита памяти контейнера (MaxRAMPercentage).
*   **CPU Awareness:** JVM определяет количество ядер для Garbage Collector и ForkJoinPool на основе лимитов (CPU Quota).
*   **Троттлинг:** Если лимит CPU (например, 2 ядра) намного меньше количества ядер хоста (например, 64), JVM может запустить слишком много потоков GC, что приведет к жесткому троттлингу со стороны ядра Linux.
*   **Решение (Java 19+):** `-XX:PreferContainerQuotaForCPUCount=true` (активен по умолчанию) для более точного расчета ядер.

## Сборщики мусора (Garbage Collectors)

| GC | Стратегия | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Serial GC** | Однопоточный | Минимальный оверхед | Длинные паузы (STW) |
| **Parallel GC** | Пропускная способность | Максимальный Throughput | Значительные паузы на больших Heap |
| **G1GC** | Балансировка | Универсальность, предсказуемые паузы | Требует тюнинга для экстремальных SLA |
| **ZGC (Generational)** | Низкие задержки | Паузы < 1 мс при любом размере Heap | Выше потребление CPU |
| **Shenandoah** | Низкие задержки | Компактная куча, эффективен в облаке | Выше потребление CPU |

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

**Профилирование без остановки (JFR):**
```bash
jcmd <PID> JFR.start name=MyRecording settings=profile duration=60s filename=output.jfr
# → Анализировать через JDK Mission Control (JMC)
```

### Тюнинг сетевого стека для Java (NIO)

Для высоконагруженных API на базе Netty/Spring WebFlux:
*   Используйте **Epoll** вместо стандартного NIO (`-Djava.net.preferIPv4Stack=true`).
*   Включайте **TCP Keepalive** на уровне ОС и приложения.
*   Следите за Direct Memory (`-XX:MaxDirectMemorySize`).

## Дополнительная информация

### См. также
* **[Оптимизация Docker для Java](../../Docker/Dockerfile/Docker_best_practices/java.md)** — лучшие практики построения образов.
* **[Диагностика OOMKilled](../../Kubernetes/Troubleshooting/Common_Errors/oomkilled_pods.md)** — что делать, если Java убивает ядро Linux.
* **[Механизмы cgroups](../../Linux/Core/cgroups.md)** — как работают лимиты ресурсов.
* **[Троттлинг процессора](../../Kubernetes/Troubleshooting/Common_Errors/cpu_throttling.md)** — почему Java может тормозить при наличии лимитов.

### Справочные ресурсы
* [JDK Bug System](https://bugs.openjdk.org/): поиск специфичных багов JVM.
* [Adoptium (Eclipse Temurin)](https://adoptium.net/): рекомендуемые сборки OpenJDK.
* [Arthas](https://arthas.aliyun.com/): мощный инструмент онлайн-диагностики Java-приложений.
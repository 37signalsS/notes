# JVM и GC тюнинг для Apache Kafka

**JVM и GC тюнинг** — это настройка Java Virtual Machine и сборщика мусора для обеспечения стабильной производительности Kafka-брокера с минимальными паузами. Неправильная конфигурация GC — основная причина latency spikes и OOM в production-кластерах.

---

## Определения

- **JVM Heap:** Область памяти JVM для хранения объектов. Kafka использует heap для метаданных, кэша и временных структур, но НЕ для хранения сообщений (они в Page Cache).
- **Page Cache:** Оперативная память ОС, используемая для кэширования данных на диске. Kafka основана на Page Cache для высокопроизводительного I/O.
- **Garbage Collector (GC):** Механизм автоматического управления памятью в JVM. Очищает неиспользуемые объекты, вызывая stop-the-world паузы.
- **G1GC (Garbage-First):** Сборщик мусора по умолчанию в Kafka. Разбивает heap на регионы и собирает мусор в наиболее заполненных.
- **ZGC:** Низко-латентный сборщик мусора (JDK 15+), выполняет почти всю работу конкурентно с приложением.
- **Metaspace:** Область JVM для хранения метаданных классов. Может расти неограниченно при динамической загрузке классов (коннекторы, SMT).
- **GC Pause (Stop-the-World):** Время, когда приложение приостанавливается для сборки мусора.
- **MaxGCPauseMillis:** Целевое время паузы GC для G1GC. Меньше значение = меньше паузы, но больше overhead.
- **InitiatingHeapOccupancyPercent:** Процент заполнения heap, при котором G1GC запускает маркировку.
- **Heap Dump:** Снимок памяти JVM для анализа утечек.
- **jstat, jmap, jstack:** Утилиты JDK для мониторинга и диагностики JVM.

---

## Основные концепции

### Принцип работы Kafka с памятью

Kafka — это не типичное Java-приложение. Её производительность критически зависит от Page Cache, а не от heap:

```
┌─────────────────────────────────────────────┐
│              RAM (64 GB)                    │
├─────────────────────────────────────────────┤
│  Heap (8 GB)  │      Page Cache (56 GB)    │
│  ─────────────┼─────────────────────────── │
│  - Метаданные │  - Данные топиков          │
│  - Кэш смещений│  - Сегменты логов          │
│  - Временные  │  - Индексы                  │
│    структуры  │  - Кэш страниц ОС           │
└─────────────────────────────────────────────┘
```

**Золотое правило:** Дайте Kafka столько Page Cache, сколько возможно. Heap — только для служебных нужд.

### Рекомендации по размеру Heap

| Сценарий | Heap | Page Cache | Общий RAM |
|----------|------|------------|-----------|
| Тестовый кластер | 4 GB | 20 GB | 32 GB |
| Production (средний) | 6-8 GB | 40-48 GB | 64 GB |
| Production (большой) | 8 GB | 100+ GB | 128 GB |
| Высокие нагрузки | 8 GB (максимум) | 180+ GB | 256 GB |

**Важно:** Heap > 8 GB обычно вреден — время паузы G1GC растет нелинейно.

### Сравнение GC для Kafka

| GC | Паузы | Overhead | Когда использовать |
|----|------|----------|-------------------|
| **G1GC** | 10-200 ms | Средний | Стандарт для Kafka < 4.0 |
| **ZGC** | < 1 ms | Высокий | Kafka 4.0+, критичные к latency |
| **Shenandoah** | < 10 ms | Высокий | Альтернатива ZGC |

**G1GC параметры (стандарт):**
```bash
KAFKA_HEAP_OPTS="-Xms6g -Xmx6g"
KAFKA_JVM_PERFORMANCE_OPTS="-XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=35"
```

**ZGC параметры (Kafka 4.0+):**
```bash
KAFKA_HEAP_OPTS="-Xms8g -Xmx8g"
KAFKA_JVM_PERFORMANCE_OPTS="-XX:+UseZGC -XX:+ZGenerational"
```

### Metaspace tuning

Metaspace может утечь при использовании множества коннекторов или динамической загрузке классов:

```bash
-XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=256m
```

### GC логирование

Всегда включайте в production для постфактум анализа:

```bash
-Xlog:gc*:file=/var/log/kafka/kafkaServer-gc.log:time,uptime,level,tags:filecount=10,filesize=100M
```

### Диагностика проблем

**Команды для диагностики:**
```bash
# Мониторинг GC в реальном времени
jstat -gcutil <pid> 1000

# Анализ heap без остановки
jmap -histo:live <pid> | head -20

# Heap dump при подозрении на утечку
jmap -dump:format=b,file=/tmp/heapdump.hprof <pid>

# Thread dump (для анализа зависаний)
jstack <pid> > /tmp/threaddump.txt
```

**Симптомы проблем с GC:**
- GC pauses > 500ms (G1GC) → переход на ZGC
- Heap постоянно > 80% после полного GC → утечка памяти
- Metaspace растет → проверить коннекторы на утечки классов
- `OutOfMemoryError: Metaspace` → увеличить MaxMetaspaceSize или проверить на утечки

---

## Практические сценарии

### Сценарий 1: Базовая настройка G1GC для production

Файл `/etc/kafka/kafka-env.sh`:
```bash
#!/bin/bash
export KAFKA_HEAP_OPTS="-Xms6g -Xmx6g"
export KAFKA_JVM_PERFORMANCE_OPTS="
  -server
  -XX:+UseG1GC
  -XX:MaxGCPauseMillis=20
  -XX:InitiatingHeapOccupancyPercent=35
  -XX:G1HeapRegionSize=16M
  -XX:MinMetaspaceFreeRatio=50
  -XX:MaxMetaspaceFreeRatio=80
  -XX:+ExplicitGCInvokesConcurrent
  -XX:+ParallelRefProcEnabled
  -XX:+UnlockExperimentalVMOptions
  -XX:+UnlockDiagnosticVMOptions
  -XX:+DebugNonSafepoints
  -Xlog:gc*:file=/var/log/kafka/kafkaServer-gc.log:time,uptime,level,tags:filecount=10,filesize=100M
  -Djava.awt.headless=true
"
```

### Сценарий 2: Миграция на ZGC для низких задержек

```bash
# Проверка текущей версии Java
java -version  # Требуется JDK 15+ (рекомендуется JDK 21)

# Настройка ZGC
export KAFKA_HEAP_OPTS="-Xms8g -Xmx8g"
export KAFKA_JVM_PERFORMANCE_OPTS="
  -server
  -XX:+UseZGC
  -XX:+ZGenerational
  -XX:SoftMaxHeapSize=8g
  -XX:MetaspaceSize=256m
  -XX:MaxMetaspaceSize=256m
  -XX:+AlwaysPreTouch
  -XX:-OmitStackTraceInFastThrow
  -Xlog:gc*:file=/var/log/kafka/kafkaServer-gc.log:time,uptime,level,tags:filecount=10,filesize=100M
"
```

**Важно:** ZGC потребляет больше CPU (5-10%), но устраняет длительные паузы.

### Сценарий 3: Диагностика GC-проблем

```bash
# 1. Проверка текущего использования GC
jstat -gc <pid> 1000 10
# Смотрите на колонки (в процентах):
# S0U/S1U: Survivor 0/1 Used
# EU: Eden Used
# OU: Old Used
# MU: Metaspace Used

# 2. Проверка времени пауз GC
grep "pause" /var/log/kafka/kafkaServer-gc.log | tail -20

# 3. Анализ частых Full GC
jstat -gcutil <pid> 1000 | awk '{print $0}' | grep -E "FGC|FGCT"

# 4. Проверка утечек памяти
jmap -histo:live <pid> | head -30
```

### Сценарий 4: Оптимизация при высоком использовании Metaspace

```bash
# Если коннекторы или SMT загружают много классов:
export KAFKA_JVM_PERFORMANCE_OPTS="
  ...
  -XX:MetaspaceSize=512m
  -XX:MaxMetaspaceSize=512m
  -XX:+CMSClassUnloadingEnabled
  ...
"
```

**Внимание:** Увеличение Metaspace — временная мера. Истинная причина — утечка загрузчиков классов в коннекторах.

### Сценарий 5: Настройка для контейнеров (Docker/K8s)

```yaml
# В docker-compose.yml или deployment
env:
  - KAFKA_HEAP_OPTS=-Xms4g -Xmx4g
  - KAFKA_JVM_PERFORMANCE_OPTS=-XX:+UseG1GC -XX:MaxGCPauseMillis=20
resources:
  limits:
    memory: "8Gi"
  requests:
    memory: "6Gi"
```

**Правило:** Лимит контейнера должен быть на 2-4 GB больше heap для Page Cache внутри контейнера.

---

## Дополнительная информация

### Мониторинг GC через JMX

Ключевые метрики:
- `java.lang:type=GarbageCollector,name=G1 Old Collection/CollectionTime` — время Full GC
- `java.lang:type=GarbageCollector,name=G1 Young Collection/CollectionTime` — время Young GC
- `java.lang:type=Memory/HeapMemoryUsage` — использование heap

### Связь с OS tuning

- `vm.swappiness=1` — предотвращает выгрузку Page Cache (критично для Kafka)
- `vm.dirty_ratio` — влияет на flush грязных страниц в Page Cache
- THP (Transparent Huge Pages) — должен быть отключен (`never`) для предотвращения latency spikes

### Чек-лист для production

- [ ] Heap не превышает 8 GB
- [ ] Включено логирование GC
- [ ] Настроен MaxMetaspaceSize
- [ ] Page Cache занимает большую часть RAM
- [ ] THP отключен на уровне ОС
- [ ] Мониторинг GC pause time настроен
- [ ] При heap > 70% после полного GC — план действий

### См. также
- **[OS Tuning](./kafka_os_tuning.md)** — настройки ядра Linux для Kafka
- **[Производительность Kafka](./kafka_overview.md)** — общее описание архитектуры производительности
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — JMX-метрики и алерты

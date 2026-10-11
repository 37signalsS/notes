# Neo4j: Диагностика на уровне JVM

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

## Определения

| Термин | Значение |
| :--- | :--- |
| **Heap** | Память JVM для Java-объектов Neo4j: планы запросов, состояние транзакций, кэш запросов. Управляется `server.memory.heap.*`. |
| **Page cache** | Кэш store-файлов и индексов. Живёт вне heap, размер задаётся `server.memory.pagecache.size`. |
| **Off-heap** | Память, выделенная напрямую из ОС мимо GC: сетевые буферы Bolt. Состояние транзакций on-heap по умолчанию — off-heap включается опционально (`dbms.tx_state.max_off_heap_memory`). |
| **Direct memory** | Буферы `ByteBuffer` вне heap; в Neo4j их занимает сетевой стек Bolt. |
| **Metaspace** | Метаданные классов: загруженные JAR-плагины, APOC, драйверы. |
| **Young / old generation** | Поколения кучи. Молодое очищается быстро и дёшево, старое — пауза растёт вместе с размером кучи. |
| **GC thrashing** | Ситуация, когда JVM почти всё время в сборке мусора. Производительность падает на порядки. |
| **NMT** | Native Memory Tracking — механизм JVM для учёта native-памяти по категориям. |
| **JFR** | Java Flight Recorder — встроенный профилировщик с низким overhead. |

## Базовые понятия: почему «OOM в Neo4j» — это не про heap

Общая теория JVM-инструментов изложена в [управлении Java в Linux](../../Linux/Development/java_management.md): там же `jcmd`, `jstat`, `jmap`, `jstack`, дампы кучи, NMT, работа с контейнерами и cgroups. Здесь — только то, что специфично для Neo4j: **процесс использует четыре независимых области памяти, и симптом у них общий — падение производительности или OOM, но лечение разное.**

| Область | Кто владеет | Как растёт | Как измерить |
| :--- | :--- | :--- | :--- |
| Heap | JVM | Планы запросов, состояние транзакций, длинные обходы | `jcmd <PID> GC.heap_info`, метрика `neo4j_dbms_vm_heap_used` |
| Page cache | Neo4j, вне JVM | Объём store-файлов и Lucene-индексов | `server.memory.pagecache.size`, `neo4j_dbms_page_cache_hit_ratio` |
| Transaction state | Neo4j | Размер незавершённых транзакций; on-heap по умолчанию, off-heap опционально | `jcmd <PID> VM.native_memory summary` (NMT), `SHOW TRANSACTIONS` (currentQueryAllocatedBytes) |
| Direct / Netty | JVM + сетевой стек | Число одновременных соединений и размеры буферов | NMT, `dbms.bolt.connections_running` |

**Практический вывод:** если процесс упирается в память, сначала определите, какая из областей исчерпана. Увеличение `server.memory.heap.max_size` при нехватке page cache не поможет, а при нехватке transaction state — усугубит давление на GC.

### Слои конфигурации JVM

JVM-параметры Neo4j задаются через `server.jvm.additional`. Ключ можно указывать **несколько раз** — каждое значение добавляет ещё один аргумент в строку запуска:

```properties
# neo4j.conf
server.jvm.additional=-XX:+UseG1GC
server.jvm.additional=-XX:+DisableExplicitGC
```

Проверка на опечатки и дубликаты работает для всего `neo4j.conf`, **кроме** `server.jvm.additional` — опечатка в JVM-флаге не помешает старту, а проявится позже как неожиданное поведение.

### Специфика GC в Neo4j

Официальные рекомендации по сборщику мусора сводятся к нескольким пунктам, и все они вытекают из устройства нагрузки Neo4j:

- куча разделена на молодое и старое поколения; при заполнении поколения сборщик выполняет collection, **останавливая все прочие потоки процесса**;
- пауза в молодом поколении коррелирует с размером живого набора, в старом — примерно с размером кучи;
- **куча должна быть подобрана так, чтобы состояние транзакций и запросов никогда не попадало в старое поколение.** Это ключевая формулировка: старые поколения и растущий там мусор — прямая причина растущих пауз;
- если молодое поколение слишком мало, короткоживущие объекты переносятся в старое слишком рано (premature promotion) — растёт частота сборок старого поколения;
- если молодое поколение слишком велико, сборщик может решить, что в старом не хватит места для ожидаемого переноса, и превращает сборки молодого в сборки старого — тоже медленно;
- больше одновременных потоков — больше аллокаций за единицу времени, то есть выше давление именно на молодое поколение;
- при GC thrashing производительность может падать **на два порядка**; это не «немного медленнее», а клиентские таймауты;
- рабочие конфигурации heap в реальных внедрениях встречаются от 1 ГБ до 32 ГБ.

`-XX:+UseG1GC` — рекомендуемый по умолчанию сборщик: хороший баланс между пропускной способностью и хвостовой задержкой при минимальной настройке.

**Compressed OOPs** сжимают ссылки до 32 бит и экономят много памяти, но доступны **только для куч до 32 ГБ**; максимально применимый размер зависит от платформы и версии JVM. Проверка — `-XX:+UseCompressedOops`.

## Практические сценарии

### Определить, какая область памяти исчерпана

**Предпосылки:** нужен `jcmd`/`jstat`/`jmap` из JDK на хосте, PID процесса Neo4j, права на чтение `/proc/<PID>` и `ps`; для NMT — перезапуск с `-XX:NativeMemoryTracking=summary` (включить нельзя на лету, метрика без перезапуска недоступна). В контейнере `jcmd` работает внутри пода и расходует лимит памяти того же контейнера.

Порядок проверки — от дешёвого к дорогому:

```bash
# 1. Что видно снаружи: реальное потребление процесса
ps -o pid,rss,vsz,cmd -C java
# → RSS заметно больше heap — значит, память ушла в page cache или off-heap

# 2. Heap и generational state
jcmd <PID> GC.heap_info

# 3. Native memory по категориям (требует NMT, см. ниже)
jcmd <PID> VM.native_memory summary
```

```cypher
-- 4. Со стороны Neo4j: transaction state и активные транзакции
SHOW TRANSACTIONS
YIELD transactionId, currentQuery, elapsedTime, currentQueryAllocatedBytes, pageFaults
RETURN transactionId, elapsedTime, currentQueryAllocatedBytes, pageFaults, currentQuery
ORDER BY currentQueryAllocatedBytes DESC
LIMIT 10;
```

```cypher
-- 5. Кто занимает page cache
CALL dbms.listPools()
```

Решение по результатам:

| Наблюдение | Диагноз | Действие |
| :--- | :--- | :--- |
| RSS ≈ heap + page cache | Штатная работа | Действий не требуется |
| RSS выше суммы слоёв | Утечка direct-памяти или буферов Netty | NMT по категориям, проверить число соединений Bolt |
| Heap заполнен, доля GC растёт | Не хватает heap либо состояние транзакций уходит в старое поколение | `server.memory.heap.*`, найти длинные транзакции |
| Page cache hit ratio падает | Рабочий набор не помещается в кэш | Увеличить `server.memory.pagecache.size`, уменьшить нагрузку |
| Растёт `currentQueryAllocatedBytes` в `SHOW TRANSACTIONS` | Одна транзакция аккумулирует изменения | Прервать транзакцию, найти запрос без `LIMIT` |

### Включить NMT

Native memory не виден в heap-статистике и плохо сходится с RSS. Включается флагом JVM:

```properties
# neo4j.conf
server.jvm.additional=-XX:NativeMemoryTracking=summary
```

После перезапуска:

```bash
jcmd <PID> VM.native_memory summary
# → таблица по категориям: Java Heap, Class, Thread, Code, GC, Internal, Other
```

Сброс базы отсчёта (полезно перед целевой нагрузкой):

```bash
jcmd <PID> VM.native_memory baseline
```

### Дамп кучи при OOM

Включается заранее — после падения OOM дамп уже не собрать:

```properties
# neo4j.conf
server.jvm.additional=-XX:+HeapDumpOnOutOfMemoryError
server.jvm.additional=-XX:HeapDumpPath=/var/lib/neo4j/diagnostics
```

Каталог должен существовать и принадлежать пользователю `neo4j`. Дампы — файлы размером с кучу; оставляйте на диске место, а каталог — в ротации.

### Логи GC

```properties
# neo4j.conf
server.jvm.additional=-Xlog:gc*,gc+heap=debug:file=/var/lib/neo4j/logs/gc.log:time,uptime,level,tags:filecount=5,filesize=20M
```

Интерпретация по [настройке GC-журналов в Neo4j](./monitoring.md#конфигурация-log4j-2) и по метрике `neo4j_dbms_vm_gc_time_percent` из [мониторинга](./monitoring.md).

### Профилирование через JFR

Официально предусмотренные значения, полезные для профилирования:

```properties
# neo4j.conf
server.jvm.additional=-XX:FlightRecorderOptions=stackdepth=256
server.jvm.additional=-XX:+UnlockDiagnosticVMOptions
server.jvm.additional=-XX:+DebugNonSafepoints
```

- `FlightRecorderOptions=stackdepth=256` увеличивает глубину сэмплирования стека с 64 до 256 кадров, чтобы профилировщик не обрезал фреймы;
- `UnlockDiagnosticVMOptions` позволяет профилировщикам сэмплировать **между safepoints** — без этого результаты сэмплирования менее точны;
- `DebugNonSafepoints` включает отладочную информацию в JIT-скомпилированном коде, что делает профилирование точнее ценой небольшого падения производительности.

Старт и остановка записи на живом процессе:

```bash
jcmd <PID> JFR.start name=LongRunning settings=profile maxsize=200M maxage=1h filename=/tmp/neo4j.jfr
jcmd <PID> JFR.stop name=LongRunning
```

Запись в production-нагрузке всегда сравнивайте с baseline той же длительности без изменений — см. [непрерывное профилирование](../../Concepts/continuous_profiling.md).

### Полезные предопределённые значения JVM

Neo4j поставляет готовый набор значений `server.jvm.additional`. Не все из них обязательны; приведены те, что влияют на эксплуатацию:

| Значение | Зачем |
| :--- | :--- |
| `-XX:+UseG1GC` | Рекомендуемый сборщик мусора |
| `-XX:+AlwaysPreTouch` | Выделяет и коммитит heap до старта базы; если флаг ухудшает производительность, heap нужно уменьшить |
| `-XX:+DisableExplicitGC` | Отключает явные вызовы GC, которые JDK иногда вызывает сам |
| `-XX:-OmitStackTraceInFastThrow` | Гарантирует, что частые исключения всегда имеют стектрейсы — иначе отладка невозможна из-за ротации логов |
| `-XX:-RestrictContended` | Разрешает Neo4j использовать аннотацию `@Contended` |
| `-Djdk.nio.maxCachedBufferSize=1024` | Ограничивает кэш буферов JDK до 1 КБ |
| `-Dio.netty.leakDetection.level=DISABLED` | Отключает детектор утечек Netty (добавлено в 2025.04); допустимы `DISABLED`, `SIMPLE`, `ADVANCED`, `PARANOID` |
| `-Dlog4j2.disable.jmx=true` | Отключает JMX-эндпоинт логирования |
| `-XX:+UseCompressedOops` | Диагностическая проверка доступности сжатых ссылок |
| `-XX:+UnlockExperimentalVMOptions` + `-XX:+TrustFinalNonStaticFields` | Агрессивная оптимизация final-полей JIT (лучше throughput); отключить при рефлексии/сериализации сторонних плагинов |
| `-Dio.netty.tryReflectionSetAccessible=true` | Эффективнее выделяет direct-буферы Netty (рефлексивный доступ к JVM-внутренностям) |
| `-Djdk.tls.ephemeralDHKeySize=2048` | DH-ключ для TLS-рукопожатий: 1024 → 2048 (жёсткость шифрования) |
| `-Djdk.tls.rejectClientInitiatedRenegotiation=true` | Блокирует client-initiated TLS renegotiation — защита от DDoS |
| `--add-opens=java.base/java.nio=ALL-UNNAMED` (и `java.io`, `sun.nio.ch`) | Открывает модули JVM для внутреннего доступа Neo4j (требуется для старта) |
| `--add-opens=java.base/java.util.concurrent=ALL-UNNAMED` | Открывает `java.util.concurrent` для внутреннего доступа Neo4j (добавлено в 2025.04) |
| `--enable-native-access=ALL-UNNAMED` | Разрешает доступ к нативной памяти (Foreign Memory и IO) |
| `--add-modules=jdk.incubator.vector` | Подключает JDK Vector API для векторных индексов (добавлено в 2026.08) |
| `-Dlog4j.layout.jsonTemplate.maxStringLength=32768` | Увеличивает максимальную длину строки в JSON-логе (иначе усекается) |
| `-Dorg.neo4j.shaded.lucene9.vectorization.upperJavaFeatureVersion=25` | Устаревшим Lucene-индексам (9.x) позволяет использовать векторный ускоритель в новых JDK (добавлено в 2026.02) |

Полный список — в разделе [JVM в `neo4j.conf`](https://neo4j.com/docs/operations-manual/current/configuration/neo4j-conf/).

### В контейнере и в Kubernetes

- Команды `neo4j-admin` в контейнере требуют флага `--expand-commands`: Helm-чарт задаёт конфигурацию через подстановку в команде, которая разрешается в рантайме.
- Процессы, запущенные через `kubectl exec`, **считаются в сторону лимита памяти контейнера**. Запущенная через exec тяжёлая операция может привести к тому, что OOM-убийцу убьёт контейнер с самим Neo4j.
- Проверка, запущен ли JVM внутри пода:

```bash
kubectl exec -it <release-name>-0 -- bash
# $ jps
# → 19 Jps   (в офлайн-режиме других java-процессов нет)
```

- Лимиты памяти контейнера должны превышать сумму heap + page cache с запасом на ОС: урезанный лимит не даёт ошибки конфигурации — Neo4j стартует и упирается в OOM Kill под нагрузкой.

Подробно — в [Kubernetes](./kubernetes_deployment.md) и в [обслуживании](./operations.md#docker-память-в-контейнере).

## Устранение неполадок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Рост `neo4j_dbms_vm_gc_time_percent` | Высокий CPU, низкий throughput | `jstat -gcutil <PID> 1000`, GC-лог | Увеличить heap; найти длинные транзакции; проверить premature promotion |
| Медленные паузы при старте нагрузки | Запросы иногда «виснут» на миллисекунды | `heap initial_size` меньше `max_size` | Задать `initial_size` равным `max_size` — рост кучи требует полного цикла GC |
| `OutOfMemoryError: Java heap space` | Запросы падают | `jcmd <PID> GC.heap_info` | Увеличить heap, но сначала найти запрос, создающий давление |
| `OutOfMemoryError: Direct buffer memory` | Ошибка на сетевых операциях | `jcmd <PID> VM.native_memory summary` | Проверить число соединений Bolt и размеры буферов |
| `OutOfMemoryError: Metaspace` | Ошибка после загрузки плагина | `jcmd <PID> VM.metaspace` | Ограничить `-XX:MaxMetaspaceSize`; проверить, не грузится ли множество версий APOC |
| RSS растёт, heap стабилен | Утечка вне кучи | NMT по категориям, сравнение с базой | Искать утечку в сетевом стеке или direct-буферах |
| Профилирование не даёт точных стеков | Обрезанные фреймы | Проверить `FlightRecorderOptions` | Поднять `stackdepth`, добавить `UnlockDiagnosticVMOptions` |
| Логов ошибок нет, а ошибки идут | Молчаливые исключения | `neo4j.log` без стектрейсов | Добавить `-XX:-OmitStackTraceInFastThrow` |
| Пода убита с exit code 137 | `OOMKilled` | `kubectl describe pod`, `jcmd VM.native_memory summary` | Поднять `limits.memory`; учесть, что память `kubectl exec` идёт в тот же лимит |

## Лучшие практики

- **Сначала определите область памяти, потом увеличивайте.** Диагностическая процедура в разделе выше — порядок действий по умолчанию.
- **Задавайте `initial_size` равным `max_size`** — рост кучи в рантайме вызывает полный GC.
- **Цель — не дать состоянию транзакций попасть в старое поколение.** Длинные транзакции без `LIMIT` бьют именно сюда.
- **Включайте `-XX:+HeapDumpOnOutOfMemoryError` заранее** и следите за местом под дампы.
- **NMT включайте на время расследования:** постоянно включённый NMT имеет overhead, а не «совсем бесплатен».
- **Heap до 32 ГБ** — иначе отключается экономия памяти на сжатых ссылках.
- **JFR включайте точечно:** постоянная запись `profile` на production-нагрузке съедает диск и добавляет overhead.
- **Лимит контейнера = heap + page cache + запас на ОС.** Ошибка конфигурации при этом не возникает — ошибка приходит как OOM Kill в проде.

## Дополнительная информация

- **[Документация: Tuning of the garbage collector](https://neo4j.com/docs/operations-manual/current/performance/gc-tuning/)** — официальные рекомендации по GC для Neo4j.
- **[Документация: Настройки JVM в `neo4j.conf`](https://neo4j.com/docs/operations-manual/current/configuration/neo4j-conf/)** — полный список предопределённых значений `server.jvm.additional`.
- **[Документация: Memory configuration](https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/)** — heap, page cache и расчёт бюджета памяти.
- **[Управление и тюнинг Java (JVM) в Linux](../../Linux/Development/java_management.md)** — общая теория: `jcmd`, `jstat`, `jmap`, `jstack`, NMT, дампы, cgroups, THP.
- **[Тюнинг JVM в Kafka](../../Kafka/kafka_jvm_gc_tuning.md)** — похожая задача для другого сервера на JVM: сравнение подходов.
- **[Непрерывное профилирование](../../Concepts/continuous_profiling.md)** — методология съёмки профилей в проде.
- **[Профилирование: углублённый разбор](../../Concepts/Observability_and_Monitoring/profiling_deep_dive.md)** — инструменты и интерпретация результатов.
- **[Метрики рантайма приложений](../../Concepts/Observability_and_Monitoring/application_runtime_metrics.md)** — общие пороги по JVM-метрикам.

## См. также

- **[Обслуживание и эксплуатация](./operations.md)** — слои памяти процесса, `memory-recommendation`, лимиты транзакций.
- **[Мониторинг и логи](./monitoring.md)** — `neo4j_dbms_vm_gc_time_percent`, логи GC, Prometheus-эндпоинт.
- **[Kubernetes](./kubernetes_deployment.md)** — probes, лимиты памяти, `kubectl exec`.
- **[Безопасность](./security.md)** — JMX на 3637 как вектор RCE.
- **[Оптимизация запросов](./query_optimization.md)** — планы, кэш планов, что именно создаёт давление на heap.
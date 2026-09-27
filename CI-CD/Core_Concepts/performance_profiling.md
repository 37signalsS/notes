# Профилирование производительности CI/CD

## Определения

- **Profiling (профилирование)** — сбор данных о распределении ресурсов (CPU, память, IO, сеть) во время выполнения задачи. В контексте CI/CD профилирование применяется к стадиям пайплайна, сервисам раннеров, реестру артефактов и сетевым переходам между ними.
- **CPU-bound** — задача ограничена производительностью процессора; профиль показывает горячие функции или команды сборки.
- **IO-bound** — задача ограничена скоростью диска или сети; профиль фиксирует длинные ожидания чтения/записи.
- **Memory-bound** — задача ограничена объёмом оперативной памяти; профиль выделений указывает источник роста RSS.
- **Flame Graph** — визуализация стека вызовов, где ширина прямоугольника соответствует доле затраченного времени. Полезна для быстрого визуального поиска «горячих» путей.
- **pprof** — профайлер для Go и Python (через HTTP-endpoint или файл). Для CI-сервисов на Go — встроенный инструмент.
- **perf** — системный профайлер Linux (Performance Events), работающий на уровне ядра. Детальный справочник — в **[perf](../../Linux/Diagnostics/Performance/perf.md)**.
- **Tail Latency** — задержка на верхних перцентилях (p95/p99/p999); среднее значение скрывает проблемы, которые влияют на пользовательский опыт.
- **Queue Time** — время ожидания задачи в очереди раннера; рост Queue Time — первый сигнал нехватки capacity или слишком жёстких лимитов.
- **Continuous Profiling** — постоянный сбор профилей в production для сравнения регрессий между релизами.

## Основные концепции

### Что профилировать в CI/CD: предметная область

Профилирование в CI/CD отличается от профилирования веб-сервиса: объектами анализа становятся не только микросервисы, но и инфраструктурные компоненты конвейера:

| Объект | Типичные узкие места | Кто отвечает |
| :--- | :--- | :--- |
| **Стадия сборки** | CPU при transpile/lint, IO при restore, Memory при bundler | DevOps / SRE |
| **Раннер (агент)** | `LimitNOFILE`, cgroup throttle, контенденция на диске | Sysadmin |
| **Registry (реестр образов)** | GC, иноды, диск, сеть до registry | Sysadmin / DevOps |
| **Сеть runner → registry** | MTU, DNS, firewall, tcp-retries | Sysadmin |
| **Артефакт-сторadge** | IO-bound на upload/download, retention | Sysadmin / DevOps |
| **База данных миграций** | Lock contention, IO, long-running transaction | SRE / DevOps |

### Метод: сначала метрики, потом профиль

Не профилируйте наугад. Сначала метрики показывают **где** проблема (раннер? реестр? стадия сборки?), затем профиль показывает **что** именно (какая команда/функция). Для CI/CD это означает последовательность:

1. Алерт или жалоба: рост Lead Time, падение Deployment Frequency, рост CFR.
2. Метрики пайплайна (queue time, stage duration, runner saturation) — локализация объекта.
3. Системные метрики узла (`iostat`, `pidstat`, `df -i`) — определение класса узкого места.
4. Профиль (perf/pprof/py-spy) — точная локализация причины.
5. Регрессия: повторный запуск после фикса, сравнение метрик.

### Чтение flame graph

Ищите широкие «полки» у основания — команды или функции, съедающие большую долю времени. Узкие пики наверху — редкие, но глубокие пути (например, блокировка или ожидание GC). В контексте CI/CD flame graph часто строится по процессу сборки или по раннеру; в этом случае верхние уровни могут содержать обёртки (`sh -c`, `bash -e`), а горячий код — глубже.

### Типы узких мест в CI/CD

- **CPU-bound:** высокий `usr%`, мало `iowait`. Типично для transpile, lint, unit-тестов, шифрования артефактов.
- **IO-bound:** высокий `iowait`, `await` диска > 20 мс. Типично для restore зависимостей, сборки кэша, загрузки образов.
- **Memory-bound:** рост RSS, GC-паузы, `OOMKilled`. Типично для bundler, JVM-сборок, `docker build` без лимитов.
- **Scheduler-bound:** поток часто вытесняется или мигрирует между ядрами; причина — нехватка CPU capacity или конфликт affinity.

### Tail latency и DORA

Средняя длительность стадии может быть 50 секунд при p99 = 2 минуты. Для SRE важны перцентили: регрессии проявляются именно на хвосте. Рост p99 Lead Time напрямую снижает DORA-метрику **Lead Time for Changes** и может повышать **Change Failure Rate**, если ускорение достигается за счёт отключения гейтов. Подробнее о связке с DORA — в **[Метрики DORA](./dora_metrics.md)**.

## Практические сценарии

### Сценарий 1: Системное профилирование узла раннера (perf)

```bash
# Запись профиля процесса раннера на 30 секунд с графом вызовов
sudo perf record -F 99 -g -p $(pgrep -f gitlab-runner) -- sleep 30
# → [ perf record: Captured and wrote 1.024 MB perf.data ]

# Интерактивный анализ
sudo perf report
# → Выберите функцию и нажмите Enter для раскрытия стека

# Для flame graph (требуется FlameGraph):
sudo perf script | /opt/FlameGraph/stackcollapse-perf.pl | /opt/FlameGraph/flamegraph.pl > runner_flame.svg
```

### Сценарий 2: Профилирование контейнера сборки

```bash
# Найти PID контейнера
CTR_ID=$(docker ps -q --filter "name=build-step")
CTR_PID=$(docker inspect -f '{{.State.Pid}}' "$CTR_ID")

# Запись perf-профиля через namespace контейнера
sudo perf record -F 99 -g -t <TID> -- sleep 30

# Альтернатива: nsenter в namespace контейнера
sudo nsenter -t "$CTR_PID" -m -u -i -n -p -- perf record -F 99 -g -- sleep 30
# → [ perf record: Woken up 2 times to write data ]
# → [ perf record: Captured and wrote 0.512 MB perf.data ]
```

### Сценарий 3: pprof для Go-сервиса (CI-платформа или раннер)

```bash
# CPU-профиль 30 секунд
go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30
# → Fetching profile over HTTP from http://localhost:6060/debug/pprof/profile?seconds=30
# → Saved profile in /tmp/pprof.xxx

# Топ-10 функций по времени
(pprof) top10
# → Showing nodes accounting for 840ms, 84% of 1000ms total

# Heap-профиль
go tool pprof http://localhost:6060/debug/pprof/heap
(pprof) top10

# Визуализация flamegraph (требуется graphviz)
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/profile?seconds=30
# → Откроет браузер с интерактивным flamegraph
```

### Сценарий 4: Диагностика registry и artifact storage

```bash
# iostat для диска реестра (проверка await, %util)
iostat -x 1 30 /dev/sdb
# → Device            r/s     w/s     rkB/s     wkB/s   await   %util
# → sdb              12.00  450.00    64.00  8192.00   12.50   85.00

# Проверка инодов (частая причина "зависания" GC)
df -i /var/lib/registry
# → Filesystem      Inodes  IUsed   IFree IUse% Mounted on
# → /dev/sdb        65536  65432    104   99% /var/lib/registry

# Список самых "дорогих" слоев по размеру
find /var/lib/registry/docker/registry/v2/blobs -type f -printf "%s %p\n" | sort -rn | head -20
```

### Сценарий 5: Применение к CI-инциденту (пошаговый пример)

**Ситуация:** Длительность стадии `build` выросла с 2 до 12 минут, CFR увеличился с 3% до 18%.

1. **Метрики:** `pipeline_observability.md` — p95 stage duration, runner saturation, queue time.
2. **Локализация:** Runner saturation < 80%, queue time < 10 секунд → проблема не в инфраструктуре, а в самой стадии.
3. **Система:** `pidstat -t -p <PID> 1` — один TID 100% CPU, остальные 0%. `perf top -g -t <TID>` — горячая функция `babel.transform`.
4. **Профиль:** `perf record -F 99 -g -t <TID> -- sleep 10` + `perf report` — 60% времени в Babel без кэширования трансформаций.
5. **Фикс:** Включение Babel cache-loader, локальный registry-прокси для образов.
6. **Регрессия:** p95 build duration вернулся к 2 минутам, CFR снизился до 4%.

## Операции и команды

### Профилирование процессов

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `perf top -g -p <PID>` | Живой просмотр горячих функций процесса | `99.0%  gitlab-runner  [.] process_job` | Sysadmin / SRE |
| `perf record -F 99 -g -p <PID> -- sleep 30` | Запись профиля на 30 секунд | `[ perf record: Captured and wrote 1.024 MB perf.data ]` | Sysadmin / SRE |
| `perf report` | Интерактивный анализ записанного профиля | Функции с Overhead, стек вызовов | Sysadmin / SRE |
| `perf script \| stackcollapse-perf.pl \| flamegraph.pl > flame.svg` | Генерация flame graph SVG | Файл `flame.svg` с интерактивной диаграммой | Sysadmin / SRE |
| `py-spy top --pid <PID>` | Живой топ Python-процесса | `99.0%  myapp.heavy (/app/heavy.py:42)` | DevOps / SRE |
| `py-spy record -o flame.svg --duration 30 --pid <PID>` | Flame graph Python без перезапуска | `Wrote flame.svg (1.2 MB)` | DevOps / SRE |

### Анализ контенденции и планировщика

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `perf sched record -p <PID> -- sleep 10` | Запись событий планировщика | `sleep 10` (без вывода) | Sysadmin |
| `perf sched timehist` | Визуализация задержек On/Off-CPU | Столбцы `wait_time`, `delay` по времени | Sysadmin / SRE |
| `perf sched latency` | Статистика задержек по задачам | `Average delay ms: 2.345` | Sysadmin / SRE |
| `perf lock contention` | Анализ контенденции блокировок | `Total contentions: 1542` | Sysadmin / SRE |

### Мониторинг ресурсов раннеров и registry

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `pidstat -t -p <PID> 1` | Интервальная статистика по потокам | Таблица `%usr`, `%system`, `%guest`, `%wait` | Sysadmin |
| `iostat -x 1 30 /dev/sdb` | Дисковые метрики с await и %util | `await 12.50`, `%util 85.00` | Sysadmin |
| `df -h /var/lib/registry` | Доступное место на тома registry | `Size Used Avail Use%` | Sysadmin |
| `df -i /var/lib/registry` | Доступные иноды реестра | `IUse% 99%` при проблемах GC | Sysadmin |
| `systemctl status gitlab-runner` | Статус сервиса раннера | `active (running)` / `failed` | Sysadmin |
| `systemctl status registry` | Статус сервиса registry | `active (running)` | Sysadmin |

### Сеть и диагностика registry

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `curl -I registry.internal/v2/` | Доступность registry API | `HTTP/1.1 200 OK` | Sysadmin |
| `dig registry.internal` | DNS-резолвинг registry | IP-адрес реестра | Sysadmin |
| `ip route get registry.internal` | Маршрут до registry | `via ... dev ... src ...` | Sysadmin |
| `nft list ruleset` | Правила firewall для registry | Таблицы, цепочки, правила | Sysadmin |
| `ss -tnp \| grep 5000` | Соединения на порту registry | `ESTAB 0 0 ... 5000` | Sysadmin |
| `tcpdump -i eth0 host registry.internal -nn -c 100` | Сетевые пакеты до registry | Счётчик пакетов, retransmit | Sysadmin |

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
| :--- | :--- | :--- | :--- |
| **`Too many open files`** | Дефолтный `LimitNOFILE` исчерпан при 100+ параллельных джоб | Увеличить `LimitNOFILE=65536` в systemd-юните раннера | Sysadmin |
| **`OOMKilled`** | `MemoryMax` не установлен или слишком мал | Указать `MemoryMax` в юните или `limits.memory` в пода раннера | Sysadmin |
| **Раннер не берёт задачи** | `concurrent=0`, неверный токен, квота исчерпана | `gitlab-runner verify`, проверить `config.toml`, свободные слоты | Sysadmin / DevOps |
| **`No space left on device`** | Переполнение `/var/lib/docker` или инодов реестра | `docker system prune -f`, `df -i /var/lib/registry`, retention | Sysadmin |
| **Registry недоступен** | DNS не резолвится, диск полон, сервис упал | `dig registry.internal`, `df -h`, `systemctl status registry` | Sysadmin |
| **Падение джоба с `connection refused`** | Нет маршрута до registry, firewall блокирует порт | `ip route get`, `nft list ruleset`, `curl -I` | Sysadmin |
| **Деплой зависает на `pull image`** | MTU через туннель меньше, чем в контуре | Уменьшить MTU на интерфейсе туннеля | Sysadmin |
| **`await` диска > 50 мс** | HDD под нагрузкой, нет NCQ/TCQ, congested IO scheduler | `iostat -x 1`, `hdparm -I /dev/sdX`, `noop`/`mq-deadline` scheduler | Sysadmin |
| **Иноды реестра исчерпаны** | GC не срабатывает, retention не настроен | `df -i`, настроить `registry:gc` timer, `Persistent=true` | Sysadmin |
| **GC registry не запускается** | Timer отключён, `Persistent=false`, пропущено окно | `systemctl list-timers`, `journalctl -u registry-gc.service` | Sysadmin |
| **p99 stage растёт, p50 стабилен** | Проблема не в коде, а в очереди или холодном кэше | Проверить Queue Time, runner cold-start | SRE / DevOps |
| **Runner 100% CPU, `perf` показывает `[unknown]`** | Бинарник stripped, нет debug-info | Установить `debug-info` пакеты или `debuginfod` | Sysadmin |
| **Профилирование в production вызывает лаги** | `perf` с высокой частотой, `strace` на долгом интервале | Уменьшить `-F`, использовать `perf archive` + offline анализ | SRE |
| **Нет correlation между profiler и метриками** | Отсутствуют `trace_id`/`correlation_id` в логах раннера | Добавить обогащение логов, проверить OTel config | DevOps / SRE |
| **Пайплайн деградирует после релиза, но p50 не изменился** | Tail latency регрессия, узкое место в hot path | Профилировать по p99, строить flame graph по процентам | SRE |
| **Thread starvation в пуле раннеров** | `max_threads` слишком мал, задачи блокируют пул | Увеличить `concurrent` в `config.toml`, проверить `LimitNOFILE` | Sysadmin / DevOps |

## Лучшие практики

### Профилирование и диагностика

1. **Метрики перед профилем:** никогда не запускайте `perf`/`pprof` без предварительного анализа метрик. Определите класс узкого места (CPU/IO/Memory/Scheduler), иначе профилирование будет нецелевым.
2. **Профилируйте в реальной среде:** staging часто не повторяет нагрузку production. Для CI/CD — профилируйте на типовых задачах в prod-раннере, но с низким оверхедом (`-F 99`, `--duration 30`).
3. **Используйте sched timehist для «холодных» задач:** если приложение медленное, но не горячее, ищите не Hot Spot, а Cold Spot — длинные Off-CPU периоды.
4. **Offline-анализ perf.data:** на production-серверах с высокой нагрузкой не запускайте `perf report` интерактивно. Скопируйте `perf.data` на dev-машину и анализируйте там.
5. **Низкоуровневые профайлеры для JIT-языков:** `async-profiler` для Java, `py-spy` для Python, `node --prof` для Node.js. `perf` видит JIT-код как `[JIT]`/`[unknown]`.

### Инфраструктура и конфигурация

6. **Immutable runner images:** Golden image (Packer) с предустановленными `perf`, `FlameGraph`, `debug-info` пакетами. При изменении — rebuild образа, а не патч на живом узле.
7. **Отдельные тома для registry и артефактов:** `/var/lib/registry` на отдельном устройстве/томе с `noatime`, мониторинг `df -h` и `df -i`. GC по расписанию через systemd-timer.
8. **cgroups v2 для всех сервисов:** `MemoryMax=`, `CPUQuota=`, `LimitNOFILE=` в systemd-юнитах. Для контейнеров — `cpu.max`, `memory.max`.
9. **Swap с контролем:** swap-файл или раздел для защиты от OOM; `vm.swappiness=10` для раннеров, `vm.overcommit_memory=0` для registry.
10. **DNS внутренний и кэширующий:** локальный resolver (Unbound/systemd-resolved) для контура; мониторинг TTL и % ответов из кэша. DNS-задержки часто маскируются под «медленный registry».

### Наблюдаемость и связь с DORA

11. **Алерты на p99/p95, а не на среднее:** дежурный должен получать actionnable алерты по tail latency, которые коррелируют с Lead Time.
12. **SLO пайплайна вместо абсолютных порогов:** «95% сборок укладываются в p95 < 15 мин за 28 дней». Исчерпание Error Budget — сигнал для профилирования, а не паника при единичном всплеске.
13. **Correlation ID / Trace ID в логах:** каждый запуск пайплайна и каждая стадия должны иметь уникальный идентификатор. Это позволяет связать `perf.data` с конкретным запуском и искать регрессии по `trace_id`.
14. **Графики Queue Time и Runner Saturation:** в Grafana как базовый дашборд. Рост Queue Time при стабильной нагрузке — сигнал capacity planning, не профилирования.

### Связь с другими дисциплинами

15. **Pipeline Observability:** трейсы, SLI/SLO, Golden Signals — источник метрик для решения «где профилировать». См. **[Наблюдаемость пайплайнов](./pipeline_observability.md)**.
16. **Load Shedding:** лимиты раннера (`LimitNOFILE`, `concurrent`, cgroup) — часть инфраструктурного shedding. См. **[Сброс нагрузки (Load Shedding)](./load_shedding.md)**.
17. **Linux Performance Diagnostics:** системный профайлинг `perf`, анализ потоков, `strace` — в **[Траблыhooting CPU/памяти потоков](../../Linux/Diagnostics/Processes/thread_cpu_troubleshooting.md)**.

## Дополнительная информация

### См. также

- [Наблюдаемость пайплайнов](./pipeline_observability.md) — SLI/SLO, трейсы, метрики для решения о профилировании.
- [Сброс нагрузки (Load Shedding)](./load_shedding.md) — sysadmin-лимиты и паттерн надёжности для раннеров.
- [Траблыhooting CPU/памяти потоков](../../Linux/Diagnostics/Processes/thread_cpu_troubleshooting.md) — perf, pprof, py-spy, async-profiler, gdb, strace.
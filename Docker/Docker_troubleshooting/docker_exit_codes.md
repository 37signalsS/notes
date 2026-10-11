# Коды завершения контейнеров (Docker Exit Codes)

**Актуально для:** Docker Engine 20.10+ (поддержка cgroup v2) / Docker Desktop 4.33+ (`docker debug`); сами коды выхода POSIX-стабильны и не меняются между версиями Docker

## Определения

**Код завершения (Exit Code)** — целочисленное значение (0–255), возвращаемое главным процессом контейнера (**PID 1**) операционной системе при завершении работы. Docker транслирует этот код без изменений для информирования пользователя или оркестратора о результате выполнения задачи.

- **`0`** — успешное завершение (Success).
- **`1–255`** — завершение с ошибкой или по внешнему сигналу.

Коды подчиняются POSIX-семантике оболочки: значение всегда укладывается в один байт (`exit 256` → `0`, `exit 300` → `44`).

## Основные концепции

### Два уровня кодов: CLI/daemon и контейнер

Код, возвращаемый командой `docker run`, имеет два источника (документация `docker run` → «Exit status»; исходный код `docker/cli`, функция `toStatusError`):

| Код | Уровень | Значение |
| :--- | :--- | :--- |
| **125** | CLI/daemon | Ошибка самого Docker Engine: некорректный флаг, недоступный демон, ошибка API |
| **126** | Запуск контейнера | Команда найдена, но не может быть исполнена (`EACCES` — нет прав; `EISDIR` — попытка exec директории) |
| **127** | Запуск контейнера | Команда не найдена (`executable file not found in $PATH`, `no such file or directory`; несовпадение типов при монтировании — файл на директорию) |
| **128** | Запуск контейнера | Неизвестная ошибка при старте контейнера (daemon, `exitUnknown` в `daemon/errors.go`) |
| **прочие** | Контейнер | Код завершения команды внутри контейнера — транслируется как есть |

```bash
docker run --foo busybox; echo $?
# → flag provided but not defined: --foo
# → 125

docker run busybox /etc; echo $?
# → exec: "/etc": permission denied
# → 126

docker run busybox foo; echo $?
# → exec: "foo": executable file not found in $PATH
# → 127

docker run busybox /bin/sh -c 'exit 3'; echo $?
# → 3
```

### Классификация кодов завершения

| Код | Описание | Типичный источник |
| :--- | :--- | :--- |
| **0** | Успешное выполнение задачи | Приложение завершило работу штатно |
| **1** | Общая ошибка (Catch-all) | Ошибка в коде, отсутствие файла, сбой рантайма |
| **2** | Ошибка синтаксиса Shell | Ошибка в скрипте entrypoint (неверные скобки и т.д.) |
| **125** | Ошибка Docker Engine | Сбой при запуске `docker run` (например, конфликт флагов) |
| **126** | Ошибка прав доступа | Команда найдена, но нет прав на выполнение (`chmod -x`) |
| **127** | Команда не найдена | Исполняемый файл отсутствует в образе или в `$PATH` |
| **128** | Служебный код | В Docker — неизвестная ошибка при старте контейнера; в shell — зарезервирован для внутренних целей |
| **128+N** | Завершение по сигналу `N` | Ядро Linux отправило сигнал (SIGKILL, SIGTERM и др.) |
| **255** | Код, заданный приложением | Часто используется CLI-утилитами как «общая ошибка» (например, SSH); сам по себе в диапазоне 0–255 |

### Формула сигналов (128 + N)

Если процесс принудительно завершён ядром или внешней утилитой, код рассчитывается как `128` + номер сигнала `N`.

| Код | Сигнал (N) | Название | Причина |
| :--- | :--- | :--- | :--- |
| **130** | 2 | **SIGINT** | Прерывание пользователем (`Ctrl+C`) |
| **131** | 3 | **SIGQUIT** | Экстренный выход с дампом памяти (core dump) |
| **134** | 6 | **SIGABRT** | Аварийное завершение (`abort()`, assertion failure в C/C++) |
| **137** | 9 | **SIGKILL** | Принудительная остановка (**OOMKilled**, `docker kill`, таймаут `docker stop`) |
| **138** | 7 | **SIGBUS** | Ошибка шины (некорректное выравнивание, ошибка маппинга файла) |
| **139** | 11 | **SIGSEGV** | Segmentation Fault (попытка доступа к чужой памяти) |
| **141** | 13 | **SIGPIPE** | Запись в закрытый канал связи |
| **143** | 15 | **SIGTERM** | Запрос на корректное завершение (`docker stop`) |

### Как Docker останавливает контейнер (143 → 137)

`docker stop` выполняет двухфазное завершение:

1. Отправляет `SIGTERM` (или сигнал из `STOPSIGNAL` / `--stop-signal`) процессу PID 1.
2. Ждёт grace period: **10 секунд** для Linux (30 для Windows), настраивается через `--stop-timeout` при создании или `-t/--timeout` при остановке.
3. Если процесс не завершился — отправляет `SIGKILL`, контейнер получает код **137**.

Сама команда `docker stop` **всегда возвращает 0** — даже если потребовался SIGKILL. Код 137 виден только в `docker ps -a`, `docker inspect` и `docker wait`. Для бесконечного ожидания: `docker stop -t -1 <id>`.

Интерпретация результата остановки:

| Поведение | Код | Вывод |
| :--- | :--- | :--- |
| Быстрая остановка | **0** | PID 1 обработал SIGTERM и завершился штатно (лучший случай) |
| Быстрая остановка | **143** | SIGTERM доставлен и обработан (приложение завершилось по сигналу) |
| Ожидание до таймаута | **137** | PID 1 игнорирует SIGTERM — применён SIGKILL |

### cgroup v2 и «тихий» OOM

В cgroup v2 параметр `memory.oom.group` по умолчанию равен `0`: при превышении `memory.max` ядро убивает **один** процесс с наивысшим `oom_score` в контрольной группе — часто это дочерний процесс, а не PID 1.

- **Silent OOM (тихий OOM):** PID 1 остаётся жив, контейнер имеет статус `Up`, но приложение работает некорректно. `docker inspect` покажет `OOMKilled: false` — флаг выставляется только при убийстве основного процесса.
- **Групповой OOM:** при `memory.oom.group=1` ядро убивает все процессы группы — контейнер завершается с кодом **137**.

**Важно:** Docker **не предоставляет** флага для установки `memory.oom.group` (флаг `--cgroup-conf` существует только в Podman). Для группового OOM используйте Podman (`--cgroup-conf=memory.oom.group=1`) или настройку systemd-slice. Флаг `--oom-kill-disable` с cgroup v2 **не поддерживается** (игнорируется с предупреждением), а на cgroup v1 требует обязательного `-m/--memory`; документация Docker не рекомендует его применение.

## Практические сценарии

### Сценарий 1: Глубокая диагностика состояния

Для получения полной информации о причинах остановки используйте расширенный формат `inspect`:

```bash
docker inspect <container_id> --format 'Status: {{.State.Status}}, ExitCode: {{.State.ExitCode}}, Error: "{{.State.Error}}", OOM: {{.State.OOMKilled}}, Restarts: {{.RestartCount}}, Finished: {{.State.FinishedAt}}'
# → Status: exited, ExitCode: 137, Error: "", OOM: true, Restarts: 0, Finished: 2026-10-03T18:00:00.000000000Z
```

Нюансы:
- Пока контейнер запущен, `{{.State.ExitCode}}` возвращает `0` — код появляется только после завершения.
- Флаг `OOMKilled` сохраняется в состоянии контейнера до следующего старта — найденное `true` может быть от вчерашнего OOM. Сверяйте с временными метками `dmesg`.
- `docker run --rm` удаляет контейнер при выходе — для диагностики кода запускайте без `--rm` (сам код при этом в `$?` передаётся корректно).
- `{{.State.Error}}` содержит сообщение runtime (например, `OCI runtime create failed: ...`), если контейнер не смог стартовать.

### Сценарий 2: Код 137 — нехватка памяти (OOMKilled)

**Проблема:** Контейнер падает с кодом 137, но в логах приложения пусто.

**Диагностика в cgroup v2:**
Проверьте события памяти в контрольной группе контейнера на хосте:
```bash
# Путь зависит от дистрибутива и драйвера (systemd/cgroupfs)
cat /sys/fs/cgroup/system.slice/docker-<ID>.scope/memory.events
# → oom 1
# → oom_kill 1
# → oom_group_kill 0
```

На хостах с cgroup v1:
```bash
cat /sys/fs/cgroup/memory/docker/<ID>/memory.oom_control
# → oom_kill 1
```

Дополнительно: `dmesg | grep -i 'killed process'` — записи OOM Killer с указанием `memcg:/docker/<ID>`.

**Интерпретация:**
- `OOMKilled: true` — ядро убило PID 1 по лимиту памяти (проверьте `dmesg` по времени — флаг сохраняется до следующего старта).
- `OOMKilled: false`, но контейнер `Up` и приложение деградировало — «тихий OOM»: убит дочерний процесс. Подтверждение — счётчик `oom_kill` в `memory.events` при живом контейнере.
- `OOMKilled: false` и контейнер `exited` со кодом 137 — сигнал `SIGKILL` отправлен вручную (`docker kill`), истёк таймаут `docker stop` или перезапущен демон (все три дают 137).

**Решение:**
1. Проверьте лимиты: `docker inspect <id> --format 'Memory: {{.HostConfig.Memory}}, Swap: {{.HostConfig.MemorySwap}}'` (в байтах).
2. Увеличьте `--memory` / `--memory-swap` или устраните утечку памяти.
3. Мягкий лимит `--memory-reservation` активируется при конкуренции за память на хосте.
4. Мониторинг: `docker stats --no-stream` и алерты на событие `oom` (`docker events --filter event=oom`).

### Сценарий 3: Код 143/137 — таймаут при остановке

**Проблема:** При выполнении `docker stop` контейнер висит 10 секунд и выходит с кодом 137.

**Причина:** Процесс PID 1 не перехватывает сигнал `SIGTERM`. Это часто происходит, когда приложение запускается через shell-форму (`CMD my-app`) без использования `exec` — оболочка не пробрасывает сигналы дочернему процессу.

**Решение:**
Используйте JSON-формат в Dockerfile, чтобы приложение запускалось как PID 1 напрямую:
```dockerfile
# Правильно
CMD ["node", "app.js"]

# Неправильно (создает лишний процесс /bin/sh)
CMD node app.js
```

Дополнительные инструменты:
- `docker run --init` — init-процесс (tini) пробрасывает сигналы и собирает зомби (см. [init_process_tini.md](../Dockerfile/init_process_tini.md)).
- `STOPSIGNAL` в Dockerfile или `--stop-signal` — если приложение ожидает другой сигнал (например, `SIGQUIT`).
- `--stop-timeout 60` при создании или `docker stop -t 60 <id>` — для приложений с медленным graceful shutdown.
- `docker kill --signal=SIGTERM <id>` — отправить SIGTERM без периода ожидания.

### Сценарий 4: Код 126 — ошибки исполнения

**Проблема:** Контейнер не запускается, код 126.

**Причины:**
1. Отсутствие прав на выполнение у скрипта (не выполнен `chmod +x`).
2. Файловая система примонтирована с опцией `noexec` (часто встречается в `/tmp` или на внешних томах).
3. Попытка exec директории (`EISDIR`).

**Диагностика:**
```bash
docker run --rm <image> ls -la /app/entrypoint.sh
# → -rw-r--r-- 1 root root 123 ... /app/entrypoint.sh  (нет x!)
```

**Решение:** `RUN chmod +x /app/entrypoint.sh` в Dockerfile или `ENTRYPOINT ["/app/entrypoint.sh"]` с проверкой прав.

### Сценарий 5: Код 127 — ошибка путей и образов

**Проблема:** Ошибка `executable file not found in $PATH`.

**Диагностика:**
Убедитесь, что бинарный файл действительно находится в образе. Используйте `docker debug` (Docker Desktop 4.33+) для проверки ФС даже в distroless-образах:
```bash
docker debug <container_id> --command "ls -la /usr/local/bin"
```

**Дополнительные причины:**
- Опечатка в `ENTRYPOINT`/`CMD` или неверный `WORKDIR`.
- Несовместимость архитектуры (amd64-образ на arm64-хосте без эмуляции) — контейнер не стартует с ошибкой `exec format error`.
- Несовпадение типов при монтировании: файл смонтирован на директорию (или наоборот) — Docker дополняет ошибку подсказкой «Are you trying to mount a directory onto a file (or vice-versa)?».

### Сценарий 6: Цикл перезапусков (crash loop)

**Проблема:** Контейнер постоянно перезапускается (`restart: on-failure` / `always`).

**Диагностика:**
```bash
docker ps --filter status=restarting
docker inspect <id> --format 'Restarts: {{.RestartCount}}, ExitCode: {{.State.ExitCode}}'
docker logs --since 10m <id>
```

**Решение:** найдите первопричину по коду выхода (см. таблицу ниже), отладьте вручную без политики перезапуска:
```bash
docker run --restart=no <image>   # без --rm, если нужен inspect после падения
```

Аналог в Kubernetes — `CrashLoopBackOff` (см. [definitions_and_concepts.md](../../Kubernetes/Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md)).

### Сценарий 7: Compose — пропагация кодов выхода

**Проблема:** в CI/CD нужно вернуть код выхода тестового сервиса из всего стека.

**Решение:**
```bash
# Остановить все контейнеры при завершении любого и вернуть код сервиса tests
docker compose up --abort-on-container-exit --exit-code-from tests

# Compose v2.27+: не снимать стек при успешном завершении побочных сервисов
docker compose up --abort-on-container-failure --exit-code-from tests

# Compose v2.20+: дождаться остановки и вывести коды всех сервисов
docker compose wait

# Список завершившихся сервисов (--all обязателен: без него видны только running)
docker compose ps --all --status=exited
```

Нюансы:
- `--exit-code-from` **включает** `--abort-on-container-exit` — любой остановившийся контейнер (даже успешно завершившийся мигратор) снимает весь стек. С v2.27 флаг `--abort-on-container-failure` меняет это поведение: успешные завершения игнорируются.
- `docker compose up` возвращает `1` при ошибке и `0` при прерывании (`Ctrl+C`).
- Для разовых задач: `docker compose run --rm <service>` — поднимает зависимости, выполняет команду, передаёт код в `$?`.
- `docker run --rm <image>` в скриптах корректно передаёт код в `$?` — `--rm` не влияет на пропагацию.

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `docker wait <id>` | Блокировка до остановки, вывод exit code | `docker wait my-app` → `137` |
| `docker ps -a --filter 'exited=<code>'` | Фильтр контейнеров по коду выхода | `docker ps -a --filter 'exited=137'` |
| `docker events --filter event=die` | События завершения с атрибутом `exitCode` | см. [debugging_with_docker_events.md](./debugging_with_docker_events.md) |
| `docker events --filter event=oom` | События OOM контрольных групп | `docker events --filter event=oom --since 1h` |
| `docker stop -t <sec> <id>` | Остановка с кастомным таймаутом | `docker stop -t 60 my-app` |
| `docker stop -s <signal> <id>` | Остановка с другим начальным сигналом | `docker stop -s SIGINT my-app` |
| `docker kill --signal=<signal> <id>` | Отправка произвольного сигнала | `docker kill --signal=SIGTERM my-app` |
| `docker run --stop-timeout <sec>` | Таймаут остановки при создании | `docker run --stop-timeout 60 my-app` |
| `docker run --stop-signal <signal>` | Сигнал остановки при создании | `docker run --stop-signal SIGQUIT my-app` |
| `docker run --init` | Init-процесс (tini) для сигналов и зомби | `docker run --init my-app` |
| `docker run --restart=on-failure[:N]` | Авто-перезапуск по ненулевому коду | `docker run --restart=on-failure:5 my-app` |
| `docker compose up --exit-code-from <svc>` | Код выхода сервиса из всего стека | см. Сценарий 7 |

## Устранение неполадок

| Код | Первое действие | Что искать |
| :--- | :--- | :--- |
| **0** | `docker ps -a` | Контейнер завершился штатно (ожидаемо для batch-задач) |
| **1** | `docker logs` | Stacktrace, ошибки конфигурации, нехватка файлов |
| **2** | `docker logs` | Синтаксическая ошибка в скрипте entrypoint |
| **125** | `docker info`, флаги команды | Ошибка демона, некорректный флаг `docker run` |
| **126** | `ls -l` на хосте/образе | Флаг исполнения (`x`), опции монтирования ФС (`noexec`), exec директории |
| **127** | `docker inspect` / `docker debug` | Опечатки в `ENTRYPOINT` или `CMD`, `$PATH`, архитектура образа |
| **128** | `docker inspect --format '{{.State.Error}}'` | Неизвестная ошибка при старте контейнера |
| **130** | `docker events` | `Ctrl+C` в attached-режиме |
| **134** | `docker logs`, core dump | `abort()`, assertion failure в нативном коде |
| **137** | `dmesg`, `memory.events`, `{{.State.OOMKilled}}` | OOM Killer, `docker kill`, таймаут `docker stop`, перезапуск демона |
| **138** | Профилирование памяти | Ошибка шины, некорректное выравнивание |
| **139** | Профилирование памяти | Ошибки в нативных библиотеках (C/C++ extensions) |
| **141** | `docker logs` | Запись в закрытый pipe (broken pipe) |
| **143** | Проверка PID 1 | Наличие `exec` в entrypoint и обработка сигналов |
| **255** | `docker logs` | Код, заданный приложением (часто — общая ошибка CLI) |

## Лучшие практики

1. **Exec-форма CMD/ENTRYPOINT** — `CMD ["app"]` вместо `CMD app`: PID 1 получает сигналы напрямую, `docker stop` завершается кодом 143, а не 137 после таймаута.
2. **Init-процесс** — `docker run --init` или tini для проброса сигналов и сбора зомби, если приложение не может быть PID 1.
3. **Не используйте `--rm` при отладке** — контейнер удаляется при выходе, и `docker inspect` станет недоступен.
4. **Настройте `STOPSIGNAL` и `--stop-timeout`** для приложений с медленным graceful shutdown (Java-сервисы, миграции БД, большие кэши).
5. **Мониторьте события `die`** с атрибутом `exitCode` и события `oom` — раннее обнаружение OOM и crash loop.
6. **Лимиты памяти** — задавайте `--memory` (и `--memory-swap`) для критичных сервисов; отслеживайте `memory.events` на хосте.
7. **Пропагация кодов в CI/CD** — `docker compose up --exit-code-from` или `docker compose wait` вместо парсинга логов.
8. **Очистка** — `docker container prune --filter "until=24h"` для остановленных контейнеров; `docker system df -v` для контроля диска.

## Дополнительная информация

### См. также

- **[Коды завершения Linux](../../Linux/Shell/exit_codes.md)** — общие стандарты кодов возврата.
- **[Сигналы процессов в Linux](../../Linux/Core/processes/signals.md)** — детальный разбор SIGTERM, SIGKILL и др.
- **[STOPSIGNAL и HEALTHCHECK](../Dockerfile/Instructions/health_signals.md#сигнал-остановки-stopsignal)** — переопределение сигнала остановки.
- **[Init-процесс tini](../Dockerfile/init_process_tini.md)** — проброс сигналов и remapping кодов.
- **[Docker Debug](./docker_debug.md)** — инструмент для анализа состояния контейнеров.
- **[Диагностика через Docker Events](./debugging_with_docker_events.md)** — интерпретация кодов в событиях `die`.
- **[Зависшие контейнеры](./hung_containers.md)** — контейнер `Up`, но не отвечает; `docker stop` висит.
- **[Ошибки docker exec](./docker_exec_failures.md)** — «Container is not running», TTY, distroless.
- **[Ограничение ресурсов](../Docker_security/resource_limits.md)** — память, CPU, OOM.
- **[OOM Killer](../../Linux/Core/processes/oom_killer_mechanism.md)** — механизм OOM. В Docker: `memory.events` (cgroup v2) для подтверждения OOM без `dmesg`, silent OOM когда убит дочерний процесс но PID 1 жив.
- **[Disk Space Issues](../../Linux/Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md)** — диагностика диска. В Docker: `docker system df -v`, `docker system prune -a --volumes`, проблема с логами `json-file` без ротации.

**Глубокое изучение:**
- **[CrashLoopBackOff (Kubernetes)](../../Kubernetes/Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md)** — полный разбор причин. В Docker аналог: контейнер перезапускается по `--restart=always/on-failure`. Диагностика: `docker inspect` → `RestartCount`, `docker logs --since`, проверка `docker ps -a` для exited контейнеров.

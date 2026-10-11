# Диагностика зависших контейнеров (Hung Containers)

**Актуально для:** Docker Engine 20.10+ (cgroup v2). В 20.10+ (PR moby/moby#41586) `docker stop` возвращает ошибку вместо бесконечного зависания; баг потери exit-event (moby/moby#51028) **всё ещё открыт** — воспроизводится на 28.0.4 (2026)

## Определения

**Зависший контейнер (Hung Container)** — контейнер со статусом `Up`, который не отвечает на запросы: PID 1 жив, но приложение не обрабатывает трафик, не реагирует на сигналы или потребляет 100% CPU. Отличается от `exited` (процесс завершился) и `paused` (заморожен cgroup-freezer).

**D-state (TASK_UNINTERRUPTIBLE)** — состояние процесса в ядре Linux: непрерывный сон, обычно ожидание I/O. Процесс в D-state **нельзя прервать никаким сигналом, включая SIGKILL**, пока он не выйдет из этого состояния сам. Это фундаментальное ограничение ядра, а не баг Docker (подтверждено мейнтейнерами moby, issue moby/moby#37886, закрыт как ожидаемое поведение).

**Зомби-процесс** — завершённый дочерний процесс, которого PID 1 не «собрал» (`wait()`). В `docker top` виден как `<defunct>`.

## Основные концепции

### Почему контейнер «Up», но не работает

| Причина | Механизм |
| :--- | :--- |
| **Приложение зависло** | Deadlock, бесконечный цикл, блокировка на внешнем ресурсе (БД, DNS) |
| **D-state** | PID 1 или рабочий процесс ждёт I/O (сеть, диск, NFS); SIGKILL не доставляется |
| **Silent OOM** | Дочерний процесс убит OOM Killer, PID 1 жив (cgroup v2, `memory.oom.group=0`) — см. **[Коды завершения](./docker_exit_codes.md)** |
| **100% CPU** | Бесконечный цикл или thrashing; контейнер «жив», но не обслуживает запросы |
| **Paused** | Контейнер заморожен (`docker pause`, cgroup freezer) — все процессы остановлены |
| **Демон/containerd wedged** | Сам CLI зависает на `exec`/`stats`/`top`/`logs` — проблема на стороне демона, а не приложения (Сценарий 4) |

### Как Docker останавливает контейнер

`docker stop` отправляет SIGTERM (или `STOPSIGNAL`) PID 1, ждёт grace period (**10 секунд** для Linux, настраивается через `-t/--time`), затем SIGKILL. Поведение демона (проверено по исходникам `daemon/kill.go`, ветка v28.x):

- В логах демона при неудаче: `Container <id> failed to exit within 10 seconds of signal 15 - using the force`.
- Голый `docker kill` (без `--signal`) — это SIGKILL **с ожиданием**: 10 секунд, затем прямой kill процесса, затем 2 секунды ожидания exit-event. Если событие не пришло — ошибка `cannot kill container: <name>: tried to kill container, but did not receive an exit event` (moby/moby#51028).
- `docker kill --signal=<SIG>` (любой сигнал, кроме SIGKILL) **отправляет сигнал и возвращается сразу**, не дожидаясь завершения.
- **Paused-контейнер**: `docker stop`/`docker kill` сначала размораживают его — сигнал доставляется после resume.
- **Restarting-контейнер**: сигнал процессу не отправляется вовсе — демону достаточно указать монитору завершиться на следующем цикле (`docker kill` на таком контейнере возвращает успех, не делая ничего).
- Сама команда `docker stop` **всегда возвращает 0** — даже если потребовался SIGKILL; код 143/137 виден только в `docker inspect` и `docker ps -a` (см. **[Коды завершения](./docker_exit_codes.md)**).

**Ключевой вывод:** если PID 1 в D-state, единственные пути — дождаться завершения I/O или перезагрузить хост. Перезапуск `dockerd` **не убивает** D-state-процесс (контейнеры живут в containerd-shim независимо от демона) — он помогает только когда wedged сам демон (Сценарий 4). Перезапуск `dockerd` затрагивает **все** контейнеры на хосте.

### Что проверять в первую очередь

1. `docker inspect my-app --format '{{.State.Status}} {{.State.Health.Status}}'` — статус и healthcheck (`unhealthy` часто первый признак «живого, но неработающего» контейнера).
2. `docker logs --since 10m my-app` — есть ли вывод, когда последняя строка?
3. `docker top my-app` — состояния процессов (R/S/D/Z).
4. `docker stats --no-stream my-app` — CPU/RAM/IO.
5. `docker exec my-app echo alive` — отвечает ли контейнер на новые процессы (если exec работает — ядро живо, проблема в приложении).
6. Хост: `dmesg`, `iostat -x 1`, `journalctl -u docker -u containerd --since 10m`.

## Практические сценарии

### Сценарий 1: Контейнер «Up», но сервис не отвечает

```bash
# 1. Статус и healthcheck
docker inspect my-app --format '{{.State.Status}} / health: {{.State.Health.Status}}'
# → running / health: unhealthy

# 2. Логи — последние строки за период
docker logs --since 10m --tail 50 my-app
# → (пусто или обрыв на середине запроса)

# 3. Процессы внутри контейнера (ps выполняется на хосте)
docker top my-app
# → PID   USER     TIME  COMMAND
# → 1234  root     0:00  /app/server
# → 1235  root     0:00  [worker] <defunct>      ← зомби

# 4. Ресурсы
docker stats --no-stream my-app
# → CONTAINER  CPU %  MEM USAGE / LIMIT  ...
# → my-app     0.05%  45MiB / 512MiB

# 5. Отвечает ли контейнер на exec?
docker exec my-app echo alive
# → alive   ← ядро и namespaces живы, проблема в приложении
```

Если `docker exec` тоже зависает — процесс в D-state или wedged демон/containerd (Сценарии 2 и 4).

### Сценарий 2: Процесс в D-state (непрерывный сон)

```bash
# 1. PID процесса PID 1 контейнера на хосте
docker inspect my-app --format '{{.State.Pid}}'
# → 1234

# 2. Состояние процесса
ps -o pid,stat,comm,wchan -p 1234
# → PID   STAT  COMMAND  WCHAN
# → 1234  D     server   rpc_wait_bit_killable   ← D-state, ждёт NFS/сеть

# 3. Детально
cat /proc/1234/status | grep State
# → State: D (disk sleep)

# 4. Стек ядра (требует root)
sudo cat /proc/1234/stack
# → [<0>] rpc_wait_bit_killable+0x.../0x...

# 5. I/O на хосте
iostat -x 1 3
# → высокий %util или await на диске
dmesg | tail -20
# → возможны ошибки NFS/блочного устройства
```

**Решение:** устранить причину блокировки I/O (сеть/NFS/диск). SIGKILL не поможет — это свойство ядра. Если I/O не восстанавливается — только перезагрузка хоста (Сценарий 3).

**Нюанс (moby/moby#51028):** потеря exit-event воспроизводится не только с D-state PID 1 — D-state **дочерних** процессов контейнера тоже вызывает ошибки `docker stop`/`kill`/`rm -f` в нагруженных средах.

### Сценарий 3: `docker stop`/`kill`/`rm` висит или возвращает ошибку kill

```bash
# Симптом: команда не возвращается или:
docker stop my-app
# → Error response from daemon: cannot kill container: my-app:
#   tried to kill container, but did not receive an exit event

# Та же ошибка может быть и при принудительном удалении:
docker rm -f my-app
# → Error response from daemon: cannot remove container "my-app":
#   could not kill container: tried to kill container, but did not receive an exit event

# 1. Проверить, не D-state ли процесс (Сценарий 2)
# 2. Принудительный kill (SIGKILL + ожидание, аналогично docker stop без grace)
docker kill my-app

# 3. Контейнер застрял в restarting? (см. Сценарий 5)
docker inspect my-app --format '{{.State.Status}} restarts: {{.RestartCount}}'

# 4. Если и kill не помогает — прямой kill runc-init на хосте
#    (workaround из moby/moby#47554: runc init — это PID 1 контейнера на хосте)
ps -ef | grep -E 'runc.*<container-id>'
sudo kill -9 <runc-init-pid>

# 5. Крайняя мера — перезапуск демона
#    ВНИМАНИЕ: останавливает ВСЕ контейнеры на хосте!
sudo systemctl restart docker

# 6. Истинная крайняя мера — перезагрузка хоста
sudo reboot
```

**Диагностика демона во время зависания:** `journalctl -u docker -f` — строки `failed to exit within 10 seconds of signal 15 - using the force` и ошибки `Error killing the container`.

**Об автоматизации:** ошибка из moby/moby#51028 непостоянна (таймаут 2 секунды на ack события). В CI/скриптах — короткий retry с backoff (2–3 попытки, 0.5–1 с) фильтрует её в большинстве случаев; воспроизводится и на пустой системе при параллельных вызовах lifecycle-команд одному демону.

### Сценарий 4: Зависает сам CLI (`exec`, `stats`, `top`, `logs`)

Если **все** команды к контейнеру (и даже `docker info`) висят — проблема не в приложении, а в демоне или containerd:

```bash
# 1. Демон отвечает?
timeout 10 docker info
# → таймаут команды → демон wedged

# 2. containerd жив?
systemctl status containerd
journalctl -u containerd --since 10m
# → недоступен: dockerd теряет exit-events, контейнеры «зависают»
#    (moby/moby#46451: kill/rm возвращают ошибку через ~10 секунд,
#     интерактивный `exit` в контейнере зависает навсегда)

# 3. Снимок goroutine демона (нужен debug-режим dockerd)
curl --unix-socket /var/run/docker.sock http://./debug/pprof/goroutine?debug=2 > /tmp/dockerd-goroutines.txt

# 4. Стек застрявшего shim (рекомендация мейнтейнеров, moby/moby#38092):
#    SIGUSR1 в docker-containerd-shim дампит стек в логи dockerd
ps -ef | grep containerd-shim | grep <container-id>
sudo kill -USR1 <shim-pid>
journalctl -u docker --since 1m
```

**Решение:** восстановить containerd (`systemctl restart containerd`) или перезапустить `dockerd` — контейнеры при этом продолжают жить (shim независим от демона), но если wedged shim самого контейнера, помогает только `kill -9` его процессов или перезагрузка хоста (moby/moby#38092: единственный надёжный способ — перезагрузка сервера).

### Сценарий 5: Контейнер застрял в `Restarting`

```bash
docker inspect my-app --format '{{.State.Status}} / restarts: {{.RestartCount}} / error: {{.State.Error}}'
# → restarting / restarts: 7 / error: ...

# Симптом: stop/rm на таком контейнере:
docker stop my-app
# → Error response from daemon: cannot stop container: my-app:
#   tried to kill container, but did not receive an exit event
```

**Причина:** контейнер с restart-политикой (`always`/`unless-stopped`) попал в гонку при перезапуске (moby/moby#47554, воспроизводится с v25.x). `docker kill` на `restarting`-контейнере сигнала не отправляет вообще (см. «Как Docker останавливает контейнер»).

**Решение:**

```bash
# 1. Выключить автоперезапуск, чтобы вырваться из цикла
docker update --restart=no my-app

# 2. Прямой kill runc-init (Сценарий 3, шаг 4) или dockerd
# 3. После восстановления — вернуть политику
docker update --restart=unless-stopped my-app
```

### Сценарий 6: Зомби-процессы (PID 1 не реапитит)

```bash
docker top my-app
# → PID   USER  TIME  COMMAND
# → 1     root  0:00  /app/server
# → 5678  root  0:00  [curl] <defunct>
# → 5679  root  0:00  [curl] <defunct>
```

**Причина:** PID 1 не вызывает `wait()` для дочерних процессов. Типично, когда приложение (Python, shell-скрипт) запускается как PID 1 без init-семантик.

**Решение:** init-процесс — `docker run --init` или `tini` (см. **[Init-процесс tini](../Dockerfile/init_process_tini.md)**), либо exec-форма `CMD` в Dockerfile.

### Сценарий 7: Контейнер потребляет 100% CPU

```bash
# 1. Какой контейнер
docker stats --no-stream
# → my-app   398.50%   ...

# 2. Какой процесс внутри
docker top my-app -eo pid,pcpu,comm --sort=-pcpu | head
# → PID   %CPU  COMMAND
# → 1235  395   worker

# 3. Профилирование приложения (если есть shell)
docker exec my-app top -b -n 1 | head -15
```

**Решение:** лимиты CPU (`--cpus`, `--cpuset-cpus`, см. **[Лимиты ресурсов](../Docker_security/resource_limits.md)**), профилирование приложения, исправление бесконечного цикла.

### Сценарий 8: Контейнер в состоянии paused

```bash
docker ps
# → my-app   Up 2 hours (Paused)

# Причина: docker pause, cgroup freezer или отладочный снапшот
docker unpause my-app
# → my-app
```

**Проверка:** `docker inspect my-app --format '{{.State.Status}}'` → `paused`. После `unpause` процессы продолжаются с момента заморозки. `docker stop`/`docker kill` на paused-контейнере работают — демон размораживает его как часть остановки.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Контейнер `Up`, сервис не отвечает, `exec` работает | Приложение зависло (deadlock, внешний ресурс) | `docker logs`, `docker top`, профилирование приложения |
| `docker exec` зависает | Процесс в D-state или демон перегружен | `ps -o stat -p {{.State.Pid}}`; `iostat`; `journalctl -u docker` |
| `docker stop` висит / `cannot kill container ... did not receive an exit event` | D-state (непрерывный сон) или баг демона (moby#51028) | `docker kill`; retry с backoff в автоматизации; при неудаче — `kill -9` runc-init или `systemctl restart docker` (все контейнеры!) |
| `docker rm -f` → `could not kill container` | То же, что и выше (moby#46451, #51845) | Сценарий 3; проверить `systemctl status containerd` |
| `docker stop` возвращает `Container failed to stop after sending SIGKILL` | SIGKILL не доставлен (D-state) | Сценарий 2: устранить блокировку I/O |
| Все CLI-команды к контейнеру висят, `docker info` не отвечает | Wedged dockerd/containerd | Сценарий 4: pprof-дамп, `systemctl status containerd` |
| Контейнер в `restarting`, stop/rm ошибаются | Гонка при перезапуске (moby#47554, с v25.x) | Сценарий 5: `docker update --restart=no`, `kill -9` runc-init |
| `<defunct>` в `docker top` | PID 1 не собирает зомби | `docker run --init` / tini (см. **[init_process_tini.md](../Dockerfile/init_process_tini.md)**) |
| Контейнер `(Paused)` | Заморожен cgroup-freezer | `docker unpause` |
| 100% CPU в `docker stats` | Бесконечный цикл / thrashing | Лимиты CPU, профилирование (см. **[resource_limits.md](../Docker_security/resource_limits.md)**) |
| Контейнер «жив», но приложение деградировало, `OOMKilled: false` | Silent OOM (убит дочерний процесс) | `memory.events` на хосте — см. **[docker_exit_codes.md](./docker_exit_codes.md)** |

## Валидация

```bash
# 1. Контейнер отвечает
docker exec my-app echo alive
# → alive

# 2. Healthcheck в норме
docker inspect my-app --format '{{.State.Health.Status}}'
# → healthy

# 3. Процессы в нормальном состоянии (S/R, не D)
docker top my-app -o pid,stat,comm
# → PID   STAT  COMMAND
# → 1234  S     /app/server

# 4. Ресурсы в норме
docker stats --no-stream my-app
# → CPU % < 100, MEM в пределах лимита

# 5. Остановка завершается штатно
docker stop -t 30 my-app
# → my-app (CLI возвращает 0; код контейнера в inspect: 143 — обработан SIGTERM,
#   137 — не успел и получил SIGKILL; см. docker_exit_codes.md)
```

## Лучшие практики

1. **Healthcheck + autoheal** — `unhealthy`-статус ловит «живой, но не работающий» контейнер раньше, чем ручная диагностика (см. **[health_signals.md](../Dockerfile/Instructions/health_signals.md)** и **[docker_autoheal.md](./docker_autoheal.md)**).
2. **`--init` для приложений, не умеющих быть PID 1** — защита от зомби и корректный проброс сигналов.
3. **Лимиты ресурсов на каждый production-контейнер** — `--memory`, `--cpus`, `--pids-limit` (см. **[resource_limits.md](../Docker_security/resource_limits.md)**).
4. **Не перезапускайте `dockerd` бездумно** — `systemctl restart docker` останавливает все контейнеры на хосте; это крайняя мера, а не первый шаг. D-state-процесс переживёт и перезапуск демона.
5. **Мониторьте D-state на хосте**: алерт на `ps -eo stat | grep -c '^D'` и на `iostat` — зависания I/O почти всегда видны на хосте раньше, чем в контейнере.
6. **Graceful shutdown**: `STOPSIGNAL` + `--stop-timeout` для приложений с медленным завершением (см. **[docker_exit_codes.md](./docker_exit_codes.md)**).
7. **Timeout-обёртки в автоматизации**: `timeout 30 docker stop ...`, `timeout 10 docker exec ...` — не дают скрипту/CI-задаче зависнуть навсегда на wedged контейнере (moby#38978: зависать могут и `exec`, и `stats`, и `top`).
8. **Мониторьте containerd наравне с dockerd** — его недоступность даёт «зависшие» контейнеры с интактными процессами (moby#46451).
9. **Сериализуйте массовые lifecycle-операции** (stop/rm при деплое и очистке) — параллельные вызовы к одному демону сами по себе провоцируют moby#51028.

## Дополнительная информация

### Сравнение состояний контейнера

| Статус | PID 1 | Отвечает на exec | `docker stop` |
| :--- | :--- | :--- | :--- |
| `running` | жив | да | SIGTERM → SIGKILL |
| `running` (hung) | жив, но завис | зависает/нет | может не завершиться |
| `paused` | заморожен | нет (до unpause) | работает: сначала разморозка |
| `restarting` | в цикле | нет | сигнал не отправляется; дождаться или `docker update --restart=no` |
| `exited` | завершён | нет (см. **[docker_exec_failures.md](./docker_exec_failures.md)**) | не нужен |

### См. также

- **[Коды завершения](./docker_exit_codes.md)** — интерпретация 137/143, OOM, таймауты stop.
- **[Отладка контейнеров](./docker_debug.md)** — `docker debug` для stopped/hung контейнеров (Docker Desktop).
- **[Отладка distroless](./debugging_distroless.md)** — диагностика без shell в образе.
- **[Docker events](./debugging_with_docker_events.md)** — события `die`, `oom`, `kill` в реальном времени.
- **[Отказы демона](./docker_daemon_failures.md)** — когда проблема в самом `dockerd`, а не в контейнере.
- **[Init-процесс tini](../Dockerfile/init_process_tini.md)** — зомби и проброс сигналов.

**Глубокое изучение:**
- **[moby/moby#37886](https://github.com/moby/moby/issues/37886)** — почему Docker не может убить контейнер с процессом в D-state (позиция мейнтейнеров: «marking the container as alive is the correct behavior»).
- **[moby/moby#41586](https://github.com/moby/moby/pull/41586)** — PR: `docker stop` возвращает ошибку вместо бесконечного зависания (Docker 20.10+).
- **[moby/moby#51028](https://github.com/moby/moby/issues/51028)** — «did not receive an exit event»: открыт (2026), воспроизводится на 28.0.4; триггеры — высокий block I/O **и** просто параллельные lifecycle-вызовы.
- **[moby/moby#47554](https://github.com/moby/moby/issues/47554)** — контейнер застревает в `restarting` (с v25.x), workaround — `kill -9` runc-init.
- **[moby/moby#46451](https://github.com/moby/moby/issues/46451)** — поведение при остановленном containerd.
- **[moby/moby#38978](https://github.com/moby/moby/issues/38978)** — `docker restart`/`exec`/`stats`/`top` висят при lingering-процессах.
- **[moby/moby#38092](https://github.com/moby/moby/issues/38092)** — нереспонсивный контейнер: pprof-дампы и SIGUSR1 в shim.
- **[Docker: Оптимизация производительности](../Docker_performance_tuning.md)** — CPU pinning, CFS quota, NUMA.

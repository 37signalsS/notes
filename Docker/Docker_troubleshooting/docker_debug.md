# Отладка контейнеров (Docker Debug)

**Актуально для:** Docker Desktop 4.33+ (Docker Debug GA); Build Debugging — Docker Desktop 4.46+ / Buildx 0.29+

## Определения

**`docker debug`** — CLI-команда Docker Desktop: подключает эфемерный отладочный контейнер с Toolbox (на базе Nix) к целевому контейнеру или образу, предоставляя полноценный shell и набор инструментов даже в distroless/scratch-образах, где нет `/bin/sh`. Альтернатива `docker exec` для slim-образов.

**Toolbox** — набор предустановленных утилит (`vim`, `nano`, `htop`, `curl`, `ps`, `ip` и другие), расширяемый на лету через встроенную команду `install` из репозитория Nix (search.nixos.org).

**Build Debugging** — отладка процесса сборки через Debug Adapter Protocol (DAP), реализованный в Buildx: точки останова на инструкциях `Dockerfile`, инспекция переменных и файловой системы промежуточных слоёв, shell внутри собираемого образа.

**Ключевое преимущество:** Полная изоляция инструментов отладки от исполняемой среды приложения. Директория `/nix` не видна процессам приложения и не увеличивает размер production-образа.

## Основные концепции

### Принцип работы

При запуске `docker debug`:
- **Эфемерный контейнер:** Создаётся временный отладочный контейнер с файловой системой на базе **Nix**, содержащей Toolbox.
- **Слияние ФС (MergerFS):** Файловая система целевого контейнера/образа монтируется и объединяется (mergerfs) с файловой системой Toolbox. Утилиты Toolbox и файлы цели доступны в одном пространстве имён — например, `vim` из Toolbox редактирует файл, находящийся внутри целевого контейнера.
- **Изоляция Namespaces:** Отладочный контейнер подключается к тем же пространствам имен (PID, Network, IPC, mount), что и целевой контейнер, что даёт полный доступ к его внутреннему состоянию.
- **Zero Interference:** Инструменты отладки (директория `/nix`) физически недоступны для основного приложения, что исключает побочные эффекты.

### Инструментарий (Toolbox)

Среда отладки по умолчанию содержит: `vim`, `nano`, `htop`, `curl`, `ps`, `ip` и другие стандартные утилиты Linux.

**Встроенные команды (builtin tools):**

| Команда | Описание |
| :--- | :--- |
| `install <pkg1> <pkg2>` | Динамическая установка пакетов из репозитория Nix (например, `nmap`, `strace`); загрузка из `cache.nixos.org` |
| `uninstall <pkg1> <pkg2>` | Удаление установленных пакетов из Toolbox |
| `entrypoint` | Печать, lint и тестовый запуск entrypoint целевого объекта (`--print`, `--lint`, `--run`) |
| `builtins` | Вывод списка встроенных команд Toolbox |

### Доступность и требования

- **Версия:** Docker Desktop 4.33+ (GA, июль 2024; beta — 4.27, февраль 2024). В GUI Docker Desktop 4.29+ — переключатель Debug mode во вкладке Exec контейнера.
- **Не входит в standalone Docker Engine:** команда недоступна в docker-ce на headless Linux-серверах (закрытый плагин Docker Desktop); запрос на поддержку — docker/roadmap#893 (открыт, февраль 2026). Для удалённой отладки Engine используйте `--host` с клиента Desktop.
- **Лицензия:** на момент GA требовалась подписка Pro/Teams/Business (блог релиза 4.33). Есть неподтверждённые сообщения (форум Docker, 2026) о расширении доступности для всех пользователей Desktop — требует проверки.
- **Shell:** `bash`, `fish`, `zsh`; по умолчанию авто-детект (`--shell auto`).
- **Сеть:** `install` загружает пакеты из бинарного кэша Nix (`cache.nixos.org`), поиск пакетов — `search.nixos.org`. В закрытых контурах (air-gapped) требуется предварительное наполнение Nix-кэша.

## Практические сценарии

### Сценарий 1: Отладка distroless-контейнера

**Задача:** Получить доступ к ФС и сети образа, в котором нет даже `/bin/sh`.

```bash
docker debug my-distroless-app
# → shell с Toolbox; ФС образа доступна, хотя /bin/sh в нём отсутствует

# Внутри сессии debug:
ps aux
curl -s localhost:8080/health
```

### Сценарий 2: Остановленный контейнер (crash-loop)

**Задача:** Контейнер мгновенно падает, `docker exec` невозможен — процесс не успевает запуститься.

```bash
docker ps -a
# → my-app   Exited (1)  ...

docker debug my-app
# → shell доступен даже для остановленного контейнера;
#   изменения ФС отбрасываются при выходе — безопасная песочница для диагностики

# Внутри сессии debug:
ls -la /app
cat /app/config.yaml
```

### Сценарий 3: Отладка образа (до запуска)

**Задача:** Проверить содержимое образа и его entrypoint без запуска рабочей нагрузки.

```bash
docker debug my-app:latest
# → образ скачивается автоматически (как docker run); sandbox-shell:
#   изменения не влияют на образ

# Внутри сессии debug:
entrypoint --print
ls /usr/local/bin
```

### Сценарий 4: Горячее исправление конфигурации Nginx

**Задача:** Изменить `nginx.conf` в работающем контейнере без его перезапуска.

```bash
docker debug web-server

# Внутри сессии debug:
# Редактируем файл (vim берется из Toolbox, файл — из контейнера);
# изменения сразу видны приложению
vim /etc/nginx/nginx.conf

# Проверяем синтаксис (бинарный файл nginx берется из целевого контейнера)
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok

# Перезагружаем конфиг без остановки процесса
nginx -s reload
```

### Сценарий 5: Анализ сетевых соединений

**Задача:** Проверить доступность внешнего API изнутри контейнера.

```bash
docker debug app-container

# Устанавливаем необходимый инструмент на лету
install nmap
# → installing 'nmap-7.93' ... copying path ... from 'https://cache.nixos.org'

# Выполняем сканирование
nmap -p 443 api.external-service.com
```

### Сценарий 6: Инспекция entrypoint

**Задача:** Понять, какая команда реально запускается в контейнере (взаимодействие `ENTRYPOINT` и `CMD`).

```bash
docker debug nginx

# Внутри сессии debug:
entrypoint
# → From CMD in Dockerfile: ['nginx', '-g', 'daemon off;']
# → From ENTRYPOINT in Dockerfile: ['/docker-entrypoint.sh']
# → Lint results:
# → PASS: '/docker-entrypoint.sh' found
# → PASS: no mixing of shell and exec form
# → PASS: no double use of shell form

# Тестовый запуск entrypoint в изолированной среде отладки
entrypoint --run
# → запускает реальный entrypoint (например, nginx); остановка — Ctrl+C
```

### Сценарий 7: Скриптовый режим (--command)

**Задача:** Выполнить одну команду в среде отладки без интерактивной сессии (CI, скрипты).

```bash
docker debug --command "cat /usr/share/nginx/html/index.html" nginx
# → <!DOCTYPE html>... (аналог bash -c "arg1 arg2 ...")
```

### Сценарий 8: Удалённая отладка через --host

**Задача:** Диагностика контейнера на удаленном сервере или другом локальном Engine.

```bash
# SSH-подключение к удалённому демону
docker debug --host ssh://root@example.org my-container

# или другой локальный Engine через unix-сокет
docker debug --host=unix:///some/path/docker.sock my-container
```

### Сценарий 9: Отладка процесса сборки (Build Debugging)

**Задача:** Понять, почему инструкция `RUN npm install` завершается с ошибкой в середине сборки.

**Требования:** Docker Desktop 4.46+, Buildx ≥ 0.29, VS Code с Docker DX extension. Buildx реализует Debug Adapter Protocol — IDE подключается к сборке напрямую.

1. Конфигурация запуска (`.vscode/launch.json`):
   ```jsonc
   {
     "version": "0.2.0",
     "configurations": [
       {
         "type": "dockerfile",   // обязательно
         "request": "launch",    // обязательно
         "name": "Docker: Build",
         "dockerfile": "Dockerfile",
         "contextPath": "${workspaceFolder}",
         "target": "test",       // опционально: стадия сборки
         "stopOnEntry": true     // останов на первой строке final-стадии
       }
     ]
   }
   ```
2. Точка останка: клик по полю слева от строки (F9) — например, на `RUN npm install`.
3. F5 — сборка останавливается на breakpoint. Доступны: **Variables** (аргументы сборки, ENV базового образа), **Filesystem** (содержимое образа на этом шаге).
4. **Debug Console** → команда `exec` — открывает терминал с shell внутри собираемого образа: можно тестировать команды перед копированием их в `Dockerfile`.
5. **Важно:** изменения в этом терминале сбрасываются при переходе к следующему шагу — это песочница, а не способ фиксации результата.

**CLI-альтернатива:** `docker buildx debug build` (опции `--call`/`--check`).

**Особенности:** breakpoint срабатывает не на всех инструкциях (`ARG`, `USER` могут не останавливать сборку — ставьте точки на инструкции, меняющие состояние ФС: `RUN`, `COPY`, `WORKDIR`); F10 (step over) не входит в другие стадии, F11 (step into) — входит.

### Сценарий 10: Диагностика, когда приложение «не открывается»

**Задача:** Контейнер запущен (`docker ps` показывает `Up`), но по адресу `localhost:8080` (или внешнему IP) приложение не отвечает.

```bash
# 1. Проверяем, что порт действительно опубликован
docker ps
# → Поле PORTS должно содержать 0.0.0.0:8080->8080/tcp

# 2. Проверяем, слушает ли приложение внутри контейнера
#    (в slim-образах ss/netstat отсутствуют — используйте docker debug)
docker exec <container_id> ss -tlnp
# → Должен быть LISTEN на 0.0.0.0:8080 или 127.0.0.1:8080

# 3. Проверяем сеть контейнера
docker inspect <container_id> | jq '.[0].NetworkSettings'
# → IPAddress, Ports, NetworkMode

# 4. Если приложение слушает только 127.0.0.1 внутри контейнера,
#    внешний доступ будет недоступен. Нужно изменять конфигурацию приложения
#    на 0.0.0.0 или использовать сеть host.

# 5. Проверяем firewall на хосте
sudo iptables -L -n -v | grep -i drop
sudo ufw status

# 6. Проверяем логи на предмет падений после старта
docker logs --tail 100 <container_id>

# 7. Вход в контейнер для проверки файлов конфигурации
docker exec -it <container_id> sh
# → cat /etc/app/config.yaml
# → env | grep BIND
```

Если контейнер слушает на `127.0.0.1`, исправьте конфигурацию приложения на `0.0.0.0` и перезапустите контейнер. Для быстрой проверки без изменения конфигурации можно использовать `network_mode: host`, но это снижает изоляцию. Глубокая диагностика сетевой связности — в **[Диагностика сетевой связности](./network_connectivity_issues.md)**.

## Валидация

```bash
# 1. Команда доступна (Docker Desktop 4.33+)
docker debug --help
# → Usage: docker debug [OPTIONS] {CONTAINER|IMAGE}
# → Options: --shell, -c/--command, --host

# 2. Toolbox на месте
docker debug hello-world
docker > builtins
# → install, uninstall, entrypoint, builtins

# 3. Инспекция entrypoint
docker debug nginx
docker > entrypoint --print
# → /docker-entrypoint.sh

# 4. Скриптовый режим
docker debug --command "cat /usr/share/nginx/html/index.html" nginx
# → <!DOCTYPE html>...
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `docker: 'debug' is not a docker command` | Standalone Docker Engine (docker-ce) или Docker Desktop < 4.33 | Обновить Docker Desktop до 4.33+; на headless Linux-серверах команда недоступна — используйте debug-sidecar или `nsenter` (см. **[Отладка distroless](./debugging_distroless.md)**) |
| `install <pkg>` зависает или падает | Нет доступа к `cache.nixos.org` (прокси, air-gapped) | Настроить прокси; в закрытых контурах — предварительно наполнить Nix-кэш |
| Изменения файлов не видны приложению | Отлаживается остановленный контейнер или образ — изменения отбрасываются при выходе из shell | Для горячих правок нужен running/paused контейнер |
| `entrypoint --run` не возвращает управление | Запущен реальный entrypoint (например, `nginx -g 'daemon off;'`) | Остановка через Ctrl+C |
| Точки останка Build Debugging не срабатывают | Не все инструкции останавливают сборку (`ARG`, `USER`) | Ставить breakpoint на инструкции, меняющие состояние ФС (`RUN`, `COPY`, `WORKDIR`) |
| Windows-контейнеры | Docker Debug не поддерживает Windows-контейнеры (по состоянию на 2024) | Использовать `docker exec` (в Windows-контейнерах есть shell) |

## Лучшие практики

1. **Правки из debug-сессии — не способ фиксации.** Вносите изменения в `Dockerfile` и пересобирайте образ; правки в running-контейнере теряются при его удалении.
2. **Очищайте Toolbox:** утилиты, установленные через `install`, персистентны между сессиями — удаляйте неиспользуемые через `uninstall`.
3. **Безопасность:** debug-shell имеет доступ к ФС, переменным окружения и секретам целевого контейнера (включая `/proc/1/environ`) — относитесь к ней как к привилегированной сессии.
4. **В CI и скриптах** используйте `--command` вместо интерактивной сессии.
5. **На production-хостах без Desktop** (docker-ce) — альтернативы: debug-sidecar (`nicolaka/netshoot`), `nsenter`, eBPF (Inspektor Gadget) — см. **[Отладка distroless](./debugging_distroless.md)**.
6. **Для постоянной отладки distroless** держите образы с тегом `:debug` (см. **[Отладка distroless](./debugging_distroless.md)**).

## Дополнительная информация

### Сохранение состояния

| Объект | Сохранение изменений |
| :--- | :--- |
| **Файлы в running/paused контейнере** | Видны приложению сразу; сохраняются до удаления контейнера |
| **Файлы в stopped контейнере или образе** | Отбрасываются при выходе из shell |
| **Утилиты (`install`)** | Персистентны между сессиями `docker debug` (Toolbox); удаляются через `uninstall` |
| **Директория `/nix`** | Никогда не видна целевому образу/контейнеру |
| **Образ** | Не изменяется никогда |

### Параметры запуска (Флаги)

| Флаг | По умолчанию | Описание | Пример |
| :--- | :--- | :--- | :--- |
| `--shell <type>` | `auto` | Выбор оболочки (`bash`, `fish`, `zsh`, `auto`) | `--shell zsh` |
| `-c`, `--command "<cmd>"` | — | Выполнение команды без интерактивной сессии (аналог `bash -c`) | `--command "df -h"` |
| `--host <socket>` | — | Демон для подключения: SSH или unix-сокет | `--host ssh://root@example.org` |

### docker debug vs docker exec

| Критерий | `docker debug` | `docker exec` |
| :--- | :--- | :--- |
| **Shell в целевом образе** | Не требуется | Требуется (`/bin/sh`) |
| **Состояние контейнера** | running, paused, stopped, образ | только running |
| **Утилиты** | Свой Toolbox (Nix) | Только те, что в образе |
| **Изменения ФС** | Видны контейнеру (running); отбрасываются (stopped/образ) | Видны контейнеру |
| **Изоляция инструментов** | `/nix` не виден приложению | Инструменты — часть образа |
| **Доступность** | Docker Desktop 4.33+ | Docker Engine (везде) |

### Безопасность и ограничения

- **Привилегии:** `docker debug` создаёт эфемерный отладочный контейнер, подключающийся к namespaces целевого контейнера; требуются обычные права на создание контейнеров (не `--privileged`).
- **Архитектура:** Toolbox формируется под архитектуру хоста (в примерах документации — `x86_64-unknown-linux-gnu`); при эмуляции чужой архитектуры целевого контейнера (например, amd64 на Apple Silicon) отладочные утилиты доступны в архитектуре хоста.
- **Ресурсы:** динамическая установка пакетов через Nix потребляет трафик и дисковое пространство (пример из доков: `nmap` — 5.58 MiB download, 26.27 MiB unpacked).

### Связанные темы

- **[Отладка Distroless образов](./debugging_distroless.md)** — особенности работы с минималистичными средами и альтернативы без Docker Desktop.
- **[Ошибки docker exec](./docker_exec_failures.md)** — когда exec недоступен или падает.
- **[Сигналы и проверки здоровья](../Dockerfile/Instructions/health_signals.md)** — автоматизация мониторинга.
- **[Создание образов через commit](../Docker_fs/docker_commit.md)** — сохранение результатов отладки.
- **[Диагностика сетевой связности](./network_connectivity_issues.md)** — глубокая диагностика сети.
- **[Отладка с помощью Docker Events](./debugging_with_docker_events.md)** — мониторинг жизненного цикла.

**Глубокое изучение:**
- **[Performance Degradation](../../Linux/Diagnostics/Networking/iperf3.md)** — диагностика производительности. В Docker: `docker stats` для CPU/memory, `docker exec <c> cat /proc/1/sched` для планировщика, PSI метрики через `/proc/pressure/` для обнаружения bottleneck.
- **[Permission Denied](../../Linux/Security/Concepts/File_Permissions/special_permissions.md)** — проблемы с правами. В Docker: `COPY --chown=user:group` для правильного ownership, `--user` в `docker run` для запуска от нужного UID, /etc/passwd в контейнере.

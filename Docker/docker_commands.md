# Команды Docker CLI

**Актуально для:** Docker Engine 29.x

> Отдельные команды, упомянутые ниже (`docker init`, `docker debug`, `docker scout`), являются закрытыми плагинами Docker Desktop и недоступны в Docker Engine standalone — это оговорено в соответствующих разделах.

## Определения

- **Docker CLI:** Интерфейс командной строки для управления всеми компонентами экосистемы Docker (контейнеры, образы, сети, тома).
- **Docker API:** REST-интерфейс, через который CLI взаимодействует с демоном `dockerd`. Текущая версия API — 1.52 (Docker 29.0); минимальная поддерживаемая демоном — 1.44 (Docker 25.0). Начиная с API 1.50 (Docker 28.2) демон опускает устаревшие поля в ответах (например, `BridgeNfIptables`/`BridgeNfIp6tables` в `GET /info`); в API 1.52 (Docker 29.0) поле `GraphDriver` в `docker image inspect` не возвращается при использовании containerd image store.
- **Контекст (Context):** Набор параметров подключения к конкретному экземпляру Docker (локальному или удаленному).
- **containerd image store:** Хранилище образов и слоёв на базе snapshotter'ов containerd. Является хранилищем по умолчанию для свежих установок начиная с Docker 29.0; требуется для `docker image ls --tree` и мультиплатформенных образов. Legacy graph-драйверы (overlay2) deprecated в 29.x, но продолжают работать на апгрейдах.

## Основные концепции

### Идентификация объектов

Для большинства команд объект задаётся позиционно — **именем** (присваивается при создании, например флагом `--name` в `docker run`) или **ID**. Для ID достаточно указать первые 3–12 символов, если они уникальны среди объектов того же типа; иначе — ошибка `Multiple IDs found with provided prefix`. В скриптах и CI используйте полные ID (`docker ps -a --no-trunc`) или устойчивые имена.

```bash
# Остановка по ID (достаточно уникального префикса)
docker stop a1f
# → a1f
```

### Публикация портов и сетевая безопасность (v28+)

Связывает порт хоста с портом внутри контейнера.
- Формат: `-p [IP_хоста:]порт_хоста:порт_контейнера`
- **Важно (v28.0+):** Docker блокирует прямой доступ извне хоста к IP-адресам контейнеров на порты, не опубликованные через `-p`/`--publish`: DROP-правило в цепочке `DOCKER` (начиная с 28.0) и в таблице `raw`, цепочка `PREROUTING` (начиная с 28.2). Обращения с самого хоста и между контейнерами одной сети по-прежнему разрешены без публикации.
- **Варианты управления прямым доступом:**
  - Опубликовать нужные порты через `-p`.
  - `"allow-direct-routing": true` в `daemon.json` (или `--allow-direct-routing`, 28.2+): прямой доступ извне хоста к **опубликованным** портам на IP-адресах контейнеров во всех bridge-сетях, через все интерфейсы хоста. Неопубликованные порты остаются защищены.
  - `com.docker.network.bridge.trusted_host_interfaces` (28.2+): то же, но для конкретных интерфейсов хоста (список через `:`) и конкретной сети.
  - Сеть с `gateway_mode_ipv[46]=nat-unprotected` (опция драйвера bridge: `com.docker.network.bridge.gateway_mode_ipv4` / `..._ipv6`): любые порты контейнера, включая неопубликованные, доступны по direct-routing с удалённых хостов.
  - `--ip-forward-no-drop` (или `"ip-forward-no-drop": true` в `daemon.json`): возвращает политику цепочки `FORWARD` в `ACCEPT`, но **не** отменяет DROP для неопубликованных портов.
  - `DOCKER_INSECURE_NO_IPTABLES_RAW=1` (28.0.2+): отключает создание правил в таблице `raw` для ядер без `CONFIG_IP_NF_RAW`. Снижает безопасность: порты, опубликованные на `127.0.0.1`, становятся доступны другим хостам LAN. Не рекомендуется для production.
- Сети с `gateway_mode_ipv[46]=routed` доступны из других bridge-сетей того же хоста и извне (NAT-правила для них не создаются).

### Инициализация проекта (docker init)

Интерактивный помощник для создания стартовых файлов (`Dockerfile`, `.dockerignore`, `compose.yaml`) по шаблонам под стек проекта.

```bash
# Запуск интерактивного помощника
docker init
# → result: создание конфигурационных файлов на основе анализа исходного кода
```

**Область применения:** закрытый CLI-плагин в составе Docker Desktop; отдельно для Docker Engine не распространяется. Полный разбор механизма и шаблонов — **[Инициализация проекта: docker init](./docker_init.md)**.

## Практические сценарии

### 1. Управление жизненным циклом контейнеров

| Команда | Описание | Пример вывода / Результат |
|:---|:---|:---|
| `docker run -d --name web -p 8080:80 nginx` | Создать и запустить в фоне | `a1f74...` (Full ID) |
| `docker ps` / `docker ps -a` | Список запущенных / всех контейнеров | Таблица: CONTAINER ID, IMAGE, STATUS |
| `docker stop -t 30 <container>` | Корректная остановка: SIGTERM, ожидание 30 с (по умолчанию 10 с), затем SIGKILL | `my-container` |
| `docker start <container>` | Запуск остановленного контейнера | `my-container` |
| `docker restart <container>` | Перезапуск (stop + start) | `my-container` |
| `docker kill -s SIGINT <container>` | Немедленная отправка сигнала (по умолчанию SIGKILL) | `my-container` |
| `docker pause` / `docker unpause` | Заморозка/разморозка процессов (cgroups freezer; RAM не освобождается) | `my-container` |
| `docker rm -f <container>` | Принудительное удаление | `my-container` |
| `docker wait <container>` | Блокировка до остановки, вывод exit code | `0` |
| `docker attach <container>` | Подключение к потокам (stdin/stdout/stderr) запущенного контейнера | — |
| `docker rename <old> <new>` | Переименование контейнера | — |
| `docker exec -it <id> sh` | Интерактивный вход в контейнер | `/app #` |
| `docker logs -f <id>` | Слежение за логами в реальном времени | `[INFO] Application started` |
| `docker inspect <id>` | Получение детальной информации (JSON) | `{ "Id": "...", ... }` |
| `docker port <id>` | Список опубликованных портов | `80/tcp -> 0.0.0.0:8080` |
| `docker diff <id>` | Изменения ФС с момента создания (A/C/D) | `C /app` |

#### Ключевые флаги docker run

| Флаг | Описание |
|:---|:---|
| `--rm` | Удалить контейнер после выхода (для разовых задач) |
| `--name <name>` | Имя контейнера (уникально на хосте) |
| `-d` / `-it` | Запуск в фоне / интерактивный tty |
| `-e KEY=val` | Переменная окружения |
| `-v <vol>:/path`, `--mount type=volume,...` | Том |
| `--network <net>` | Сеть (расширенный синтаксис: `--network name=bridge,driver-opt=...`) |
| `--restart unless-stopped` | Политика перезапуска |
| `-w /app`, `-u user` | Рабочая директория / пользователь |
| `--add-host host:ip` | Запись в `/etc/hosts` |
| `--health-cmd`, `--health-interval` | Healthcheck |
| `--memory`, `--cpus`, `--pids-limit` | Лимиты ресурсов (см. раздел 6) |
| `--pull` | Политика получения образа: `always` или `missing` |
| `--platform linux/amd64` | Платформа для multi-arch образов |

#### Полезные флаги docker logs и docker exec

```bash
# Последние 100 строк за последние 10 минут с таймстампами
docker logs --tail 100 --since 10m -t my-container

# От имени root, в рабочей директории /app, с переменной, в фоне
docker exec -u root -w /app -e DEBUG=1 -d my-container ./task.sh
```

### 2. Просмотр состояния и диагностика

#### Фильтры и форматирование docker ps

```bash
# Только остановленные контейнеры
docker ps -a --filter status=exited

# Поиск по имени и метке
docker ps -a --filter name=web --filter label=env=prod

# Полные ID (для скриптов и CI)
docker ps -a --no-trunc --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

#### Диагностика окружения

```bash
docker version                          # версии клиента и демона
docker info                             # драйвер хранилища, cgroup driver, число контейнеров
docker version --format '{{.Server.Version}}'
# → 29.8.0
```

#### docker events — поток событий жизненного цикла

```bash
# Отслеживание OOM и завершения контейнеров за последний час
docker events --filter 'event=oom' --filter 'event=die' --since 1h
# → 2026-10-03T... container oom a1b2c3... (image=nginx, name=web_app)
```

#### docker top — просмотр процессов контейнера

Команда `docker top` отображает список процессов, запущенных внутри контейнера, аналогично команде `top` на хосте.

```bash
# Просмотр всех процессов контейнера
docker top my-container
# → UID    PID    PPID   C   STIME   TTY   TIME     CMD
# → root   1234   1      0   10:00   ?     00:00:01 /usr/bin/python app.py

# Просмотр конкретных полей (форматирование)
docker top my-container -eo pid,comm,%cpu,%mem
# → PID    COMMAND   %CPU   %MEM
# → 1234   python    5.2    12.3
```

**Когда использовать:**
- Диагностика высокого потребления CPU/RAM на уровне отдельных процессов
- Проверка что все ожидаемые процессы запущены (воркеры, демоны)
- Поиск "зависших" процессов внутри контейнера

#### docker stats — потребление ресурсов в реальном времени

Команда `docker stats` выводит динамический поток данных о потреблении ресурсов контейнерами.

```bash
# Мониторинг всех контейнеров
docker stats

# Мониторинг конкретного контейнера (однократный снимок)
docker stats my-container --no-stream
# → CONTAINER   CPU %   MEM USAGE / LIMIT   MEM %   NET I/O   BLOCK I/O   PIDS
# → my-container  5.2%   120MiB / 512MiB    23.4%   1MB / 2MB  3MB / 0B   12

# Кастомный формат вывода
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}"
```

**Различия между `docker top` и `docker stats`:**

| Команда | Фокус | Вывод |
|:---|:---|:---|
| `docker top` | Отдельные процессы | Список PID, CMD, ресурсы по процессам |
| `docker stats` | Контейнер целиком | Агрегированные CPU, MEM, I/O, PIDs |

> На cgroup v2 `docker stats` вычитает из потребления памяти `inactive_file` (working set), а API `/containers/<id>/stats` возвращает сырые значения — важно при интеграции с внешними коллекторами. Подробности: **[Нативные метрики Docker](./Docker_metrics/docker_native_metrics.md)**.

### 3. Сборка и управление образами

Современный стандарт сборки — **Buildx** (BuildKit). С v29.0 containerd image store является хранилищем по умолчанию для свежих установок; legacy graph-драйверы (overlay2) deprecated, но работают на апгрейдах (в v28.0 удалена поддержка устаревших graphdriver-плагинов).

```bash
# Проверка Dockerfile перед сборкой (Build Checks, Buildx v0.13+ / Docker 27.0+)
docker buildx build --check .
# → result: список предупреждений о неоптимальных инструкциях

# Дерево слоёв мультиплатформенного образа (v27+, экспериментально, требует containerd image store)
docker image ls --tree
# → result: дерево платформ с колонками DISK USAGE / CONTENT SIZE / USED

# С v29.0 docker image ls по умолчанию показывает свёрнутое дерево,
# сортирует по имени и скрывает untagged-образы (показать: --all)
docker image ls

# Очистка образов
docker image prune -a
```

| Команда | Описание |
|:---|:---|
| `docker pull nginx:1.27` | Скачать образ (`--platform` для multi-arch) |
| `docker push registry/app:1.0` | Выгрузить образ в реестр |
| `docker tag <src> <dst>` | Локальный тег |
| `docker rmi <image>` | Удалить образ (`-f` — принудительно) |
| `docker save -o app.tar app:1.0` | Экспорт в tar (`--platform` с v28.0) |
| `docker load -i app.tar` | Импорт из tar (`--platform` с v28.0, выбор платформ с v29.0) |
| `docker history --no-trunc <image>` | История слоёв |
| `docker login registry.example.com` | Аутентификация в реестре (`docker logout` — выход) |

Подробнее: **[Docker Buildx](./Dockerfile/docker_buildx.md)**, **[Основы образов](./Docker_fs/images/docker_images_basics.md)**, **[Управление слоями](./Docker_fs/images/layer_management.md)**, **[Реестры](./docker_registries.md)**.

### 4. Управление сетями и томами

| Команда | Описание | Пример использования |
|:---|:---|:---|
| `docker network create my-net` | Создать виртуальную сеть | `docker network create my-net` |
| `docker network ls` / `inspect` | Список сетей / детали | `NAME: bridge, DRIVER: bridge` |
| `docker network connect/disconnect <net> <ctr>` | Подключить/отключить контейнер | `docker network connect my-net web` |
| `docker network rm` / `prune` | Удалить сеть / неиспользуемые сети | `docker network prune` |
| `docker volume create pg_data` | Создать именованный том | `docker volume create pg_data` |
| `docker volume ls` / `inspect` | Список томов / детали | `DRIVER: local, VOLUME NAME: pg_data` |
| `docker volume rm` / `prune` | Удалить том / неиспользуемые тома | `docker volume prune` |

Полные справочники: **[Сети в Docker: CLI](./Docker_network/cli.md)**, **[Тома и хранилища](./Docker_fs/docker_volumes.md)**.

### 5. Копирование файлов (docker cp)

Команда `docker cp` позволяет копировать файлы между хостом и контейнером, а также **между контейнерами напрямую**.

```bash
# Копирование файла из хоста в контейнер
docker cp ./config.json my-container:/app/config.json

# Копирование файла из контейнера на хост
docker cp my-container:/app/logs/app.log ./logs/

# Копирование между контейнерами (через хост)
docker cp container-a:/data/file.tar - | docker cp - container-b:/data/
```

**Важная особенность — копирование из остановленных контейнеров:**

В отличие от большинства команд Docker, `docker cp` работает не только с работающими, но и с **остановленными** контейнерами. Это позволяет извлекать файлы из "упавшего" контейнера без его запуска.

```bash
# Контейнер остановлен, но файлы доступны
docker ps -a
# → my-container  Exited (1) 2 minutes ago

# Копирование файла из остановленного контейнера
docker cp my-container:/var/log/app/error.log ./debug-logs/
# → Successfully copied 2.3MB to ./debug-logs/

# Копирование из одного остановленного контейнера в другой работающий
docker cp stopped-container:/data/test.json - | docker cp - running-container:/data/
```

**Ограничения:**
- `docker cp` работает только с файловой системой контейнера, а не напрямую с томами (volumes). Для копирования данных из томов используйте промежуточный контейнер
- Копирование больших файлов может занять значительное время
- Символические ссылки копируются как есть (могут указывать на несуществующие пути в новом контексте)

### 6. Мониторинг и лимиты ресурсов

| Флаг / Команда | Описание | Пример использования |
|:---|:---|:---|
| `--memory 512m` | Лимит RAM | `docker run -m 512m ...` |
| `--cpus 0.5` | Лимит CPU (в ядрах) | `docker run --cpus 0.5 ...` |
| `--pids-limit 200` | Лимит процессов (защита от fork bomb) | `docker run --pids-limit=200 ...` |
| `docker stats` | Потребление в реальном времени | `CPU %: 12.5, MEM: 100MiB` |
| `docker system df` | Анализ использования диска | `Images: 1.2GB, Containers: 50MB` |
| `docker update --memory 1g --cpus 2 <ctr>` | Изменить лимиты без перезапуска | `--memory` можно только увеличивать |

Глубокий разбор всех лимитов (`--memory-high`, `--memory-swap`, `--cpuset-cpus`, `--ulimit`, `--oom-score-adj`, I/O-лимиты и их отображение в cgroups v2): **[Ограничение ресурсов контейнеров](./Docker_security/resource_limits.md)**.

### 7. Очистка и управление дисковым пространством

```bash
docker system df -v            # детальный разбор: images, containers, volumes, build cache
docker system prune            # остановленные контейнеры, dangling-образы, неиспользуемые сети, build cache
docker system prune -a         # + все неиспользуемые образы (не только dangling) — осторожно
docker system prune --volumes  # + неиспользуемые тома — осторожно
docker builder prune           # только кэш сборки BuildKit
docker image prune -a          # все неиспользуемые образы
```

**Важно:** без `-a` удаляются только dangling-образы (без тегов); образы с тегами, не используемые контейнерами, остаются. Логи контейнеров (драйвер `json-file`) не ротируются по умолчанию — настройте `max-size`/`max-file` (см. **[Ротация логов](./Docker_logs/docker_log_rotation.md)**).

### 8. Безопасность и аудит (Docker Scout)

```bash
# Краткий отчет по безопасности образа
docker scout quickview nginx:latest
# → result: 0 critical, 2 high, 15 medium vulnerabilities (пример формата вывода)
```

**Область применения:** Docker Scout — компонент Docker Desktop (подписка). На хостах с Docker Engine standalone используйте Trivy или Grype — см. **[Сканирование Docker-образов на уязвимости](./Docker_security/vulnerability_scanning.md)**.

### 9. Отладка и диагностика (docker debug)

`docker debug` создаёт эфемерный sidecar с Nix-toolbox (`vim`, `curl`, `htop`, `jq`, `ps`), подключённый к namespace-ам целевого контейнера, — позволяет отлаживать distroless-образы, в которых нет `/bin/sh`.

```bash
# Запуск отладочной оболочки
docker debug <container_id>
```

**Область применения:** команда входит в состав Docker Desktop (подписка); в Docker Engine standalone недоступна — запрос на портирование открыт (docker/roadmap#893, февраль 2026). Альтернативы для Engine: `docker exec` (если в образе есть shell), debug-sidecar с общими томами/сетью, `nsenter`. Подробности: **[Отладка контейнеров (Docker Debug)](./Docker_troubleshooting/docker_debug.md)**, **[Отладка distroless-контейнеров](./Docker_troubleshooting/debugging_distroless.md)**.

## Устранение неполадок

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Cannot connect to the Docker daemon. Is the docker daemon running?` | Демон не запущен, неверный контекст или нет прав на сокет | `systemctl status docker`; `docker context ls`; проверить членство в группе `docker` (см. **[Диагностика демона](./Docker_troubleshooting/docker_daemon_failures.md)**) |
| `Got permission denied while trying to connect to the Docker daemon socket` | Пользователь не в группе `docker` | `sudo usermod -aG docker $USER` (нужен перелогин) |
| `Conflict. The container name "/web" is already in use` | Имя занято другим контейнером | `docker rm web` или другое `--name` |
| `No such container: web` | Контейнер удалён или имя/ID неверны | `docker ps -a`; проверить префикс ID |
| `No such image: nginx:1.27` | Образ не скачан | `docker pull nginx:1.27` |
| `port is already allocated` | Хост-порт занят другим контейнером или процессом | `docker ps --format 'table {{.Names}}\t{{.Ports}}'`; `ss -tlnp` (см. **[Конфликты портов](./Docker_troubleshooting/port_conflicts.md)**) |
| `Multiple IDs found with provided prefix` | Короткий ID неоднозначен | Более длинный префикс, полный ID (`docker ps -a --no-trunc`) или имя |
| `dockerd` не стартует на 28.0+: ошибка `ipset` | Ядро без поддержки `ipset` | Включить `ipset` в ядре (требование с 28.0) |
| `failed to set up container networking ... iptables table 'raw'` (28.2+) | Ядро без `CONFIG_IP_NF_RAW` | Обновить ядро; временно — `DOCKER_INSECURE_NO_IPTABLES_RAW=1` (снижает безопасность) |
| Порты контейнера недоступны из LAN после апгрейда на 28.0 | Новый DROP для неопубликованных портов | Опубликовать порты через `-p` или создать сеть с `gateway_mode_ipv4=nat-unprotected` |
| Exit code `137` без ошибок в логах | OOM Killer (SIGKILL) | `docker inspect --format '{{.State.OOMKilled}}' <id>`; увеличить `--memory` (см. **[Коды выхода](./Docker_troubleshooting/docker_exit_codes.md)**) |
| `docker stats` показывает лимит хоста | Контейнеру не задан `--memory` | Задать лимиты (см. **[Лимиты ресурсов](./Docker_security/resource_limits.md)**) |
| Старый `docker-proxy` не работает после апгрейда `dockerd` до 28.0+ | Обновлён демон, бинарник `docker-proxy` устарел | Обновить пакет Docker целиком |

## Лучшие практики

- **Фиксируйте версии образов:** в production используйте теги версий или digests (`nginx@sha256:...`), а не `latest` — иначе деплой недетерминирован.
- **`--rm` для разовых контейнеров** (`docker run --rm ...`); долгоживущие сервисы — с явным `--name` и политикой `unless-stopped`.
- **Лимиты ресурсов на каждый production-контейнер:** `--memory`, `--cpus`, `--pids-limit` (см. **[Лимиты ресурсов](./Docker_security/resource_limits.md)**).
- **Регулярная очистка:** `docker system prune` (без `-a` — безопасно), `docker builder prune`; на CI-раннерах — после каждой сборки.
- **Ротация логов:** для драйвера `json-file` задавайте `max-size`/`max-file` (см. **[Ротация логов](./Docker_logs/docker_log_rotation.md)**).
- **Полные ID и digests в скриптах/CI:** короткие префиксы могут стать неоднозначными; используйте `docker ps -a --no-trunc` и `--format` для парсинга.
- **Контексты вместо `DOCKER_HOST`:** для удалённых хостов — `docker context` (см. **[Docker Context](./docker_context.md)**).
- **Buildx вместо классического `docker build`:** BuildKit даёт кэширование, `--check` и мультиплатформенность (см. **[Docker Buildx](./Dockerfile/docker_buildx.md)**).
- **Обновляйте пакет Docker целиком:** с 28.0 старый `docker-proxy` несовместим с новым `dockerd`.
- **Отладка distroless на Engine:** не используйте `docker debug` (Docker Desktop); используйте `docker exec` с shell-образом или debug-sidecar (см. **[Отладка distroless](./Docker_troubleshooting/debugging_distroless.md)**).

## Дополнительная информация

### Политики перезапуска

- `no`: Не перезапускать (по умолчанию).
- `on-failure`: Только если код выхода не равен 0.
- `always`: Всегда перезапускать.
- `unless-stopped`: Перезапускать всегда, если контейнер не был остановлен вручную (**рекомендуется для prod**).

### Управление контекстами

```bash
# Список доступных подключений (активный отмечен *)
docker context ls

# Создание контекста для удаленного сервера через SSH
docker context create remote-srv --docker "host=ssh://user@host"
```

Полный разбор механизма, приоритета переменных окружения и диагностика — в **[Docker Context](./docker_context.md)**.

### Различия между stop и pause

- **Stop:** Отправляет `SIGTERM` (или сигнал из `STOPSIGNAL`), процесс завершается, ресурсы освобождаются.
- **Pause:** Использует `cgroups freezer`, процесс "замораживается", память (RAM) **не освобождается**.

### См. также
- **[Docker Compose CLI: Справочник команд](./Docker_compose/docker_compose_cli_commands.md)**
- **[Сети в Docker: CLI-справочник](./Docker_network/cli.md)**
- **[Тома и хранилища](./Docker_fs/docker_volumes.md)**
- **[Безопасность Docker-демона](./Docker_security/host_daemon_hardening.md)**
- **[Нативные метрики Docker](./Docker_metrics/docker_native_metrics.md)**
- **[Ограничение ресурсов контейнеров](./Docker_security/resource_limits.md)**
- **[Сканирование уязвимостей](./Docker_security/vulnerability_scanning.md)**
- **[Отладка контейнеров](./Docker_troubleshooting/docker_debug.md)**
- **[Коды выхода контейнеров](./Docker_troubleshooting/docker_exit_codes.md)**
- **[Инициализация проекта: docker init](./docker_init.md)**

# Docker Compose: Вопросы на собеседованиях

**Актуально для:** Docker Compose v2.20+ (Compose Specification). Ответы верифицированы по документации Docker и содержимому базы знаний; теория и практика — в смежных файлах (ссылки в конце).

## Определения

**Задачи этого файла** — краткие, точные ответы на типичные вопросы DevOps/SRE-собеседований по Docker Compose. Каждый ответ содержит ключевой факт и, где нужно, команду для проверки.

## Основы

**Q: Что такое Docker Compose и чем отличается от `docker run`?**
A: Инструмент определения и запуска многоконтейнерных приложений через декларативный YAML (`compose.yml`): сети, тома, зависимости, healthcheck и переменные описываются в одном файле. `docker run` управляет одним контейнером; Compose — проектом (группой контейнеров с общим именем, сетями и томами).

**Q: Чем Compose отличается от Docker Swarm и Kubernetes?**
A: Compose — развёртывание на одном хосте без desired state и без оркестрации (нет rolling update, self-healing, распределения по узлам). Swarm — кластерный режим Docker с сервисами и `docker stack deploy`. Kubernetes — полноценный оркестратор. Compose-файл можно конвертировать в манифесты K8s через Kompose (`kompose convert`).

**Q: Что такое project name и как он определяется?**
A: Уникальный идентификатор проекта, из которого формируются имена контейнеров, сетей и томов. Приоритет (по документации Docker): флаг `-p`/`--project-name` > переменная `COMPOSE_PROJECT_NAME` > ключ `name:` в файле > имя директории проекта > имя текущей директории. Проверка: `docker compose ls`.

**Q: Чем `docker compose up -d` отличается от `docker compose up --wait`?**
A: `up -d` возвращает управление сразу после запуска контейнеров. `up --wait` (Compose v2.2.0+) блокирует выполнение, пока все сервисы не достигнут состояния `running|healthy` (или не будут запущены, если healthcheck не задан) — детерминированная готовность стека.

## Конфигурация

**Q: Каков приоритет источников переменных в compose-файле?**
A: От высшего к низшему: переменные системного окружения (shell) > `--env-file` > директива `env_file` сервиса > файл `.env` в директории проекта > значения по умолчанию в YAML.

**Q: Чем `include` отличается от `extends`?**
A: `include` (Compose v2.20+) импортирует целые конфигурации (локальные файлы или OCI-артефакты) с полной изоляцией ресурсов — сети и тома импортируемого файла не конфликтуют с текущими. `extends` — наследование и переопределение отдельных сервисов между файлами. Для модульности инфраструктуры рекомендуется `include`.

**Q: Что такое override file?**
A: `compose.override.yml` автоматически загружается вместе с `compose.yml` и применяет deep merge. Используется для локальных переопределений, не попадающих в контроль версий. Явное указание: `-f compose.yml -f compose.prod.yml`.

**Q: Какие формы интерполяции переменных существуют?**
A: `${VAR}` — подстановка; `${VAR:-default}` — default, если переменная пуста или не задана; `${VAR-default}` — default, только если переменная не задана (пустое значение допускается); `${VAR:?error}` — завершить с ошибкой, если переменная не задана.

**Q: Что такое extension fields (`x-`)?**
A: Ключи YAML с префиксом `x-`, игнорируемые парсером Compose, но используемые как переиспользуемые шаблоны через YAML-якоря (`&anchor` / `*ref`) — централизованные метки, переменные, ресурсы.

## Запуск и жизненный цикл

**Q: Как декларативно задать зависимость между сервисами?**
A: `depends_on` с `condition: service_healthy` — Compose дожидается healthy-зависимого сервиса перед запуском. Для сервисов с долгой инициализацией задайте `start_period` в `healthcheck`.

**Q: В чём разница `restart: always` и `restart: unless-stopped`?**
A: `always` — dockerd перезапускает контейнер при падении и при старте демона (в т.ч. после reboot). `unless-stopped` — то же, но не перезапускает контейнер, остановленный вручную. Для одноразовых задач (миграции) — `restart: "no"`. **Анти-паттерн:** `restart: always` + systemd-юнит, управляющий стеком — конфликт двух менеджеров жизненного цикла.

**Q: Что удаляет `docker compose down -v`?**
A: Контейнеры, сети проекта и **анонимные** тома (`-v`). Именованные тома (`volumes:` с явным именем) удаляются только с `docker compose down -v` при их объявлении в проекте... точнее: `-v` удаляет именованные тома, объявленные в compose-файле проекта, и анонимные. Данные в external-томах не затрагиваются.

**Q: Зачем `--remove-orphans`?**
A: Удаляет контейнеры, оставшиеся от предыдущих запусков проекта (например, после удаления сервиса из compose-файла). Без флага орфаны остаались бы на хосте.

**Q: Что делает `docker compose wait`?**
A: Блокирует выполнение до остановки контейнеров всех (или указанных) сервисов; полезна в multi-stage пайплайнах. Отличается от `up --wait`, которая ждёт готовности, а не остановки.

## Продакшен

**Q: Как сделать compose-стек переживающим reboot хоста?**
A: systemd-юнит с `Type=oneshot`, `RemainAfterExit=yes`, `ExecStart=docker compose up -d --remove-orphans`, `ExecStop=docker compose down --timeout 30`, `After=docker.service network-online.target`, `Delegate=yes`, `WantedBy=multi-user.target`; включение через `systemctl enable --now`. Для rootless — user-юнит + `loginctl enable-linger`. Подробно: [Автозапуск через systemd](./docker_compose_systemd_autostart.md).

**Q: Как реализовать откат версии в Compose?**
A: Compose не хранит историю ревизий. Откат = возврат к предыдущей конфигурации в Git (`git checkout <commit> -- compose.yml`) + `docker compose pull && docker compose up -d --wait`. Требуется пининг образов (тег или digest), иначе `pull` получит непредсказуемую версию.

**Q: Как реализовать blue-green на одном хосте?**
A: Два проекта одной конфигурации с разными именами (`docker compose -p myapp-blue up -d` / `-p myapp-green`), общая `external` сеть, переключение трафика на сетевом слое (nginx upstream, балансировщик). Откат — обратное переключение. Подробно: [Стратегии развёртывания](./docker_compose_deployment_strategies.md).

**Q: Есть ли в Compose rolling update?**
A: Нет нативного контроллера. Эмуляция: масштабирование (`docker compose up -d --scale web=4 --wait`, затем снижение) при условии, что балансировщик опрашивает все контейнеры сервиса. Для автоматического progressive delivery — Argo Rollouts/Flagger в Kubernetes.

**Q: Как масштабировать сервис?**
A: `docker compose up -d --scale <service>=N` (разовый запуск) или `scale:` в compose-файле (Compose v2). Для stateful-сервисов масштабирование требует поддержки приложением (кластеризация БД).

**Q: Как передать секреты в сервис без утечки?**
A: Директива `secrets:` — файл монтируется в `/run/secrets/<name>` (права по умолчанию 0400), не попадает в образ, переменные окружения и логи. Для сборки — `build.secrets` (BuildKit): токен доступен на этапе `RUN --mount=type=secret`, но не сохраняется в слоях.

## CLI и диагностика

**Q: Что выводят `docker compose config --services`, `--volumes`, `--networks`?**
A: Список сервисов, томов и сетей итоговой (после merge всех `-f` файлов и интерполяции) конфигурации — проверка того, что Compose понял файл, без запуска стека.

**Q: Что такое `docker compose ls`?**
A: Список compose-проектов на хосте (с `--all` — включая остановленные, с `--format json` — машиночитаемый вывод).

**Q: Чем `docker compose events` полезен в production?**
A: Поток событий контейнеров проекта в реальном времени (`--json`, `--since 5m`); фильтры, например `--filter event=oom`, для диагностики убийств контейнеров.

**Q: Что делает `docker compose port <service> <port>`?**
A: Печатает публичный хост-порт, на который опубликован порт сервиса — полезно в скриптах и CI, где порт назначается динамически.

**Q: Есть ли у `docker compose` флаг `--context` для удалённого демона?**
A: **Нет** — глобальные опции compose (`--env-file`, `-f`, `--profile`, `-p` и др.) не включают `--context`. Целевой демон задаётся через `docker context use <NAME>`, переменную `DOCKER_CONTEXT` или `DOCKER_HOST` (который перекрывает контексты). Подробно: [Удалённое управление](./docker_compose_remote_management.md).

## Безопасность

**Q: Можно ли монтировать `/var/run/docker.sock` в сервис?**
A: Технически можно, но это эквивалент root-доступа к хосту: контейнер может запустить привилегированный контейнер с корневой ФС хоста. В production — только `docker-socket-proxy` с гранулярными правами (`CONTAINERS=1`, `SERVICES=1`, `TASKS=1`) или Portainer Agent.

**Q: Что такое rootless Compose?**
A: Запуск стеков через rootless-демон (`dockerd-rootless-setuptool.sh install`): демон и контейнеры работают от непривилегированного пользователя через user namespaces; при побеге из контейнера права ограничены пользователем. Установщик создаёт контекст `rootless`; автозапуск — `loginctl enable-linger`. Ограничение: порты < 1024 требуют `sysctl net.ipv4.ip_unprivileged_port_start=80` или reverse proxy.

**Q: Какие директивы compose-файла снижают привилегии сервиса?**
A: `cap_drop: [ALL]` + точечный `cap_add`, `read_only: true`, `security_opt: [no-new-privileges:true]`, `tmpfs` для временных файлов, `user: <non-root>`, `internal: true` для сетей без внешнего доступа.

## Производительность

**Q: Контейнер упал с exit 137. Что это и как проверить?**
A: OOM: ядро убило процесс в cgroup при превышении `deploy.resources.limits.memory`. Проверка: `docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' <c>` → `true 137`. Действия: поднять лимит, найти утечку, `docker compose stats` для мониторинга.

**Q: В чём разница `limits` и `reservations` в `deploy.resources`?**
A: `limits` — жёсткий потолок (превышение `memory` → OOM Kill; `cpus` — троттлинг). `reservations` — мягкий лимит: в non-Swarm compose работает только `reservations.memory` (`--memory-reservation`, reclaim при превышении); `reservations.cpus`/`pids` compose не применяет — опции Swarm.

**Q: Почему named volume быстрее для записи в БД?**
A: Данные в named volume обходят CoW (Copy-on-Write) overlay2: первая запись в файл из нижнего слоя образа не копирует файл в верхний слой контейнера. Для write-heavy нагрузок (БД, логи) — named volume; для hot-reload в dev — bind mount.

**Q: Как предотвратить переполнение диска логами?**
A: Ротация в compose-файле:
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"
    compress: "true"
```
Значения — строки; применяется только к новым контейнерам (`--force-recreate`).

## Дополнительная информация

- **[Обзор Docker Compose](./docker_compose_overview.md)** — архитектура и ключевые возможности.
- **[Справочник по директивам](./docker_compose_directives.md)** — все ключи `compose.yml`.
- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — полный список команд.
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — `include`, профили, секреты.
- **[Автозапуск через systemd](./docker_compose_systemd_autostart.md)** — юниты и жизненный цикл.
- **[Стратегии развёртывания](./docker_compose_deployment_strategies.md)** — откат, blue-green, canary.
- **[Удалённое управление](./docker_compose_remote_management.md)** — контексты и remote daemon.
- **[Безопасность](./docker_compose_security.md)** — сокет, rootless, секреты.
- **[Производительность](./docker_compose_performance_tuning.md)** — лимиты, OOM, I/O.
- **[Docker логирование: вопросы на собеседованиях](../Docker_logs/docker_logging_interview_qa.md)** — смежная тема: лог-драйверы и диагностика.

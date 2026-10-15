# Podman: Основные команды CLI

> **Актуально для:** Podman 6.x (стабильная ветка 6.0.x, проверено на 6.0.2). Где важно, указана версия появления/изменения команды.

## Определения

**Podman CLI** — интерфейс командной строки для управления контейнерами, образами, подами, сетями, томами и секретами. В отличие от Docker, Podman не требует фонового демона (**daemonless**) и ориентирован на работу без привилегий root (**rootless**). Подробнее: [Daemonless архитектура](./podman_daemonless_architecture.md), [Rootless режим](./podman_rootless.md).

**OCI (Open Container Initiative)** — набор стандартов для форматов образов и сред выполнения контейнеров, которым полностью соответствует Podman. Команды построены вокруг двух уровней: `podman <объект> <операция>` (например, `podman volume ls`) и «двухсловных» алиасов (`podman image ls` ≡ `podman images`).

**Pod** — группа из одного или нескольких контейнеров, разделяющих сетевые ресурсы (и, опционально, другие пространства имён) через инфраструктурный (infra) контейнер. Концепция заимствована из Kubernetes и реализована в Podman нативно. Подробнее: [Поды в Podman](./podman_pods.md).

**Containerfile / Dockerfile** — файл с инструкциями для сборки образа. Podman принимает оба имени; сборка выполняется движком Buildah.

---

## Основные концепции

### Информация о системе и настройка

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Версия | `podman --version` | Краткая информация о версии бинарного файла |
| Детальное инфо | `podman info` | Данные о хосте, хранилище, сетевом стеке и драйверах |
| Использование диска | `podman system df` | Объём, занимаемый образами, контейнерами, томами и кэшем сборки |
| Перенумерация хранилища | `podman system renumber` | Перенумерация слоёв хранилища (после удаления промежуточных слоёв) |
| Сброс хранилища | `podman system reset` | Полный сброс хранилища (удаляет все образы, контейнеры, тома) — необратимо |
| Аутентификация | `podman login <registry>` | Вход в реестр образов; `podman logout <registry>` — выход |
| Поиск образов | `podman search <term>` | Поиск в настроенных реестрах (управляются `registries.conf`) |
| События системы | `podman events` | Поток событий (create, start, stop, died и т.д.) в реальном времени |
| Удалённые подключения | `podman system connection add/list/remove` | Управление `podman system connection` для `podman --remote` и `podman machine` |

### Управление образами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Список | `podman images` | Показать локальные образы; `-a` — включая промежуточные |
| Загрузка | `podman pull <image>` | Скачать образ (рекомендуется полный путь, FQIN) |
| Отправка | `podman push <image> <registry>` | Загрузить образ в реестр |
| Метки | `podman tag <image> <новое-имя>` | Добавить дополнительное имя образу |
| Сборка | `podman build -t <tag> .` | Сборка по Containerfile/Dockerfile (движок Buildah) |
| История | `podman history <image>` | Слои и команды сборки образа |
| Инспекция слоёв | `podman image inspect <image> \| jq '.[0].RootFS.Layers'` | Список слоёв файловой системы образа |
| Удаление | `podman rmi <image>` | Удалить образ (`-f` — принудительно; `-a` — все неиспользуемые) |
| Сохранение в архив | `podman save -o <файл>.tar <image>` | Экспорт образа в архив (для переноса между хостами) |
| Импорт архива | `podman load -i <файл>.tar` | Загрузка образа из архива |
| Фиксация контейнера | `podman commit <container> <новый-образ>` | Создать образ из изменённого контейнера |
| Мультиплатформенность | `podman manifest create/add/push` | Работа с манифест-списками (multi-arch) |
| Мультиплатформенная сборка | `podman farm build --farm <имя> -t <image> .` | Сборка для нескольких архитектур на удалённых узлах (доступна с Podman 4.2) |

### Управление контейнерами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Запуск | `podman run [flags] <image>` | Создать и запустить контейнер |
| Создание без запуска | `podman create [flags] <image>` | Создать контейнер, не запуская его |
| Список | `podman ps [-a]` | Запущенные контейнеры; `-a` — все |
| Список (формат) | `podman ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}'` | Таблица: имя, статус, образ (tab-separated) |
| Логи | `podman logs [-f] <name>` | Логи контейнера; `-f` — в реальном времени |
| Исполнение | `podman exec -it <name> <cmd>` | Запуск команды внутри работающего контейнера |
| Подключение | `podman attach <name>` | Подключение к работающему процессу (stdin/stdout) |
| Копирование | `podman cp <контейнер>:<путь> <локальный-путь>` | Копирование файлов между контейнером и хостом |
| Старт | `podman start <name>` | Запуск созданного/остановленного контейнера |
| Остановка | `podman stop [-t 10] <name>` | Плавная остановка (SIGTERM, затем SIGKILL после таймаута) |
| Перезапуск | `podman restart <name>` | Перезапуск контейнера |
| Убить | `podman kill <name>` | Отправить сигнал (по умолчанию SIGKILL; `-s` — свой) |
| Пауза | `podman pause <name>` / `podman unpause <name>` | Заморозить/возобновить процессы (через SIGSTOP/SIGCONT) |
| Удаление | `podman rm [-f] <name>` | Удалить контейнер; `-f` — принудительно (даже запущенный) |
| Обновление на лету | `podman update [flags] <name>` | Изменение лимитов ресурсов, restart-политики и env без пересоздания (см. [Переменные окружения](./podman_environment_variables.md)) |
| Изменения ФС | `podman diff <name>` | Разница между контейнером и его образом |
| Инспекция | `podman inspect <name>` | Подробные метаданные (формат через `--format '{{...}}'`) |
| Процессы | `podman top <name>` | Список процессов внутри контейнера |
| Статистика | `podman stats [-a]` | Живой поток использования CPU/памяти/сети всеми контейнерами |
| Ожидание | `podman wait <name>` | Ожидание завершения контейнера, возврат кода выхода |
| Проброс портов | `podman port <name> [<порт>]` | Список или конкретный проброс портов контейнера |
| Экспорт ФС | `podman export -o <file>.tar <name>` | Экспорт файловой системы контейнера в tar-архив |
| Импорт ФС | `podman import <file>.tar [образ]` | Импорт tar-архива как нового образа |
| Копирование между контейнерами | `podman scp <src>:<dest>` | Копирование файлов между контейнерами (аналог `podman cp` для контейнер-контейнер) |
| Переименование | `podman rename <старое> <новое>` | Переименование контейнера |

### Управление подами (Pods)

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Создание | `podman pod create --name <n> [-p 8080:80]` | Создать под с инфраструктурным контейнером; проброс портов задаётся на уровне пода |
| Список | `podman pod ps` | Список подов и число контейнеров в каждом |
| Запуск в поде | `podman run --pod <n> ...` | Запустить контейнер внутри существующего пода |
| Старт/Остановка | `podman pod start <n>` / `podman pod stop <n>` | Управление всеми контейнерами пода |
| Перезапуск | `podman pod restart <n>` | Перезапуск всех контейнеров пода |
| Удаление | `podman pod rm [-f] <n>` | Удалить под (и все его контейнеры) |
| Процессы/Статистика | `podman pod top <n>` / `podman pod stats` | Аналоги `top`/`stats`, но по всему поду |
| Клонирование | `podman pod clone <n>` | Создать копию пода (с Podman 4.2) |

### Управление сетями

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Список | `podman network ls` | Список сетей |
| Создание | `podman network create <имя>` | Создать сеть (драйвер `bridge`; Netavark + aardvark-dns) |
| Подключение | `podman network connect <сеть> <контейнер>` | Присоединить контейнер к дополнительной сети |
| Отключение | `podman network disconnect <сеть> <контейнер>` | Отсоединить контейнер |
| Инспекция | `podman network inspect <имя>` | Параметры сети (подсеть, шлюз, DNS) |
| Удаление | `podman network rm <имя>` | Удалить сеть (запрещено, если она используется) |
| Пересоздание правил | `podman network reload` | Пересоздать правила файрвола для работающих контейнеров (после перезагрузки файрвола) |

В rootless-режиме сеть по умолчанию строится на стеке **pasta** (с Podman 5.0 — драйвер по умолчанию; в Podman 6.x — единственный поддерживаемый, `slirp4netns` удалён). Контейнеры в `pasta` изолированы друг от друга; для взаимодействия используются общий pod, проброс портов или rootless bridge-сеть. Подробнее: [Rootless режим](./podman_rootless.md).

### Управление томами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Список | `podman volume ls` | Список томов |
| Создание | `podman volume create <имя>` | Создать именованный том |
| Инспекция | `podman volume inspect <имя>` | Параметры тома (включая путь монтирования) |
| Удаление | `podman volume rm <имя>` | Удалить том (`-f` — даже если используется) |
| Очистка | `podman volume prune` | Удалить все неиспользуемые тома |
| Перезагрузка | `podman volume reload` | Синхронизация состояния с плагинами томов (с Podman 4.2) |

Подробнее о хранилище, типах монтирований и правах доступа: [Тома и хранилище](./podman_volumes_and_storage.md).

### Управление секретами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Создание | `podman secret create <имя> <файл>` | Создать секрет из файла (или `-` для stdin) |
| Список | `podman secret ls` | Список секретов |
| Инспекция | `podman secret inspect <имя>` | Метаданные секрета |
| Удаление | `podman secret rm <имя>` | Удалить секрет |
| Использование | `podman run --secret <имя> ...` | Передать секрет в контейнер (подробнее — [Секреты](./podman_secrets.md)) |

### Интеграция с экосистемой

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Compose | `podman compose up -d` | Запуск Compose-проекта через внешний провайдер (docker-compose или podman-compose); с Podman 4.2 существует тонкая обёртка `podman-compose` |
| Kubernetes (экспорт) | `podman kube generate <под> > файл.yaml` | Генерация Kubernetes-манифеста из пода; `--type deployment` — в виде Deployment (группа `podman kube` — с Podman 4.3) |
| Kubernetes (запуск) | `podman kube play файл.yaml` | Локальный запуск пода/Deployment из YAML |
| Kubernetes (удаление) | `podman kube down файл.yaml` | Удаление ресурсов, развёрнутых через `kube play` |
| systemd-юнит | `podman generate systemd --new --name <n>` | Генерация юнита для контейнера; **устаревший** способ — вместо него используется Quadlet |
| Декларативный деплой | Quadlet (файлы `.container`, `.pod`, `.volume`) | Современный стандарт управления контейнерами под systemd |
| Автообновление | `podman auto-update` | Обновление контейнеров по политике `io.containers.autoupdate` |
| Проверка здоровья | `podman healthcheck run <имя>` | Ручной запуск проверки здоровья; настройка — [Healthchecks](./podman_healthchecks.md) |

> **Примечание об устаревших командах:** `podman generate kube` и `podman play kube` (до Podman 4.3) продолжают работать, но считаются устаревшими в пользу группы `podman kube`. `podman generate systemd` устарел в пользу Quadlet (см. [Daemonless архитектура](./podman_daemonless_architecture.md)).

---

## Практические сценарии

### 1. Запуск изолированного веб-стека в поде
Поды позволяют контейнерам взаимодействовать через `localhost`, имитируя поведение Kubernetes, и решают проблему изоляции контейнеров в rootless-сети pasta.

```bash
# Создаём под с пробросом порта наружу (8080 → 80)
podman pod create --name web-app -p 8080:80

# Добавляем БД (PostgreSQL) — без собственного проброса портов
podman run -d --pod web-app --name db -e POSTGRES_PASSWORD=secret postgres:alpine

# Добавляем сервер (Nginx), обращающийся к БД по localhost:5432
podman run -d --pod web-app --name server nginx:alpine

# Проверка состояния пода
podman pod ps
# → POD       NAME      ...
# → web-app   2         ...

# Остановить и удалить весь стек одним действием
podman pod stop web-app
podman pod rm web-app
```

### 2. Динамическое обновление параметров работающего контейнера
Команда `podman update` изменяет конфигурацию уже запущенного контейнера без его пересоздания. Ограничение: новые лимиты вступают в силу для процессов после перезапуска контейнера; для `env` — после следующего старта.

```bash
# Ограничиваем CPU и память для уже работающего контейнера
podman update --cpus 0.5 --memory 512m my-container

# Включаем политику перезапуска (no | on-failure[:N] | always | unless-stopped)
podman update --restart always my-container

# Изменяем переменную окружения на лету
podman update --env DEBUG=true my-running-app

# Проверка применения
podman exec my-running-app env | grep DEBUG
```

Подробнее о приоритетах переменных окружения: [Переменные окружения](./podman_environment_variables.md).

### 3. Экспорт и импорт в Kubernetes
Podman является мостом между локальной разработкой и кластером: под можно превратить в Kubernetes-манифест и наоборот.

```bash
# Генерируем YAML для существующего пода
podman kube generate web-app > deployment.yaml

# Как Deployment (с репликами) — с Podman 4.3
podman kube generate --type deployment web-app > deployment.yaml

# Воспроизводим окружение локально из YAML
podman kube play deployment.yaml

# Удаляем ресурсы, развёрнутые из этого манифеста
podman kube down deployment.yaml
```

> **Важно:** `podman kube play` использует политику выхода `exit-policy=stop` — под корректно останавливается при завершении последнего контейнера.

### 4. Диагностика и мониторинг
Базовый набор команд для разбора проблем с контейнером.

```bash
# Инспекция: IP-адрес, состояние, монтирования, env
podman inspect my-app --format '{{.NetworkSettings.IPAddress}}'

# Живые метрики потребления ресурсов (Ctrl+C для выхода)
podman stats

# Процессы внутри контейнера
podman top my-app

# События системы в реальном времени (фильтр по контейнеру)
podman events --filter container=my-app

# Код выхода завершившегося контейнера
podman wait my-app
```

### 5. Перенос образов между хостами без реестра
Когда нет доступа к общему реестру, образ переносится архивом.

```bash
# Экспорт образа в tar-архив
podman save -o nginx.tar docker.io/library/nginx:alpine

# На целевом хосте — импорт архива
podman load -i nginx.tar

# Проверка, что образ появился локально
podman images | grep nginx
# → docker.io/library/nginx    alpine    ...    ...

# Прямое копирование между машинами через skopeo (без локального хранилища)
skopeo copy docker://docker.io/library/nginx:alpine docker://myhost:5000/nginx:alpine
```

Подробнее: [Skopeo: обзор](./skopeo_overview.md).

### 6. Мультиархитектурная сборка
Для публикации образов под несколько архитектур (amd64/arm64) используется манифест-список и команда `podman farm build`.

```bash
# Сборка для одной платформы с указанием цели (эмуляция QEMU на хосте)
podman build --platform linux/arm64 -t myapp:arm64 .

# Нативная сборка на удалённых узлах разной архитектуры
podman farm create myfarm builder-amd64 builder-arm64
podman farm list
podman farm build --farm myfarm -t registry.example.com/myapp:latest .

# Инспекция манифест-списка после сборки
podman manifest inspect registry.example.com/myapp:latest
```

`podman farm build` доступен с Podman 4.2 (в RHEL длительное время — Technology Preview) и присутствует в актуальной ветке 6.x. Альтернатива без farm — `podman build --platform <арх1>,<арх2> --manifest <имя>` с эмуляцией.

### 7. Очистка ресурсов (Pruning)
Регулярная очистка помогает избежать переполнения диска, особенно в rootless-режиме, где квоты могут быть ограничены.

```bash
# Удалить все остановленные контейнеры
podman container prune

# Удалить все неиспользуемые образы без тегов
podman image prune -a

# Удалить неиспользуемые сети
podman network prune

# Удалить старые тома
podman volume prune

# Полная очистка неиспользуемых объектов (контейнеры, сети, образы)
podman system prune -a

# Объём освобождаемого места — сначала оценка без удаления
podman system df
```

> **Осторожно:** `podman system reset` полностью сбрасывает хранилище Podman (все образы, контейнеры, тома) — необратимая операция, применять только осознанно.

### 8. Безопасный запуск контейнеров (hardening)
Минимальный набор привилегий снижает риск взлома и ограничивает последствия компрометации приложения. В Production применяйте эти флаги по умолчанию.

```bash
# Запуск с отказом от всех capabilities и явным добавлением только необходимых
podman run -d \
  --name web-server \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /run --tmpfs /tmp \
  -v /srv/data:/data:Z \
  nginx:alpine

# Проверка: контейнер запущен, корневая ФС только для чтения
podman exec web-server touch /test 2>&1 || true
# → Read-only file system
```

**Пояснение флагов:**
- `--cap-drop=ALL`: отключает все Linux-привилегии по умолчанию.
- `--cap-add=NET_BIND_SERVICE`: разрешает bind на порты < 1024 (если настроен `sysctl`).
- `--security-opt=no-new-privileges`: запрещает повышение привилегий через setuid/setgid.
- `--read-only`: монтирует корневую ФС в режиме только для чтения.
- `--tmpfs /run --tmpfs /tmp`: временные директории в RAM, не записываются на диск.
- Подробнее об изоляции и наборе capabilities: [Изоляция Podman](./linux_isolation.md).

### 9. Управление логами и ротация
Podman хранит логи в JSON-файлах по умолчанию. В Production используйте `journald` для централизованного сбора и автоматической ротации.

```bash
# Просмотр логов с фильтрацией по времени
podman logs --since "2026-09-16T08:00:00" --until "2026-09-16T09:00:00" web-server

# Просмотр последних 100 строк
podman logs --tail 100 web-server

# Только логи с ошибкой
podman logs --tail 50 web-server | grep -i error

# Логи в реальном времени (Ctrl+C для выхода)
podman logs -f web-server
```

**Ротация через journald (rootful):**
```bash
# Настройка лимита journald (по умолчанию 10% от размера раздела)
sudo mkdir -p /etc/systemd/journald.conf.d
echo -e "[Journal]\nSystemMaxUse=500M" | sudo tee /etc/systemd/journald.conf.d/size.conf
sudo systemctl restart systemd-journald
```

**Ротация для JSON-логов (rootless / если journald не используется):**
```bash
# Настройка в containers.conf
mkdir -p ~/.config/containers
cat > ~/.config/containers/containers.conf << 'EOF'
[engine]
cgroup_manager = "systemd"
runtime = "crun"

[containers]
# Ограничение размера JSON-логов
# Примечание: log-opt настраивается через podman run, а глобальные лимиты — через journald
EOF
```

**Важно:** В rootless-режиме логи хранятся в `~/.local/share/containers/storage/containers/`. Для ротации используйте `logrotate` или монтируйте журнал в `tmpfs`.

### 10. Резервное копирование и восстановление состояния
Для миграции или бэкапа используйте комбинацию экспорта ФС контейнера и резервного копирования томов.

```bash
# 1. Остановить контейнер (для консистентности данных)
podman stop web-server

# 2. Экспорт файловой системы контейнера в tar
podman export -o /backups/web-server-$(date +%F).tar web-server

# 3. Резервное копирование тома (если используется)
podman volume export app-data --output /backups/app-data-$(date +%F).tar

# 4. На целевом хосте — импорт
podman import /backups/web-server-2026-09-16.tar web-server:restored
podman volume import app-data-restored /backups/app-data-2026-09-16.tar

# 5. Валидация: запуск восстановленного контейнера
podman run -d --name web-server-restored -v app-data-restored:/data web-server:restored
podman logs --tail 20 web-server-restored
```

Для автоматизации бэкапов томов см. [Тома и хранилище](./podman_volumes_and_storage.md).

### 11. Локальный CI/CD раннер (GitLab CI)
Podman может выступать executor'ом для GitLab Runner на локальных хостах без облачных зависимостей.

```bash
# 1. Установка GitLab Runner
sudo apt install gitlab-runner  # Debian/Ubuntu
# или
sudo dnf install gitlab-runner  # RHEL/Fedora

# 2. Регистрация раннера с executor'ом podman
sudo gitlab-runner register \
  --url https://gitlab.example.com/ \
  --token $RUNNER_TOKEN \
  --executor podman \
  --podman-image docker.io/library/alpine:latest \
  --podman-privileged=false \
  --podman-pull-policy if-not-present

# 3. Настройка глобального контейнера для задач
sudo gitlab-runner exec podman --pre-clone-image docker.io/library/alpine:latest
```

**Важные ограничения:**
- `--podman-privileged=false` по умолчанию; для задач, требующих `--privileged`, установите `privileged = true` в `config.toml`.
- Для доступа к private registry укажите `pull_policy` и `authfile` в `config.toml`.
- Реннер работает как rootful-сервис; для rootless запускайте его в user session systemd.

**Альтернатива: Jenkins Agent в Podman**
```bash
# Запуск Jenkins agent как контейнера
podman run -d --name jenkins-agent \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  jenkins/inbound-agent:latest \
  -url http://jenkins.example.com/ \
  $AGENT_SECRET $AGENT_NAME
```

---

## Устранение неполадок

### Типичные ошибки CLI

| Симптом / команда | Причина | Решение |
| :--- | :--- | :--- |
| `Error: unable to find image` | Образ не найден локально или недоступен в реестре | Проверьте FQIN: `podman pull docker.io/library/nginx:alpine`; настройте `registries.conf` |
| `permission denied` (rootless) | Нет делегирования cgroups или UID/GID mapping | Проверьте `cat /sys/fs/cgroup/user.slice/.../cgroup.controllers`; настройте `uidmap` |
| `cgroup: cannot set cgroup` | cgroups v1 или нет делегирования | Переведите на cgroups v2; добавьте `Delegate=` в `user@.service.d` |
| `short name resolution` | Короткое имя не разрешено | Используйте FQIN или настройте `unqualified-search-registries` в `registries.conf` |
| `port is already allocated` | Порт занят другим процессом | `sudo ss -tlnp \| grep :80`; остановите конфликтующий сервис или измените проброс |
| `no space left on device` | Переполнение хранилища | `podman system df`; `podman system prune -a --volumes` |
| `container exec failed` | Контейнер остановлен или нет процесса | `podman ps -a --filter id=<id>`; проверьте `podman logs <name>` |
| `authentication required` | Нет или неверный authfile | `podman login registry.example.com --authfile ~/.config/containers/auth.json` |
| `operation not permitted` | Seccomp или Capability заблокирована | Для отладки: `--security-opt seccomp=unconfined`; для production — добавьте нужную `--cap-add` |
| `dial tcp ...: connection refused` | Зависимый сервис не готов | Используйте `--health-cmd` + `Notify=healthy` в Quadlet или wait-скрипт |

### Диагностические команды

```bash
# События системы в реальном времени
podman events --filter event=health_status --format '{{.Time}} {{.Actor}} {{.Status}}'

# Проверка cgroup-лимитов
cat /sys/fs/cgroup/system.slice/podman-<id>.scope/memory.max

# Проверка делегированных контроллеров (rootless)
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers

# Живые метрики потребления ресурсов
podman stats -a --no-stream

# Проверка SELinux-контекста файлов тома
ls -laZ ~/.local/share/containers/storage/volumes/<имя>/_data
```

---

## Дополнительная информация

### Полезные флаги запуска (`podman run`)
- `-d`: Запуск в фоновом режиме (detached).
- `--rm`: Автоматическое удаление контейнера после завершения процесса.
- `--name <имя>`: Задать имя вместо автоматически сгенерированного.
- `-v /host:/cont:Z`: Монтирование тома с коррекцией меток SELinux (`:Z` — relabel, `:z` — shared; в rootless-режиме с пользовательским namespace актуальны `:U` и `keep-id`, см. [Тома](./podman_volumes_and_storage.md)).
- `--network=pasta`: Явное указание сетевого стека pasta (по умолчанию с Podman 5.0; в Podman 6.x — единственный поддерживаемый для rootless-контейнеров, `slirp4netns` удалён).
- `--replace`: Автоматически удаляет существующий контейнер с тем же именем перед запуском.
- `--restart <policy>`: Политика перезапуска (`no`, `on-failure[:N]`, `always`, `unless-stopped`).
- `--health-cmd "..."`: Проверка здоровья контейнера (подробнее — [Healthchecks](./podman_healthchecks.md)).
- `--secret <имя>`: Проброс секрета в контейнер (подробнее — [Секреты](./podman_secrets.md)).
- `--cap-drop=ALL --cap-add <cap>`: Минимальный набор Linux-привилегий (подробнее — [Изоляция Podman](./linux_isolation.md)).
- `--security-opt no-new-privileges`: Запрет на повышение привилегий через setuid/setgid.
- `--read-only`: Запуск с неизменяемой корневой ФС; используйте `--tmpfs` для writable директорий.
- `--tmpfs <path>`: Монтирование временной ФС в RAM (например, `/tmp`, `/run`).
- `--log-driver <driver>`: Драйвер логов (`journald`, `json-file`, `none`). По умолчанию rootful — `journald`, rootless — `k8s-file`.
- `--log-opt <key>=<value>`: Опции драйвера логов (`max-size`, `max-file` для json-file).
- `--pids-limit <N>`: Лимит PID (защита от fork-бомб).
- `--ulimit <type>=<soft>:<hard>`: Ограничения ресурсов процесса (`nofile`, `nproc` и др.).

### Глобальная конфигурация (`containers.conf` и `registries.conf`)
- **`containers.conf`**: глобальные флаги engine (`/etc/containers/containers.conf` или `~/.config/containers/containers.conf`). Влияет на `cgroup_manager`, `runtime` (`crun`/`runc`), `userns` и др.
- **`registries.conf`**: управляет разрешением коротких имен и зеркалами (`/etc/containers/registries.conf` или `~/.config/containers/registries.conf`). Для продакшена используйте FQIN или задайте `unqualified-search-registries = ["docker.io"]` явно.
- **`storage.conf`**: драйвер хранилища (`overlay`, `vfs`, `fuse-overlayfs`) и параметры монтирования (`/etc/containers/storage.conf` или `~/.config/containers/storage.conf`).

### Rootless-специфика
- Команда `podman unshare` открывает shell внутри пользовательского namespace Podman — полезно для отладки прав на файлы томов и поддиапазонов UID/GID.
- Лимиты ресурсов (`--cpus`, `--memory`) в rootless-режиме требуют **cgroups v2** (обязательна с Podman 6.0; cgroups v1 не поддерживается) и корректной настройки `uidmap`.
- Разрешение низких портов (например, 80) достигается через `net.ipv4.ip_unprivileged_port_start=80` или включением linger (`loginctl enable-linger $USER`).

Подробнее: [Rootless режим](./podman_rootless.md).

### Связанные разделы
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — роль `conmon`, Quadlet и интеграция с systemd.
- **[Rootless режим](./podman_rootless.md)** — особенности прав доступа и сети без root.
- **[Изоляция Podman](./linux_isolation.md)** — capabilities, seccomp, `--privileged`, cgroups v2.
- **[Миграция с Docker](./migration-from-docker.md)** — алиасы, Docker-совместимый сокет и перенос рабочих нагрузок.

### Ссылки
- **[Podman Farm](https://docs.podman.io/en/latest/markdown/podman-farm-build.1.html)** (англ.) — официальная документация мультиархитектурной сборки.
- **[Podman Update](https://docs.podman.io/en/latest/markdown/podman-update.1.html)** (англ.) — параметры изменения существующих контейнеров.
- **[Podman Commands](https://docs.podman.io/en/latest/Commands.html)** (англ.) — полный справочник команд CLI.

# force reindex test

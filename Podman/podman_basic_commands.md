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

### Rootless-специфика
- Команда `podman unshare` открывает shell внутри пользовательского namespace Podman — полезно для отладки прав на файлы томов и поддиапазонов UID/GID.
- Лимиты ресурсов (`--cpus`, `--memory`) в rootless-режиме требуют **cgroups v2** (обязательна с Podman 6.0; cgroups v1 не поддерживается) и корректной настройки `uidmap`.
- Разрешение низких портов (например, 80) достигается через `net.ipv4.ip_unprivileged_port_start=80` или включением linger (`loginctl enable-linger $USER`).

Подробнее: [Rootless режим](./podman_rootless.md).

### Связанные разделы
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — роль `conmon`, Quadlet и интеграция с systemd.
- **[Rootless режим](./podman_rootless.md)** — особенности прав доступа и сети без root.
- **[Миграция с Docker](./migration-from-docker.md)** — алиасы, Docker-совместимый сокет и перенос рабочих нагрузок.

### Ссылки
- **[Podman Farm](https://docs.podman.io/en/latest/markdown/podman-farm-build.1.html)** (англ.) — официальная документация мультиархитектурной сборки.
- **[Podman Update](https://docs.podman.io/en/latest/markdown/podman-update.1.html)** (англ.) — параметры изменения существующих контейнеров.
- **[Podman Commands](https://docs.podman.io/en/latest/Commands.html)** (англ.) — полный справочник команд CLI.

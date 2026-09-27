# Миграция с Docker на Podman

## Определения

**Миграция на Podman** — комплексный процесс перевода контейнерной инфраструктуры с Docker на Podman. Главный вектор миграции — переход от монолитного привилегированного демона (`dockerd`) к бездемонной (**daemonless**) архитектуре и работе без прав суперпользователя (**rootless**). Оба инструмента поддерживают спецификации **OCI**, поэтому образы и Dockerfile/Containerfile переносятся без пересборки.

**Quadlet** — нативный инструмент Podman для декларативного описания контейнеров, сетей, томов и подов в виде юнитов **systemd**. Является рекомендуемым стандартом для промышленной эксплуатации (Production) вместо классического Docker Compose. Файлы Quadlet размещаются в каталоге systemd-генератора: `/etc/containers/systemd/` (rootful) или `~/.config/containers/systemd/` (rootless) и автоматически преобразуются в юниты при `daemon-reload`.

**Pasta (Pack A Subtle Tap Abstraction)** — сетевой стек в пространстве пользователя, заменивший `slirp4netns` для rootless-контейнеров. Введен как драйвер по умолчанию в Podman 5.0, а в Podman 6.0 стал единственным поддерживаемым вариантом (slirp4netns удален из кодовой базы). Обеспечивает производительность, близкую к нативной, без NAT и с поддержкой IPv6.

**podman-docker** — пакет (в дистрибутивах Fedora/RHEL), устанавливающий команду `docker` как обертку над Podman и обеспечивающий эмуляцию Docker API через сокет. Аналог ручного алиаса `alias docker=podman`, но с поддержкой CLI-совместимости на уровне системы.

**podlet** — вспомогательная утилита (Rust), генерирующая файлы Quadlet из команды `podman run`/`podman pod create`, из файла Docker Compose или из уже существующего контейнера/пода/сети/тома. Упрощает конвертацию Compose-стеков в систему юнитов systemd.

**Fully Qualified Image Name (FQIN)** — полное имя образа с указанием реестра и пространства имен, например `docker.io/library/nginx`. Podman по соображениям безопасности не ищет короткие имена на Docker Hub по умолчанию: разрешение коротких имен регулируется файлом `registries.conf`.

**Актуально для:** Podman 6.x (стабильная ветка 6.0.x, проверено на 6.0.2), Docker Engine 29.x. Миграция ориентирована на Linux-хосты (rootless); на macOS/Windows рабочий процесс аналогичен, но контейнеры выполняются в виртуальной машине `podman machine`.

---

## Предварительные требования

### Требования к окружению

- **Podman >= 6.0** — для полной поддержки динамического обновления через `podman update`, стабильной работы `HealthOnFailure` и корректной обработки cgroups v2.
- **systemd >= 245** (рекомендуется >= 247) — требуется для Quadlet, таймеров автообновления и работы `sd_notify`. На дистрибутивах без systemd healthcheck и Quadlet работают только через CLI.
- **Cgroups v2** — обязателен для Podman 6.0; поддержка cgroups v1 удалена. Проверка: `stat -fc %T /sys/fs/cgroup` → должно быть `cgroup2fs`.
- **Kernel 5.11+** — для нативного overlay и поддержки idmapped mounts в rootless.
- **OCI Runtime**: по умолчанию используется `crun`; поддерживаются также `runc`, `runj`, `kata`, `runsc`.
- **Rootless-режим**: требуется `loginctl enable-linger $USER` для работы пользовательских юнитов systemd после выхода из сессии.
- **Skopeo** (опционально) — для копирования образов между реестрами без локального хранения.

### Инициализация окружения

```bash
# Проверка версии Podman
podman --version
# → podman version 6.0.2

# Проверка cgroups v2
stat -fc %T /sys/fs/cgroup
# → cgroup2fs

# Проверка systemd
systemctl --version
# → systemd 255 (255.4-1.el9_4.6)

# Проверка linger (для rootless)
loginctl show-user $USER -p Linger
# → Linger=yes

# Проверка UID/GID диапазонов
grep $USER /etc/subuid
# → user:100000:65536
grep $USER /etc/subgid
# → user:100000:65536
```

### Предмиграционная проверка (Pre-flight)

Перед началом миграции выполните аудит существующей инфраструктуры Docker:

```bash
# Список запущенных контейнеров
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# Список volumes
docker volume ls

# Список сетей
docker network ls

# Список secrets (Swarm)
docker secret ls

# Проверка использования docker-compose
find /opt -name "docker-compose*.yaml" -o -name "compose.yaml" 2>/dev/null

# Проверка Docker socket consumers
lsof /var/run/docker.sock | grep -v dockerd
```

Сохраните вывод команд для последующего сравнения после миграции.

---

## Основные концепции

### Мотивация миграции

1.  **Повышение безопасности**: Rootless-режим гарантирует, что даже при полном взломе приложения злоумышленник получит права обычного пользователя (UID 0 внутри контейнера мапируется на обычный UID хоста), а не root-доступ к хосту.
2.  **Архитектурная устойчивость**: Отсутствие центрального демона устраняет единую точку отказа. Каждый контейнер — это стандартный дочерний процесс операционной системы, управляемый через `conmon` и OCI Runtime.
3.  **Интеграция с systemd**: Podman «из коробки» использует системный планировщик (через Quadlet) для управления жизненным циклом, зависимостями (`After=`, `Requires=`), перезапуском и сбором логов через `journald` вместо файловых драйверов логирования Docker.
4.  **Совместимость с Kubernetes**: Podman использует концепцию **Pods** (групп контейнеров с общим сетевым пространством имен), что позволяет экспортировать локальные конфигурации напрямую в YAML-манифесты Kubernetes (`podman kube generate`) и запускать их обратно (`podman kube play`).
5.  **Низкое потребление ресурсов**: При отсутствии запущенных контейнеров Podman не держит в памяти постоянный процесс; демон Docker (`dockerd` + `containerd`) потребляет ~150–200 МБ в простое.
6.  **Автообновление образов**: Встроенный механизм `podman auto-update` (через `AutoUpdate=registry` в Quadlet) заменяет сторонний `watchtower`.

### Стратегии миграции

Выбор способа переноса зависит от объема и назначения инфраструктуры:

| Стратегия | Когда применять | Средства |
| :--- | :--- | :--- |
| **Алиас / пакет podman-docker** | Быстрый старт, интерактивная работа, скрипты с командами `docker` | `alias docker=podman`, пакет `podman-docker` |
| **Compose-режим** | Существующие `compose.yaml` без изменений; совместимость с воркфлоу Docker | `podman compose` (провайдер) или `podman-compose` |
| **Quadlet (systemd)** | Production на Linux: перезапуск, зависимости, автообновление, мониторинг | Ручное описание `.container`/`.network`/`.volume` либо генерация через `podlet` |
| **Поды + Kubernetes** | Экспорт в кластер, локальная проверка манифестов K8s | `podman kube play` / `podman kube generate` |

Рекомендуемый путь для Production на Linux: **Compose → Quadlet** (промежуточный этап — запуск через `podman compose` для проверки). Подробное сравнение моделей управления см. в разделе [Сравнение Podman и Docker](./podman_vs_docker.md).

### Сопоставление компонентов Docker ↔ Podman

| Компонент | Docker | Podman | Примечание по миграции |
| :--- | :--- | :--- | :--- |
| **Демон** | `dockerd` (клиент-сервер) | Отсутствует (daemonless) | Контейнеры — обычные процессы |
| **Команды CLI** | `docker ...` | `podman ...` | CLI совместимо, см. алиасы |
| **Сокет API** | `/var/run/docker.sock` | `/run/podman/podman.sock` (rootful), `/run/user/$(id -u)/podman/podman.sock` (rootless) | Через `podman.socket` |
| **Образы** | OCI-образы в `/var/lib/docker` | OCI-образы в `~/.local/share/containers/storage` | `docker save` → `podman load` |
| **Тома** | `docker volume`, драйвер `local` | `podman volume` | Данные копируются из `/var/lib/docker/volumes/<имя>/_data` |
| **Сети** | `bridge` (172.17.0.0/16) | `podman` (10.88.0.0/16), Netavark + Aardvark | `docker network create` → `podman network create` |
| **Секреты** | Docker Secrets (только Swarm) | `podman secret` (работает и без оркестратора) | Механизмы не совместимы напрямую |
| **Сборка** | BuildKit (требует демона) | Buildah / `podman build` (без демона, rootless) | Dockerfile переносится без изменений |
| **Compose** | `docker compose` (плагин) | `podman compose` / `podman-compose` | Compose Spec совместим |
| **Оркестрация** | Swarm | Нет; Kubernetes или поды + Quadlet | Swarm не поддерживается |
| **Автообновление** | Watchtower | `podman auto-update` | Через `AutoUpdate=registry` |

---

## Практические сценарии

### 1. Подготовка системы к Rootless-режиму

Для полноценной работы без прав root необходимо настроить маппинг идентификаторов и системные лимиты. Полное описание механизмов — в разделе [Безрутовый (Rootless) режим](./podman_rootless.md).

#### Настройка UID/GID (subuid/subgid)

Убедитесь, что для пользователя выделен диапазон дополнительных ID (обычно 65536 на пользователя):
```bash
grep $USER /etc/subuid
# → user:100000:65536

# Если диапазоны отсутствуют (от root)
# sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER
```

#### Разрешение низких портов и Linger

Чтобы разрешить запуск сервисов на портах < 1024 и гарантировать работу контейнеров после выхода из SSH:
```bash
# Разрешаем порты от 80
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/90-podman.conf
sudo sysctl -p /etc/sysctl.d/90-podman.conf

# Включаем Linger для пользователя (автозапуск пользовательских юнитов)
sudo loginctl enable-linger $USER
```

#### Проверка готовности

```bash
podman info --format '{{.Host.Security.Rootless}}'
# → true
```

### 2. Перенос образов

Образы используют общий формат OCI, поэтому их можно переносить без пересборки. Основные способы:

**Способ 1 — экспорт в архив (offline):**
```bash
# На стороне Docker — сохранить образ в архив
docker save nginx:latest -o nginx.tar

# На стороне Podman — загрузить архив
podman load -i nginx.tar

# Проверка
podman images
# → REPOSITORY          TAG      IMAGE ID ...
# → docker.io/nginx     latest   ...
```

**Способ 2 — копирование через реестр (skopeo):**
```bash
# Копирование без участия демона и без локального хранения
skopeo copy docker://docker.io/library/nginx:latest containers-storage:nginx:latest

# Либо напрямую между реестрами (Docker Hub → внутренний реестр)
skopeo copy docker://docker.io/library/postgres:16 docker://registry.example.com/postgres:16
```
Подробнее об инструменте — в разделе [Skopeo](./skopeo_overview.md).

**Способ 3 — прямая загрузка из реестра:**
```bash
# Важно: указывать полное имя образа (FQIN) или настроить registries.conf
podman pull docker.io/library/nginx:latest
```

**Сборка из Dockerfile** выполняется напрямую через `podman build` (бэкенд Buildah) без демона и без root:
```bash
podman build -t myapp:latest .
```

### 3. Перенос Docker Compose

Podman поддерживает спецификацию Compose (Compose Spec), поэтому большинство файлов работают «как есть». Подробности о различиях и ограничениях — в разделе [Podman Compose](./podman-compose.md).

#### Вариант А: Прямой запуск (Docker Compose V2 в качестве провайдера)

Установите пакет `podman-docker`, включите сокет и используйте привычный CLI:
```bash
# Подготовка сокета Podman (rootless)
systemctl --user enable --now podman.socket
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"

# Команда docker compose теперь работает через эмуляцию API Podman
docker compose up -d

# Либо встроенная обертка podman compose (провайдер — docker-compose)
podman compose up -d
```

#### Вариант Б: Нативный podman-compose

Python-утилита, исполняющая команды `podman` напрямую (без демона и сокета):
```bash
# Debian/Ubuntu
sudo apt install podman-compose
# Fedora
sudo dnf install podman-compose

podman-compose --version
# → podman-compose version 1.6.0

podman-compose up -d
```
`podman-compose` по умолчанию объединяет сервисы проекта в общий под (`pod_<проект>`), но с `--share=` (без общего network namespace), поэтому межсервисная связь работает по именам сервисов через DNS, а не через `localhost`.

#### Вариант В: Конвертация в Quadlet (Рекомендуется)

Для Production рекомендуется сгенерировать systemd-юниты из Compose-файла с помощью утилиты `podlet` (установка: `brew install podlet`, `cargo install podlet` или бинарник из [репозитория](https://github.com/containers/podlet)):

```bash
# Генерация юнитов из compose.yaml
# -i — добавить [Install]; -a — абсолютные пути хоста для bind-mount (обязательно!)
podlet -i -a compose compose.yaml

# Размещение файлов (для rootless-пользователя)
mkdir -p ~/.config/containers/systemd/
mv *.container *.network *.volume ~/.config/containers/systemd/

# Применение конфигурации
systemctl --user daemon-reload
systemctl --user start my-app.service

# Проверка
systemctl --user status my-app.service
```

Альтернатива stdout: флаг `-f .` записывает файлы в текущий каталог, флаг `-u` — сразу в каталог юнитов. Сгенерированные файлы **обязательно проверять перед запуском**: podlet не является полным конвертером и возвращает ошибку при неподдерживаемых опциях (например, `build:`, `deploy.resources`, сложные `ipam:` блоки).

Подробное описание форматов Quadlet и возможностей Podlet см. в [Quadlet и Podlet](./podman-quadlet-vs-podlet.md).

**Маппинг Compose → Quadlet:**

| Поле Compose | Директива Quadlet | Секция |
| :--- | :--- | :--- |
| `image:` | `Image=` | `[Container]` |
| `container_name:` | `ContainerName=` | `[Container]` |
| `ports:` | `PublishPort=` | `[Container]` |
| `volumes:` | `Volume=` | `[Container]` |
| `environment:` | `Environment=` | `[Container]` |
| `env_file:` | `EnvironmentFile=` | `[Container]` |
| `networks:` | `Network=` | `[Container]` |
| `healthcheck:` | `HealthCmd=`, `HealthInterval=`, `HealthRetries=`, `HealthOnFailure=` | `[Container]` |
| `secrets:` | `Secret=имя,type=mount,target=/run/secrets/имя` | `[Container]` |
| `depends_on:` | `After=` / `Requires=` | `[Unit]` |
| `restart:` | `Restart=` | `[Service]` |
| Объявленные сети | `.network` файл | — |
| Именованные тома | `.volume` файл | — |

Пример сгенерированного `db.container` (PostgreSQL):
```ini
[Unit]
Description=PostgreSQL database

[Container]
ContainerName=db
Image=docker.io/library/postgres:16
Environment=POSTGRES_USER=admin
Environment=POSTGRES_PASSWORD=secret
Volume=pgdata.volume:/var/lib/postgresql/data
Network=appnet.network

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
```

Замена `depends_on` на `[Unit] After=`/`Requires=` и вопросы готовности сервисов описаны в разделе [Управление зависимостями и готовностью](./podman-dependencies.md).

### 4. Перенос данных и томов

Тома Docker физически находятся в `/var/lib/docker/volumes/<имя>/_data` и не видны Podman напрямую. Перенос выполняется через резервную копию:

**На стороне Docker — создание архива тома:**
```bash
# Инспекция пути тома
docker volume inspect my_volume
# → "Mountpoint": "/var/lib/docker/volumes/my_volume/_data"

# Создание архива содержимого тома
docker run --rm -v my_volume:/data -v "$PWD":/backup alpine \
  tar czf /backup/my_volume.tar.gz -C /data .
```

**На стороне Podman — создание тома и восстановление:**
```bash
# Создание тома Podman
podman volume create my_volume

# Восстановление данных из архива
podman run --rm -v my_volume:/data -v "$PWD":/backup alpine \
  tar xzf /backup/my_volume.tar.gz -C /data
```

**Права доступа (rootless):** UID 0 внутри контейнера — это ваш UID на хосте. Если приложение в образе запускается под другим пользователем (например, UID 999 для PostgreSQL), владельца каталога нужно привести в соответствие:
```bash
# Вход в user namespace и рекурсивная смена владельца
podman unshare chown -R 999:999 ./data

# Альтернатива: флаг :U — рекурсивно назначает владельца внутри контейнера
podman run -v ./data:/var/lib/postgresql/data:U ...

# Или сохранить UID хоста: --userns=keep-id
```
Подробнее — в разделах [Безрутовый режим](./podman_rootless.md) и [Хранилище и тома](./podman_volumes_and_storage.md).

### 5. Перенос сетей и DNS

Модель сети отличается: Docker использует bridge + встроенный DNS на пользовательских сетях, Podman — Netavark + Aardvark (DNS включен по умолчанию во всех сетях, включая дефолтную `podman`). При rootless-режиме с pasta контейнеры по умолчанию изолированы друг от друга — для взаимодействия нужен общий под или rootless bridge-сеть (Netavark). Подробности — в разделе [Поды в Podman](./podman_pods.md).

**Перенос пользовательской сети:**
```bash
# На стороне Docker — параметры сети
docker network ls
docker network inspect mynet
# → "Subnet": "172.28.0.0/16", "Gateway": "172.28.0.1", "Driver": "bridge"

# На стороне Podman — создание сети с теми же параметрами
podman network create --subnet 172.28.0.0/16 --gateway 172.28.0.1 mynet

# Подключение контейнера
podman run -d --network mynet --name web nginx
```

**Различия DNS-имен:** в Docker имя контейнера доступно по имени в пользовательской сети; в Podman аналогично — контейнер резолвится по `ContainerName=` через Aardvark в общей сети. В rootless-режиме pasta обращение к хосту — по имени `host.containers.internal` (Podman 5.3+).

### 6. Перенос секретов

Docker Secrets работают только в Swarm-режиме. Podman предоставляет механизм `podman secret`, работающий без оркестратора:

```bash
# Создание секрета в Podman (из файла)
podman secret create db_password ./secrets/db_password.txt

# Использование при запуске контейнера
podman run -d --secret db_password,type=mount,target=/run/secrets/db_password nginx

# В Quadlet
# [Container]
# Secret=db_password,type=mount,target=/run/secrets/db_password

# Список и удаление
podman secret ls
podman secret rm db_password
```

### 7. Интеграция с systemd и автообновление

Quadlet передает контейнерам все возможности системных служб: автозапуск, перезапуск при сбоях, лимиты ресурсов, логи в `journald`.

```bash
# Логи контейнера теперь собираются системой
journalctl --user -u my-app.service -f

# Перезапуск настроен в [Service] Restart=on-failure
```

Автообновление образов — встроенный механизм вместо `watchtower`:
```ini
[Container]
Image=docker.io/library/nginx:latest
AutoUpdate=registry
```
```bash
podman auto-update --dry-run    # просмотр доступных обновлений
podman auto-update              # применение
```
Подробности — в разделе [Автообновление и откат в Podman](./podman_auto_update.md).

### 8. Интеграция с Kubernetes

Поды Podman напрямую совместимы с манифестами Kubernetes — это основной путь миграции из локальной среды в кластер.

```bash
# Экспорт пода в YAML-манифест (Podman 4.3+)
podman kube generate web-app-pod > web-app.yaml

# Экспорт в виде Deployment
podman kube generate --type deployment web-app-pod > web-app.yaml

# Локальный запуск манифеста (аналог docker compose, но для K8s)
podman kube play web-app.yaml
podman kube play --replace web-app.yaml

# Удаление ресурсов, развернутых через play
podman kube down web-app.yaml
```
> **Примечание:** устаревшие команды `podman generate kube` и `podman play kube` заменены группой команд `podman kube`. Подробнее — в разделе [Поды в Podman](./podman_pods.md).

### 9. Настройка сетевого стека Pasta

В Podman 5.0 стек `pasta` стал драйвером по умолчанию для rootless-режима; в Podman 6.0 он единственный поддерживаемый (slirp4netns удален). Он позволяет контейнеру видеть сетевую конфигурацию хоста напрямую, без NAT.

```bash
# Проверка используемого исполнителя
podman info --format '{{ .Host.Pasta.Executable }}'
# → /usr/bin/pasta

# Принудительное использование pasta
podman run --network=pasta ...

# Выбор сетевого интерфейса хоста
podman run --network=pasta:-i,en0 ...
```

Доступ к сервисам на `localhost` хоста из rootless-контейнера — опция `--network=pasta:--map-gw` (по умолчанию выключена из соображений безопасности). Подробнее о сетевом стеке — в разделе [Поды в Podman](./podman_pods.md).

### 10. Работа с Docker Socket

Если ваши инструменты (CI/CD агенты, мониторинг, Portainer) требуют `/var/run/docker.sock`, Podman может эмулировать Docker API через `podman.socket`:

```bash
# Для системного уровня (root)
sudo systemctl enable --now podman.socket
# Сокет: /run/podman/podman.sock
export DOCKER_HOST="unix:///run/podman/podman.sock"

# Для пользователя (rootless)
systemctl --user enable --now podman.socket
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
# → /run/user/$(id -u)/podman/podman.sock

# Проверка совместимости
docker info | grep "Runtime"
# → Runtime: crun
```

На некоторых дистрибутивах пакет `podman-docker` дополнительно настраивает эмуляцию привычного пути `/var/run/docker.sock`. Работа с Docker API через сокет подробно описана в разделе [Бездемонная архитектура](./podman_daemonless_architecture.md).

---

## Устранение неполадок

### Типичные ошибки миграции

| Ошибка / симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `overlay mount fails` | Драйвер overlay недоступен в rootless | `podman info` | Установите `fuse-overlayfs` или используйте `vfs` драйвер. |
| `no such file or directory` при copy | Неверный путь в контексте сборки | `ls -la <path>` | Проверьте `.dockerignore` и пути в Dockerfile. |
| `permission denied` на volume | UID mismatch между хостом и контейнером | `podman unshare ls -l /data` | Используйте флаг `:U` или `--userns=keep-id`. |
| `short name resolution` | Реестр не настроен в `registries.conf` | `podman pull nginx` | Используйте FQIN или добавьте `unqualified-search-registries`. |
| `service_healthy condition unreliable` | `podman-compose` не реализует `condition: service_healthy` корректно | `docker compose config` | Используйте внешнего провайдера для `podman compose` или перейдите на Quadlet. |
| `podman auto-update не обновляет` | Контейнер не управляется systemd или отсутствует FQIN | `podman auto-update --dry-run` | Убедитесь, что контейнер запущен через Quadlet с `AutoUpdate=registry` и полным именем образа. |
| `iptables: No such file or directory` | Podman 6 использует nftables, iptables-модуль ядра отсутствует | `iptables -L` | Установите `iptables-nft` или настройте firewall через nftables. |
| `cgroup v1 not supported` | Хост работает на cgroups v1 | `stat -fc %T /sys/fs/cgroup` | Обновите ядро и переключите на cgroups v2. |
| `Error: no memory events supported` | cgroup контроллеры не делегированы в user slice | `systemctl show --user --property=Delegate` | Добавьте `Delegate=yes` в `user@.service.d/delegate.conf`. |
| `podlet: unsupported option` | Compose-файл использует опции, не поддерживаемые podlet | `podlet ... 2>&1` | Удалите `build:`, `deploy.resources`, сложные `ipam:` из compose.yaml перед конвертацией. |

---

## Best Practices и откат

### Рекомендации по миграции

- **Rootless-first:** на Linux используйте rootless-режим для минимизации поверхности атаки. UID 0 внутри контейнера мапируется на обычный UID хоста.
- **Quadlet вместо Compose:** в production используйте `systemd`-юниты для управления жизненным циклом, зависимостей и автоматического перезапуска.
- **FQIN:** всегда указывайте полные имена образов в новых конфигурациях — это избавит от зависимости от `registries.conf` и обеспечит детерминированность в CI/CD.
- **Проверка podlet-юнитов:** никогда не запускайте сгенерированные Quadlet-файлы без ручного ревью — podlet не обрабатывает `build:`, `deploy.resources` и сложные `ipam:` блоки.
- **Бэкап хранилища:** перед обновлением Podman между мажорными версиями создайте резервную копию `~/.local/share/containers/storage` — миграция БД (BoltDB → SQLite) необратима.
- **Мониторинг через journald:** настройте централизованный сбор логов через `journalctl --user -u <service>` или `journalctl --user -u podman-auto-update.service`.

### Откат (Rollback)

Если миграция завершилась частично или требуется вернуться к Docker:

```bash
# 1. Остановка всех Podman-контейнеров
podman ps -q | xargs podman stop

# 2. Восстановление Docker демона
sudo systemctl enable --now docker

# 3. Восстановление данных (если тома были скопированы)
# Данные остаются в Podman storage; при необходимости скопируйте обратно
podman run --rm -v podman_volume:/data -v "$PWD":/backup alpine \
  tar czf /backup/restore_docker.tar.gz -C /data .

# На стороне Docker
docker run --rm -v docker_volume:/data -v "$PWD":/backup alpine \
  tar xzf /backup/restore_docker.tar.gz -C /data

# 4. Откат алиасов
# Удалите alias docker=podman из ~/.bashrc/.zshrc
# Или удалите пакет podman-docker
sudo dnf remove podman-docker  # Fedora/RHEL
sudo apt remove podman-docker  # Debian/Ubuntu
```

### Очистка окружения

```bash
# Удаление неиспользуемых образов, контейнеров, томов и сетей
podman system prune -a

# Удаление неиспользуемых образов (включая промежуточные слои)
podman image prune -a

# Удаление неиспользуемых томов (с подтверждением)
podman volume prune

# Удаление неиспользуемых сетей
podman network prune
```

---

## Версионирование

| Версия Podman | Версия Docker | Особенности миграции |
| :--- | :--- | :--- |
| **4.x** → **5.0** | Docker Engine 24.x–25.x | `pasta` по умолчанию для rootless; добавлен Startup Healthcheck (Gate). Проверьте скрипты, зависящие от `slirp4netns`. |
| **5.0** → **6.0** | Docker Engine 28.x–29.x | Удален `slirp4netns`; cgroups v1 не поддерживается; `iptables` удален из бэкенда firewall; BoltDB → SQLite. Требуется перезагрузка ядра на старых хостах. |
| **6.x** (текущий) | Docker Engine 29.x | Полная замена Docker API через `podman.socket`; `podman update` для динамического обновления параметров; улучшена обработка отката автообновления. |

---

## Сравнение с Docker

Детальное архитектурное сравнение, совместимость CLI, производительность и поддержка платформ см. в разделе [Сравнение Podman и Docker](./podman_vs_docker.md). Краткий обзор ключевых различий, влияющих на миграцию:

- **Демон vs Daemonless:** Docker требует постоянно работающего `dockerd`; Podman запускает контейнеры как обычные процессы через `conmon`.
- **Rootless:** в Docker rootless-режим реализован через отдельный `rootlesskit`; в Podman — нативно через User Namespaces.
- **Сеть:** Docker использует `bridge` (172.17.0.0/16) + `iptables`; Podman — Netavark + Aardvark (10.88.0.0/16) + `nftables`.
- **Автообновление:** Docker требует Watchtower (отдельный контейнер-монитор); Podman использует встроенный механизм через systemd-таймеры.
- **Сборка:** Docker BuildKit требует демона; Podman Buildah работает без демона и без root.

---

## Нюансы и ограничения

- **Явные реестры (Fully Qualified Image Names)**: Podman (в отличие от Docker) по соображениям безопасности требует указывать полный путь к образу: `docker.io/library/nginx` вместо просто `nginx`, либо настраивать `unqualified-search-registries` в `registries.conf` (при этом короткое имя может разрешиться в образ не с Docker Hub, а из вендорского реестра).
- **Права на тома (Volume Permissions)**: В rootless-режиме UID 0 внутри контейнера — это ваш UID на хосте. При монтировании существующих папок может потребоваться `podman unshare chown -R 0:0 /data`, флаг `:U` или `--userns=keep-id`.
- **Миграция БД Podman**: При переходе между мажорными версиями (например, Podman 4 → 5) происходит автоматическая миграция базы данных с BoltDB на SQLite. В Podman 6 унаследованный BoltDB полностью удален. Рекомендуется делать бэкап `~/.local/share/containers/storage` перед обновлением.
- **Отсутствие Docker Swarm**: Podman не поддерживает Swarm. Рекомендуемой альтернативой является переход на **Kubernetes** (через `podman kube generate`/`play`) или использование **Pods** в связке с Quadlet.
- **Cgroups v2**: Podman 6.0 требует cgroups v2; поддержка cgroups v1 удалена. На старых дистрибутивах (RHEL 7, Debian 10) миграция может потребовать обновления ядра.
- **Firewall**: Podman настраивает правила только через **nftables** (с Podman 6 бэкенд `iptables` удален); при наличии внешних правил iptables возможны конфликты.
- **Rootless-сеть pasta**: контейнеры изолированы друг от друга по умолчанию — прямой связи между ними нет; для взаимодействия нужен проброс портов хоста, общий под или rootless bridge (Netavark).
- **Healthcheck**: директива `HEALTHCHECK` из Dockerfile работает в Podman; для Quadlet используется маппинг `HealthCmd=`/`HealthInterval=` и т.д. Подробнее — в разделе [Проверки состояния (Healthcheck) в Podman](./podman_healthchecks.md).
- **Сборка образов**: Docker BuildKit поддерживает продвинутые функции кэширования и параллельной сборки; Buildah обеспечивает совместимость, но сложные сценарии могут требовать адаптации Dockerfile.
- **Автообновление**: работает только для контейнеров, управляемых systemd (Quadlet или `podman generate systemd --new`). Простые `podman run` контейнеры игнорируются, даже если помечены меткой `io.containers.autoupdate`.
- **Registry authentication**: `podman login` хранит учетные данные в `~/.config/containers/auth.json`; при переносе скопируйте этот файл или используйте `--authfile`.
- **Storage driver**: Docker использует `overlay2`; Podman поддерживает `overlay`, `vfs`, `devicemapper`, `btrfs`, `zfs`. В rootless по умолчанию `overlay` (требует `fuse-overlayfs` или kernel 5.11+ с idmapped mounts).

---

## Дополнительная информация

### Связанные разделы
- **[Безрутовый (Rootless) режим](./podman_rootless.md)** — механизмы маппинга UID/GID и подготовка системы.
- **[Podman Compose](./podman-compose.md)** — особенности запуска Compose-файлов и совместимые режимы.
- **[Бездемонная архитектура и Quadlet](./podman_daemonless_architecture.md)** — целевая модель управления через systemd.
- **[Сравнение Podman и Docker](./podman_vs_docker.md)** — архитектурные различия, производительность и поддержка платформ.
- **[Автообновление и откат в Podman](./podman_auto_update.md)** — замена Watchtower и настройка `AutoUpdate=registry`.
- **[Управление зависимостями и готовностью](./podman-dependencies.md)** — `Notify=healthy`, `sd_notify` и старт сервисов.
- **[Проверки состояния (Healthcheck) в Podman](./podman_healthchecks.md)** — маппинг `HEALTHCHECK` в Quadlet.

### Ссылки
- **[Migrating from Docker to Podman (официальный блог)](https://podman.io/blogs/2019/11/05/docker2podman)** — обзор процесса миграции (англ.).
- **[Podman 6.0 Release Notes](https://blog.podman.io/2026/07/introducing-podman-v6-0-0/)** — архитектурные изменения актуальной версии.
- **[podlet: генератор Quadlet](https://github.com/containers/podlet)** — конвертация Compose и команд в юниты systemd.
- **[podman-compose (man page)](https://docs.podman.io/en/latest/markdown/podman-compose.1.html)** — документация подкоманды `podman compose`.

### Рекомендации

- Для Production на Linux переходите с Compose на **Quadlet**: контейнеры получают управление, перезапуск, логи и мониторинг от `systemd`.
- При переносе Compose-файлов сначала запускайте стек через `podman compose`, затем конвертируйте в Quadlet через `podlet` и проверяйте сгенерированные юниты вручную.
- Перед обновлением Podman делайте бэкап `~/.local/share/containers/storage` — миграция БД между мажорными версиями необратима.
- Для CI/CD, где требуется Docker API, включайте `podman.socket` и настраивайте `DOCKER_HOST` на соответствующем уровне (rootful или rootless).
- Указывайте полные имена образов (FQIN) в новых конфигурациях — это избавит от зависимости от `registries.conf`.

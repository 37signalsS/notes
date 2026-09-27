# Сравнение Podman и Docker: Ключевые различия

## Определения

**Podman (Pod Manager)** и **Docker** — это инструменты для управления контейнерами, которые полностью поддерживают спецификации **OCI (Open Container Initiative)**. Это гарантирует, что образы, созданные в одном инструменте, будут корректно работать в другом. Несмотря на внешнюю схожесть интерфейса командной строки (CLI), инструменты имеют фундаментальные различия в архитектуре, модели безопасности и способах интеграции с операционной системой.

**Бездемонная архитектура (Daemonless)** — модель управления, при которой отсутствует постоянно работающий фоновый процесс с правами суперпользователя.

**Безрутовый режим (Rootless)** — возможность запуска и управления контейнерами от имени обычного пользователя без использования `sudo` или прав `root`.

**Актуально для:** Podman 6.x (стабильная ветка 6.0.x, проверено на 6.0.2), Docker Engine 29.x (проверено на 29.7.x). Смежное ПО: Podman Desktop 1.29, Docker Desktop 4.85.

---

## Основные концепции

### Архитектурные и технические различия

| Критерий | Docker | Podman |
| :--- | :--- | :--- |
| **Архитектура** | **Клиент-серверная**: Клиент CLI взаимодействует с фоновым демоном `dockerd` через сокет. Демон является "единой точкой отказа" и владеет всеми процессами. | **Бездемонная**: Podman — это утилита, которая напрямую запускает процессы контейнеров (через `conmon`). Каждый контейнер — независимый процесс. |
| **Безопасность** | По умолчанию требует `root`. Rootless-режим реализован через `rootlesskit` (отдельный пользовательский демон и сокет), что усложняет настройку. | **Rootless-first**: Изначально спроектирован для работы без root. Использует `User Namespaces` для маппинга UID/GID. |
| **Сетевой стек** | Rootful: `libnetwork` + `docker-proxy`; правила `iptables`/`nftables` настраивает демон. Rootless: `rootlesskit`, стек `gvisor-tap-vsock` (новый по умолчанию с Docker Engine 29.5; ранее `slirp4netns`). | Rootful: **Netavark** (написан на Rust) + `aardvark-dns`, правила firewall настраиваются через **nftables** (с Podman 6 `iptables` удален). Rootless: **pasta** (по умолчанию с Podman 5.0; в 6.x `slirp4netns` полностью удален). |
| **Интеграция с ОС** | Демон сам управляет перезапуском. Использование `systemd` ограничено и часто конфликтует с логикой Docker. | Глубокая интеграция через **Quadlet**. Контейнеры описываются декларативно и управляются `systemd` как нативные службы. |
| **Управление томами** | Традиционное монтирование. Проблемы с правами в rootless требуют ручного `chown`. Поддерживаются SELinux-метки `:Z`/`:z`. | Автоматический маппинг прав в rootless через флаг **`:U`** (unshare), который подстраивает UID/GID хоста под контейнер. Поддерживаются SELinux-метки `:Z`/`:z`. |
| **Сборка образов** | Встроенный **BuildKit**. Мощный, но требует демона. | Поддерживает `Dockerfile` через встроенный код **Buildah**. Позволяет собирать образы без демона и без root. |
| **Секреты** | Docker Secrets доступны только в режиме Swarm. | Встроенная поддержка секретов на уровне пользователя, хранятся в зашифрованном виде в локальном хранилище. |
| **Хранилище данных** | Образы и контейнеры в `/var/lib/docker`, конфигурация демона в `/etc/docker/`. | Rootless: данные в `~/.local/share/containers/storage`, конфигурация в `~/.config/containers/`. Rootful: `/var/lib/containers`. |
| **Состояние системы** | Отдельной БД нет — состояние ведется демоном в памяти и на диске. | Собственная БД состояния на **SQLite** (стандарт с 4.8; в Podman 6 унаследованный BoltDB удален). |
| **Экосистема** | Монолитный инструмент "все-в-одном". | Набор Unix-утилит: **Podman** (Run), **Buildah** (Build), **Skopeo** (Transport). |

### Совместимость командного интерфейса

CLI Podman спроектирован как совместимая замена Docker: большинство команд идентичны по синтаксису и назначению.

| Операция | Docker | Podman |
| :--- | :--- | :--- |
| Запуск контейнера | `docker run` | `podman run` |
| Список контейнеров | `docker ps` | `podman ps` |
| Логи | `docker logs` | `podman logs` |
| Команда внутри контейнера | `docker exec` | `podman exec` |
| Остановка/запуск/перезапуск | `docker stop` / `start` / `restart` | `podman stop` / `start` / `restart` |
| Список образов | `docker images` | `podman images` |
| Сборка образа | `docker build` | `podman build` |
| Загрузка образа | `docker pull` | `podman pull` |
| Публикация образа | `docker push` | `podman push` |
| Инспекция объектов | `docker inspect` | `podman inspect` |
| Удаление контейнера/образа | `docker rm` / `rmi` | `podman rm` / `rmi` |
| Управление сетями | `docker network ...` | `podman network ...` |
| Управление томами | `docker volume ...` | `podman volume ...` |
| Теги, экспорт, импорт | `docker tag` / `save` / `load` | `podman tag` / `save` / `load` |
| Авторизация в реестре | `docker login` / `logout` | `podman login` / `logout` |
| Статистика ресурсов | `docker stats` | `podman stats` |
| Информация о системе | `docker info` | `podman info` |
| Очистка | `docker system prune` / `system df` | `podman system prune` / `system df` |
| Оркестрация стеков | `docker compose up` | `podman compose up` / `podman-compose up` |

Для бесшовного перехода существуют два пути: алиас `alias docker=podman` или установка пакета `podman-docker`, который предоставляет команду `docker` (обертку над Podman), а также эмуляцию сокета `/var/run/docker.sock`.

### Сравнение производительности и ресурсов

По результатам тестов на актуальных версиях (Docker Engine 29.x vs Podman 6.x):

- **Потребление памяти (Idle):**
  - **Docker:** ~150–200 МБ (постоянно потребляется демоном `dockerd` и `containerd`).
  - **Podman:** 0 МБ (процессы отсутствуют, если нет запущенных контейнеров).
- **Масштабируемость:** При запуске более 100 контейнеров Podman потребляет на 25–30% меньше оперативной памяти за счет отсутствия оверхеда на управление через центральный демон.
- **Сетевая задержка (Rootless):** С переходом на драйвер **pasta** задержки в rootless-режиме Podman практически сравнялись с нативными: pasta не использует NAT и копирует IP-адреса хоста в контейнер. Стек `slirp4netns` (исторически используемый Docker rootless) имеет лимит пропускной способности из-за NAT; с Docker Engine 29.5 по умолчанию включен `gvisor-tap-vsock`, однако производительность нативного стека pasta остается преимуществом Podman.

### Оркестрация и управление стеками

- **Docker Compose v2:** стандартный способ описания многоконтейнерных приложений в экосистеме Docker (`docker compose up`).
- **Podman:**
  - `podman compose` — встроенная обёртка над Compose, использующая эмуляцию Docker API через сокет Podman.
  - `podman-compose` — независимый Python-инструмент. Подробнее см. [Podman Compose](./podman-compose.md).
  - **Quadlet** — рекомендуемый нативный способ декларативного управления контейнерами через `systemd`. Подробнее в сценарии ниже.
- **Совместимость с Compose:** Podman 6 значительно улучшил паритет с Docker API, что снизило трение при переносе существующих `compose.yaml`-файлов.

### Экосистема и инструменты

- **Автообновление образов:** `watchtower` (Docker) ↔ встроенный `podman auto-update` в связке с Quadlet (`AutoUpdate=registry`). Подробнее см. [Автообновление и откат в Podman](./podman_auto_update.md).
- **Графические интерфейсы:** Docker Desktop ↔ Podman Desktop (обеспечивает управление контейнерами, Kubernetes и Quadlet).
- **Мониторинг и логи:** в Podman логи контейнеров, управляемых через systemd, собираются в `journald`; в Docker — файловые драйверы логирования (`json-file`, `journald`, `splunk` и др.).
- **Реестры:** Docker по умолчанию работает с Docker Hub; Podman требует явно указывать полное имя образа (Fully Qualified Image Name) или настраивать `registries.conf`.
- **Сторонние инструменты:** большинство утилит (Portainer, CI-агенты) работают через API-сокет, поэтому поддерживают Podman через `podman.socket`.

### Поддержка платформ

- **Linux:** оба инструмента полностью поддерживаются; Podman — нативный выбор без GUI, Docker — через установку пакетов (`docker-ce`).
- **macOS:**
  - Docker Desktop: зрелый продукт с GUI, требует лицензию для крупных компаний.
  - Podman: `podman machine` + Podman Desktop (бесплатно, open source). С Podman 6 по умолчанию используется провайдер **libkrun** (Apple Silicon); поддержка Intel Mac прекращена.
- **Windows:**
  - Docker Desktop работает через WSL2.
  - Podman работает через WSL2 или Hyper-V (`podman machine`). С Podman 6 поддержка Windows 10 прекращена; запуск и остановка Hyper-V-машин больше не требуют прав администратора (создание — по-прежнему требует).

---

## Предварительные требования

### Версии и поддерживаемые платформы

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
| :--- | :--- | :--- | :--- |
| **Podman** | 4.0+ | 6.x | С Podman 6 удален cgroups v1, iptables-бэкенд сети и поддержка Windows 10. |
| **Docker Engine** | 20.10+ | 29.x | Docker Desktop 4.85+ включает новые rootless-сети (gvisor-tap-vsock). |
| **Ядро Linux** | 5.11+ | 6.1+ LTS | Нативное OverlayFS и полный cgroups v2. |
| **OCI Runtime** | `runc` 1.0+ | `crun` | Podman по умолчанию использует `crun` (меньше потребление памяти, лучше cgroups v2). |

### Требования к хосту

- **cgroups v2:** обязателен для Podman 6.x. Проверка: `stat -fc %T /sys/fs/cgroup` → должно быть `cgroup2fs`. Docker Engine 29.x работает с обоими, но для новых функций требует v2.
- **Kernel 5.11+:** для нативного overlay и поддержки idmapped mounts в rootless.
- **Rootless-подготовка:** при работе без root необходимы записи в `/etc/subuid` и `/etc/subgid` для пользователя. Подробнее — в [Пользовательские конфигурации](../Linux/SystemAdministration/Users/users_config_files.md).
- **SELinux/AppArmor:** на RHEL/Fedora включен по умолчанию; на Debian/Ubuntu — AppArmor. Оба инструмента совместимы, но политики отличаются.
- **FUSE overlay (rootless):** на ядрах < 5.11 требуется `fuse-overlayfs` для rootless-режима с драйвером `overlay`.

### Проверка окружения

```bash
# Версии
podman --version
docker --version

# cgroups
stat -fc %T /sys/fs/cgroup

# Kernel
uname -r

# Rootless-готовность
podman unshare cat /proc/self/uid_map
grep $USER /etc/subuid /etc/subgid

# Storage driver (rootless)
podman info --format '{{.Store.Info}}'
```

---

## Практические сценарии

### 1. Переход с Docker на Podman (Алиасы)

Для большинства пользователей переход бесшовен. Рекомендуется использовать алиас для сохранения привычных команд:

```bash
alias docker=podman
# Теперь можно выполнять привычные команды:
docker run -d --name app nginx
docker ps
```

Альтернативный вариант — установить пакет `podman-docker`:

```bash
# Fedora / RHEL
sudo dnf install -y podman-docker
# Команда docker и сокет /var/run/docker.sock будут эмулироваться Podman
```

Пошаговый план полного перехода описан в разделе [Миграция с Docker](./migration-from-docker.md).

### 2. Использование Quadlet вместо Docker Compose

Хотя `podman-compose` существует, рекомендуемый путь для Podman в Linux — использование **Quadlet**. Это позволяет `systemd` полностью контролировать жизненный цикл контейнера (запуск, мониторинг, зависимости).

**Пример Quadlet-файла (`myapp.container`):**
```ini
[Unit]
Description=My Web Application
After=network-online.target

[Container]
Image=docker.io/library/nginx:latest
PublishPort=8080:80
AutoUpdate=registry

[Install]
WantedBy=multi-user.target
```

После размещения файла в `~/.config/containers/systemd/` выполните:

```bash
systemctl --user daemon-reload
systemctl --user start myapp.service
```

Подробное сравнение Quadlet и Podlet, а также типовые сценарии использования см. в [Quadlet и Podlet](./podman-quadlet-vs-podlet.md).

### 3. Работа с Kubernetes манифестами

Podman позволяет протестировать манифесты K8s локально без развертывания кластера (minikube/kind).

```bash
# Запуск пода из YAML файла Kubernetes
podman kube play deployment.yaml

# Генерация манифеста K8s из запущенного контейнера
podman kube generate my-app-container > pod.yaml
```

### 4. Совместная работа Docker и Podman на одном хосте

Инструменты не конфликтуют по умолчанию, так как используют раздельные хранилища и сетевые подсети, но требуют учета при назначении портов.

```bash
# Проверка раздельных хранилищ
sudo du -sh /var/lib/docker          # данные Docker
du -sh ~/.local/share/containers     # данные rootless-Podman

# Сетевые подсети по умолчанию не пересекаются
docker network inspect bridge | grep Subnet
# → "Subnet": "172.17.0.0/16"
podman network inspect podman | grep subnet
# → "subnet": "10.88.0.0/16"
```

- **Порты хоста:** оба инструмента могут связывать один и тот же диапазон портов, поэтому один и тот же порт одновременно могут использовать только разные инструменты — при запуске контейнеров следите за коллизиями.
- **Стек:** Docker использует `dockerd` + `containerd`, Podman — собственный daemonless-стек (`conmon` + `crun`/`runc`), поэтому процессы изолированы друг от друга.
- **Сокеты:** пути `docker.sock` и `podman.sock` различны; при одновременной работе включайте их через разные сервисы systemd.

---

## Безопасность и hardening

### Сравнение механизмов безопасности по умолчанию

| Механизм | Docker | Podman |
| :--- | :--- | :--- |
| **Seccomp** | Профиль `default` (блокирует ~50 syscall). | Профиль из `/usr/share/containers/seccomp.json` (блокирует ~30+ syscall). Переопределяется через `/etc/containers/seccomp.json`. |
| **AppArmor** | Профиль `docker-default`. | Профиль `containers-default` (более строгий). |
| **SELinux** | Автоматические метки `svirt_lxc_net_t`. | Уникальные MCS-метки на каждый контейнер (`container_file_t`). Для томов: `:Z` (общая) / `:z` (индивидуальная). |
| **Capabilities** | По умолчанию удаляет `NET_RAW`, `SYS_CHROOT` и др. | По умолчанию удаляет `NET_RAW`, `SYS_CHROOT`, `MKNOD`; `mount` разрешен только с `CAP_SYS_ADMIN` (отсутствует по умолчанию). |
| **NoNewPrivileges** | Выключен по умолчанию. | Выключен по умолчанию, но активно рекомендуется через `--security-opt no-new-privileges`. |
| **Rootless** | Через `rootlesskit` + отдельный пользовательский демон. | Нативный User Namespaces + маппинг UID/GID; без дополнительных демонов. |
| **Content Trust** | Docker Content Trust (Notary v1) — устаревший; Cosign. | Cosign, Notary v2 через `policy.json`. Подробнее — в [Подпись и верификация образов](../Docker/Docker_security/image_signature_and_verification.md). |

### Практические различия

- **SELinux в Podman:** каждый контейнер получает уникальную MCS-метку, что предотвращает доступ одного контейнера к файлам другого. При монтировании томов используйте `:Z` для общей маркировки или `:z` для индивидуальной.
- **NoNewPrivileges:** критично для production. В Docker включается через `--security-opt no-new-privileges`; в Podman — аналогично или через `SecurityOptNoNewPrivileges=true` в Quadlet.
- **Rootless-сеть:** в Docker rootless контейнеры видят общую виртуальную сеть через `rootlesskit`; в Podman (режим `pasta`) контейнеры изолированы друг от друга по умолчанию — для взаимодействия нужен общий pod или проброс портов.
- **Привилегированный режим:** в Podman `--privileged` эквивалентен `--privileged` в Docker, но в rootless-режиме ограничения User Namespace ослабляют изоляцию.

### Рекомендации по hardening

1. Никогда не используйте `--privileged` и `--security-opt seccomp=unconfined` в production.
2. Включайте `no-new-privileges` для всех production-контейнеров.
3. Используйте минимальный набор `--cap-add`; явно отказывайтесь от опасных (`SYS_ADMIN`, `SYS_PTRACE`).
4. Для томов всегда указывайте `:Z`/`:z` (SELinux) или `:U` (Podman rootless маппинг).
5. Настройте `policy.json` для принудительной проверки подписей образов.

---

## Управление ресурсами и cgroups

### Cgroups v2

Podman 6.x требует **cgroups v2** (унифицированная иерархия). Docker Engine 29.x поддерживает v2, но может работать и с v1.

```bash
# Проверка версии cgroups
stat -fc %T /sys/fs/cgroup
# → cgroup2fs (требуется для Podman 6)
```

### Лимиты ресурсов

| Параметр | Docker | Podman | Примечание |
| :--- | :--- | :--- | :--- |
| **Memory** | `--memory`, `--memory-reservation` | `--memory`, `--memory-swap` | В rootless Podman для `memory.max` требуется делегирование cgroup-контроллера. |
| **CPU** | `--cpus`, `--cpu-shares`, `--cpuset-cpus` | `--cpus`, `--cpu-shares`, `--cpuset-cpus` | Оба инструмента применяют лимиты через cgroups. |
| **PIDs** | `--pids-limit` | `--pids-limit` | Защита от fork-бомб. В rootless требует делегирования `pids` контроллера. |
| **OOM** | Убивает контейнер при превышении лимита | Убивает контейнер при превышении лимита | Оба инструмента регистрируют событие в логах. |
| **I/O** | `--blkio-weight`, `--device-read-bps` | `--blkio-weight`, `--device-read-bps` | Через cgroups v2 blkio контроллер. |

### Делегирование cgroups в rootless

Для применения лимитов в rootless-режиме требуется делегировать контроллеры в user cgroup:

```bash
# /etc/systemd/system/user@.service.d/delegate.conf
[Service]
Delegate=cpu cpuset io memory pids
```

```bash
systemctl --user daemon-reload
```

### Проверка активных лимитов

```bash
# Cgroup-путь Podman-контейнера (rootful)
cat /sys/fs/cgroup/system.slice/podman-<id>.scope/memory.max
cat /sys/fs/cgroup/system.slice/podman-<id>.scope/cpu.max

# Или через podman inspect
podman inspect --format '{{.HostConfig.Memory}}' <container>
podman inspect --format '{{.HostConfig.CpuShares}}' <container>
```

---

## Реестры и аутентификация

### Короткие имена vs FQIN

- **Docker:** разрешает короткие имена (`nginx`, `alpine`) — автоматически подставляет `docker.io`.
- **Podman:** по умолчанию требует **Fully Qualified Image Name (FQIN)** — `docker.io/library/nginx:latest`. Короткие имена разрешаются только через `registries.conf`.

### Конфигурация реестров

Файл `registries.conf` управляет разрешением коротких имен и mirrors:

- **Rootless:** `~/.config/containers/registries.conf`
- **Rootful:** `/etc/containers/registries.conf`

```ini
# Пример: разрешение коротких имен и mirrors
unqualified-search-registries = ["docker.io"]

[[registry]]
prefix = "docker.io"
location = "docker.io"

[[registry.mirror]]
location = "registry.example.com:5000"
pull-from-mirror = true
```

### Аутентификация

Файл `auth.json` хранит учетные данные:

- **Rootless:** `${XDG_RUNTIME_DIR}/containers/auth.json` (эфемерный; при перезагрузке теряется). Персистентный вариант: `~/.config/containers/auth.json`.
- **Rootful:** `/run/containers/0/auth.json`.

```bash
# Логин (сохраняет в персистентный файл для rootless)
podman login --authfile ~/.config/containers/auth.json registry.example.com

# Использование в CI
export REGISTRY_AUTH_FILE=/path/to/auth.json
```

### Content Trust и подписи

- **Docker:** Docker Content Trust (Notary v1) — устаревший. Cosign — современный стандарт.
- **Podman:** Cosign, Notary v2. Проверка подписей настраивается через `/etc/containers/policy.json`.

```json
{
  "default": [
    {
      "type": "insecureAcceptAnything"
    }
  ],
  "transports": {
    "docker-daemon": {
      "": [
        {
          "type": "insecureAcceptAnything"
        }
      ]
    }
  }
}
```

---

## Логирование и аудит

### Драйверы логирования

| Драйвер | Docker | Podman | Особенности |
| :--- | :--- | :--- | :--- |
| **json-file** | По умолчанию | Поддерживается | Файлы в `/var/lib/docker/containers/` или `~/.local/share/containers/storage/containers/`. |
| **journald** | Опция `--log-driver=journald` | По умолчанию (rootful) | Логи в `journalctl -u <unit>` или `journalctl -t <container>`. |
| **syslog** | Опция `--log-driver=syslog` | Поддерживается | Требует конфигурации контейнера. |
| **fluentd / splunk** | Плагины | Поддерживается через `--log-driver` | |

### Практические различия

- **Podman + systemd:** логи контейнеров, управляемых через Quadlet, автоматически попадают в `journald` с меткой `CONTAINER_NAME=`.
- **Docker:** файловые драйверы (`json-file`) по умолчанию; `journald` требует явного включения.
- **Rootless Podman:** логи доступны через `journalctl --user -u my-container.service` (если используется Quadlet) или напрямую из `~/.local/share/containers/storage/containers/`.

### Аудит событий

```bash
# Docker: события через docker events
docker events --filter 'container=my-app'

# Podman: аналогично
podman events --filter 'container=my-app'

# Через journald (systemd/Qudlet)
journalctl --user -u myapp.service --since "1 hour ago"
```

---

## CI/CD и автоматизация

### Docker-in-Docker vs Podman-in-Container

| Подход | Docker | Podman |
| :--- | :--- | :--- |
| **DinD/Podman-in-Podman** | Требует `--privileged` контейнер | Поддерживается rootless без `--privileged` (через `fuse-overlayfs` или `vfs`). |
| **Сборка образов** | `docker build` (BuildKit требует демона) | `podman build` / `buildah build` (daemonless, rootless). |
| **Кэширование** | `--cache-from`, `--cache-to` | `--cache-from`, `--cache-to`, `--layers=true`. |
| **Rootless в CI** | Сложная настройка через `rootlesskit` | Нативная поддержка; требует subuid/subgid. |

### Пример: GitLab CI с Podman

```yaml
build_image:
  image: docker.io/library/gitlab/gitlab-runner:latest
  services:
    - docker:dind
  variables:
    DOCKER_HOST: tcp://docker:2376
```

Эквивалент с Podman (без DinD):

```yaml
build_image:
  image: quay.io/podman/stable:latest
  variables:
    STORAGE_DRIVER: overlay
```

---

## Валидация миграции

После перехода с Docker на Podman выполните проверки:

```bash
# 1. Проверка совместимости CLI
podman --version
docker --version

# 2. Проверка хранилищ
docker info --format '{{.DockerRootDir}}'
podman info --format '{{.Store.GraphRoot}}'
# → /var/lib/docker vs ~/.local/share/containers/storage

# 3. Проверка образов
docker images
podman images

# 4. Функциональный прогон
docker run -d --name test-docker nginx:alpine
podman run -d --name test-podman docker.io/library/nginx:alpine
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080
# → 200

# 5. Проверка сети
docker network inspect bridge | grep Subnet
podman network inspect podman | grep subnet

# 6. Проверка томов
docker volume inspect my-data
podman volume inspect my-data

# 7. Проверка systemd/Qudlet (если используется)
systemctl --user list-units 'myapp*'
```

### Чеклист миграции

- [ ] Все `docker run` заменены на `podman run` или протестированы через алиас
- [ ] Docker Compose файлы протестированы через `podman compose`
- [ ] Данные томов мигрированы из `/var/lib/docker/volumes/`
- [ ] Образы выгружены через `docker save` и загружены через `podman load`
- [ ] Сети пересозданы в Podman (разные подсети по умолчанию)
- [ ] CI/CD пайплайны обновлены для работы с Podman
- [ ] Мониторинг и логи переключены на journald (если используется Quadlet)

---

## Типичные проблемы и решения

| Ошибка / симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `overlay mount fails` | Драйвер overlay недоступен в rootless | `podman info` | Установите `fuse-overlayfs` или используйте `vfs` драйвер. |
| `no such file or directory` при copy | Неверный путь в контексте сборки | `ls -la <path>` | Проверьте пути относительно корня контекста; используйте абсолютные пути внутри смонтированного rootfs. |
| `unable to find user` | UID:GID не существует в образе | `podman inspect --format '{{.User}}' <ctr>` | Создайте пользователя через `podman run -- useradd <username>` или используйте числовой UID. |
| `permission denied` на томах | Ошибка маппинга UID/GID или SELinux | `podman unshare ls -la <path>` | Используйте `:Z`/`:z` для SELinux, `:U` для rootless маппинга. |
| `timeout waiting for connection` | Контейнер не смонтирован или удален | `podman ps -a` | Пересоздайте контейнер и повторно смонтируйте. |
| `port is already allocated` | Коллизия портов с Docker | `ss -tlnp \| grep :80` | Освободите порт или используйте другой хост-порт. |
| `cgroups v1` | Хост работает на устаревшей версии | `stat -fc %T /sys/fs/cgroup` | Переведите систему на cgroups v2. |
| `short name resolution` | Podman не разрешает короткие имена | `podman pull nginx` (ошибка) | Используйте FQIN `docker.io/library/nginx` или настройте `registries.conf`. |
| `Docker socket not found` | Инструменты ожидают `/var/run/docker.sock` | `ls -la /var/run/docker.sock` | Установите `podman-docker` или включите `podman.socket`. |
| `rootless network isolation` | Контейнеры не видят друг друга (pasta) | `podman network inspect` | Используйте общий pod или настройте rootless bridge через Netavark. |

---

## Рекомендации

### Production-hardening

- **Rootless-first:** на Linux используйте rootless-режим для минимизации поверхности атаки. UID 0 внутри контейнера мапируется на обычный UID хоста.
- **Quadlet вместо Compose:** в production используйте `systemd`-юниты для управления жизненным циклом, зависимостей и автоматического перезапуска.
- **Сетевой стек:** учитывайте разницу `pasta` (Podman) vs `bridge` (Docker) при проектировании сетевой топологии; для контейнеров, требующих прямого взаимодействия, используйте общий pod или настройте bridge.
- **Реестры:** всегда используйте FQIN в production или предварительно настроенный `registries.conf`. Настройте mirrors для корпоративных реестров.
- **Логирование:** переведите все контейнеры на `journald` (Podman) для централизованного сбора логов через `systemd-journald`.
- **Мониторинг:** используйте `podman stats` или `cAdvisor` (если требуется Prometheus); логи из `journald` экспортируются через `promtail` или `vector`.

### Выбор инструмента

| Сценарий | Рекомендация |
| :--- | :--- |
| **Новый проект на Linux** | Podman (rootless, ресурсоэффективный, systemd-native). |
| **Миграция существующего стека** | Начните с алиаса `podman-docker`, затем перейдите на Quadlet для production. |
| **macOS / Windows разработка** | Podman Desktop (open source) или Docker Desktop (если требуется лицензионный функционал). |
| **Enterprise CI/CD** | Podman (без DinD, rootless, меньший оверхед). |
| **Kubernetes-направленность** | Podman (нативная поддержка подов и `kube play`/`generate`). |

---


---

## Нюансы и ограничения

### Краткий справочник

| Ограничение | Docker | Podman |
| :--- | :--- | :--- |
| **Docker Socket** | Стандарт индустрии. Многие инструменты (Portainer, CI-агенты) требуют `/var/run/docker.sock`. | Поддерживает эмуляцию сокета через `podman.socket`, но в rootless-режиме путь отличается (`$XDG_RUNTIME_DIR/podman/podman.sock`). |
| **Docker Swarm** | Нативная поддержка оркестрации. | **Не поддерживается**. Podman ориентирован на локальный запуск или Kubernetes. |
| **Windows / macOS** | Docker Desktop — очень зрелый продукт с GUI. | Podman Desktop активно развивается; на macOS по умолчанию провайдер `libkrun` (Apple Silicon, Intel не поддерживается с Podman 6), на Windows — WSL2/Hyper-V (Windows 10 не поддерживается с Podman 6). |
| **Короткие имена образов** | По умолчанию ищет на Docker Hub. | Требует явного указания реестра (например, `docker.io/`) или настройки `registries.conf` для безопасности. |
| **Cgroups v2** | Ориентирован на cgroups v2 (после перехода на containerd 2.x). | Строгое требование: в Podman 6 поддержка cgroups v1 удалена. |
| **Firewall** | Поддерживает `iptables` и `nftables`. | Только `nftables` (с Podman 6 бэкенд `iptables` удален). |
| **Rootless-сеть** | Изоляция через rootlesskit; контейнеры видят виртуальную сеть. | В режиме `pasta` контейнеры изолированы друг от друга по умолчанию — прямой связи между ними нет; для взаимодействия нужен проброс портов хоста, общий pod или rootless bridge (Netavark). |

### Rootless-режим: обратная сторона архитектуры

Rootless-режим — ключевое архитектурное преимущество Podman, но он приносит и конкретные ограничения, с которыми приходится мириться на практике.

#### Порты ниже 1024

Ядро Linux не позволяет непривилегированному процессу слушать порты ниже 1024. В rootless-контейнере опубликовать `PublishPort=80:80` напрямую не получится. Доступны два обхода:

- изменить `net.ipv4.ip_unprivileged_port_start` через `sysctl`;
- поднять reverse-proxy на непривилегированном порту (например, 8080) и пробрасывать его дальше средствами хоста.

На практике это часто означает перенос обратного прокси в отдельный LXC-контейнер или использование внешнего балансировщика, чтобы отвязать его от backend'ов. Детали работы с rootless-сетью и пробросом портов см. в [Безрутовый (Rootless) режим](./podman_rootless.md).

#### UID-маппинг и права на bind-mount

Rootless-контейнеры используют User Namespaces: UID 0 внутри контейнера превращается в непривилегированный UID на хосте через `subuid`/`subgid`. При bind-mount'е существующих директориев файлы, созданные внутри контейнера, на хосте принадлежат UID из диапазона `subuid`, и `chown`/`chmod` превращаются в отдельное испытание.

Для работы с правами существует `podman unshare`, который пускает в те же namespace'ы, что видит контейнер. Более системный обход — флаг `--userns=keep-id` (маппит UID 0 на тот же UID, под которым вы залогинены) или суффикс `:U` для volume (Podman автоматически выполнит `chown` при монтировании). Оба механизма подробно описаны в [Безрутовый (Rootless) режим](./podman_rootless.md) и [Хранилище и работа с файловой системой](./podman_volumes_and_storage.md).

#### Требования файловой системы к rootless-overlay

Rootless-overlay для хранилища образов требует от файловой системы поддержки `d_type` (тип файла возвращается прямо в записи каталога). Без `d_type` Podman откатывается на драйвер `vfs`, который работает надёжно, но медленнее и жёстче расходует место, так как не может эффективно использовать слои между образами.

На практике для систем с ext4/XFS `d_type` есть из коробки. Проблемы могут возникнуть на сетевых ФС (NFS) или экзотическом хранилище. На NFS нативный overlay не работает; используется `fuse-overlayfs` с накладными расходами. См. [Безрутовый (Rootless) режим](./podman_rootless.md) и [Хранилище и работа с файловой системой](./podman_volumes_and_storage.md).

### Отсутствие Docker Swarm

В rootless Podman Docker Swarm отсутствует полностью и не предвидится в обозримом будущем — это осознанное архитектурное решение. Если планировалось использовать Swarm для оркестрации, стоит сразу смотреть в сторону Kubernetes (через `podman kube play`/`generate`) или выбирать другой инструмент. В инфраструктуре, которая уже завязана на Swarm, это блокер.

### Неполная совместимость с Docker Compose

`podman-compose` — независимый проект, а не встроенный аналог `docker compose`. На практике совместимость с `docker-compose.yml` часто требует правок:

- **DNS-резолвинг:** при подключении сервиса к нескольким пользовательским сетям DNS по имени сервиса может не резолвиться стабильно из сетей, к которым сервис был подключён не первым;
- **external: true:** `podman-compose` по умолчанию добавляет префикс имени проекта к имени сети — если имена не совпадают буквально, вместо переиспользования существующей сети получается попытка создать новую;
- **Имена контейнеров и сетей:** по умолчанию используется разделитель `_` вместо `-` (принятого в новых версиях Docker Compose), что может сломать парсящую автоматизацию;
- **Функции Compose:** не все версии `docker-compose.yml` (сложные `healthcheck`, `depends_on` с условиями, профили) поддерживаются идентично — часть фич работает «почти так же», часть требует правок, часть удаляется.

Формальный путь — переход на нативный **Quadlet** (см. [Бездемонная архитектура](./podman_daemonless_architecture.md)), что снимает большинство проблем, но это уже не «тот же самый docker-compose.yml без изменений», а миграция на другой формат. Для проектов с десятками compose-файлов из чужих репозиториев (типично для self-hosting) нужно быть готовым к точечным правкам. Подробности о podman-compose см. в [Podman Compose](./podman-compose.md).

### macOS и Windows: виртуальная машина остаётся

Отсутствие демона — преимущество Podman только на Linux. На macOS и Windows контейнеры не могут работать нативно (другое ядро), и оба инструмента — Docker Desktop и `podman machine` — решают это одинаково: поднимают легкую Linux-VM и запускают контейнеры уже внутри неё.

На хосте параллельно с VM крутится `gvproxy`, который через SSH-туннель прокидывает сетевой доступ и Docker-совместимый сокет внутрь машины. То есть «просто VM» на практике — это VM плюс обвязка вокруг неё. В команде, где часть разработчиков работает на macOS, часть на Windows, разница с Docker Desktop по факту меньше, чем кажется из маркетинговых сравнений. Детали архитектуры и управления VM см. в [Podman Machine](./podman_machine.md).

### Отсутствие встроенной оркестрации на несколько хостов

Podman по design закрывает задачи одного хоста. Если требуется:

- горизонтальное масштабирование сервиса под нагрузкой;
- HA-кластер из нескольких физических узлов;
- service discovery между узлами «из коробки»;

готового решения у Podman нет. Генерация Kubernetes-манифестов через `podman generate kube` облегчает миграцию, но сама миграция означает разворачивание полноценного Kubernetes (k3s, MicroK8s, RKE2) со всеми сопутствующими компонентами: etcd, control-plane, CNI-плагины.

Docker Swarm при всех недостатках хотя бы предлагает в меру простое родное решение по переходу от одного хоста к нескольким — у Podman такой «промежуточной ступеньки» нет и не будет в обозримом будущем. Сравнение с Kubernetes см. в [Podman и Kubernetes](./podman_kubernetes.md).

### Экосистема и инструменты

Технически Podman достаточно зрелый проект, но по охвату экосистемы Docker всё ещё далеко впереди:

- **GUI.** Podman Desktop активно развивается и уже пригоден для повседневной работы, но по количеству встроенных расширений, готовых интеграций и «вылизанности» интерфейса уступает Docker Desktop;
- **Готовые туториалы.** Абсолютное большинство инструкций для проектов с контейнеризацией написаны под `docker run`/`docker-compose up`. Работать с ними приходится либо через алиас `docker=podman` (помогает в большинстве случаев), либо вручную адаптировать под rootless-специфику — SELinux-лейблы `:Z`/`:z` в оригинальных доках почти никогда не упоминаются, хотя при работе на Fedora/RHEL без них контейнер не увидит примонтированную директорию;
- **Инструменты, жёстко завязанные на docker.sock.** Некоторые популярные утилиты (дашборды, CI-раннеры, мониторинговые агенты) исторически обращаются напрямую к Docker socket. Podman предоставляет Docker-совместимый REST API через `podman system service`, но решение не идеальное, и для нишевых инструментов иногда приходится искать форк с поддержкой Podman или оставлять сервис на Docker. См. [Бездемонная архитектура](./podman_daemonless_architecture.md);
- **Реестры.** Podman по умолчанию не привязан к одному реестру, и новичков первое время путает необходимость явно указывать полный путь до образа (`docker.io/library/nginx` вместо `nginx`), если в `registries.conf` не настроены `unqualified-search-registries`. На дистрибутивах, не связанных с Red Hat, настраивать их приходится вручную. Конфигурация реестров подробно описана в разделе [Реестры и аутентификация](#реестры-и-аутентификация).

### Более высокий порог входа для новичков

Docker долгие годы был синонимом контейнеризации, потому что скрывал сложные решения за простой оболочкой: один демон, одна команда `docker run`, и всё «просто работает» от root. Podman требует большего понимания происходящего под капотом:

- что такое `subuid`/`subgid` и что произойдёт, если диапазоны не настроены или пересекаются;
- разница между rootless и rootful режимом и когда переключаться на второй оправданно;
- SELinux-лейблы на volume'ах в Fedora/RHEL-семействе, без которых контейнер не увидит примонтированную директорию;
- cgroups v2 и поведение Podman на системах, где он ещё не включён по умолчанию.

Для человека, который уже настраивал инфраструктуру с контейнерами, это не проблема, а естественная часть процесса. Но если цель — просто побыстрее поднять сервис, первое знакомство с Podman может ощущаться заметно более болезненным, чем с Docker.

### Когда недостатки действительно важны

Подытоживая, три ситуации, где минусы Podman перевешивают его архитектурные плюсы:

1. **Нужна оркестрация на несколько хостов здесь и сейчас.** Тогда либо Docker Swarm как временное решение, либо сразу переходить на Kubernetes.
2. **Инфраструктура завязана на инструменты, строго требующие доступа к `docker.sock`.** Альтернатив под Podman нет.
3. **Команда разработчиков работает преимущественно на macOS/Windows.** Избавиться от VM-прослойки, переходя с Docker Desktop, не получится.

Во всех остальных сценариях — а для Linux-систем это подавляющее большинство — недостатки скорее про «нужно один раз разобраться и настроить», чем про «категорически не подходит».

---

## Дополнительная информация

### Связанные разделы

- **[Бездемонная архитектура](./podman_daemonless_architecture.md)** — подробный разбор работы без демона.
- **[Безрутовый (Rootless) режим](./podman_rootless.md)** — механизмы маппинга UID/GID.
- **[Изоляция в Podman](./linux_isolation.md)** — AppArmor, SELinux, seccomp, capabilities.
- **[Buildah: Концепции и практика сборки](./buildah_overview.md)** — сравнение механизмов сборки BuildKit и Buildah.
- **[Автообновление и откат в Podman](./podman_auto_update.md)** — `AutoUpdate=registry` в Quadlet.

### Ссылки

- **[Введение в Podman 6.0](https://blog.podman.io/2026/07/introducing-podman-v6-0-0/)** — официальный анонс (англ.).
- **[Netavark и Aardvark](https://github.com/containers/netavark)** — документация сетевого стека.

### Рекомендации

- На Linux для новых проектов выбирайте Podman: безопаснее за счет rootless, дешевле по ресурсам, глубже интегрирован с `systemd`.
- На macOS/Windows начинайте с Podman Desktop (open source), если не требуется проприетарный функционал Docker Desktop и ваша компания не использует его лицензированную версию.
- Для Production используйте Quadlet вместо Docker Compose: контейнеры получают управление, логи и мониторинг от `systemd`.
- При переносе стеков с Docker учитывайте разницу в сетевом стеке (pasta vs bridge) и в правилах именования образов (FQIN).

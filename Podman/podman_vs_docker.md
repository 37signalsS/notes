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

## Нюансы и ограничения

| Ограничение | Docker | Podman |
| :--- | :--- | :--- |
| **Docker Socket** | Стандарт индустрии. Многие инструменты (Portainer, CI-агенты) требуют `/var/run/docker.sock`. | Поддерживает эмуляцию сокета через `podman.socket`, но в rootless-режиме путь отличается (`$XDG_RUNTIME_DIR/podman/podman.sock`). |
| **Docker Swarm** | Нативная поддержка оркестрации. | **Не поддерживается**. Podman ориентирован на локальный запуск или Kubernetes. |
| **Windows / macOS** | Docker Desktop — очень зрелый продукт с GUI. | Podman Desktop активно развивается; на macOS по умолчанию провайдер `libkrun` (Apple Silicon, Intel не поддерживается с Podman 6), на Windows — WSL2/Hyper-V (Windows 10 не поддерживается с Podman 6). |
| **Короткие имена образов** | По умолчанию ищет на Docker Hub. | Требует явного указания реестра (например, `docker.io/`) или настройки `registries.conf` для безопасности. |
| **Cgroups v2** | Ориентирован на cgroups v2 (после перехода на containerd 2.x). | Строгое требование: в Podman 6 поддержка cgroups v1 удалена. |
| **Firewall** | Поддерживает `iptables` и `nftables`. | Только `nftables` (с Podman 6 бэкенд `iptables` удален). |
| **Rootless-сеть** | Изоляция через rootlesskit; контейнеры видят виртуальную сеть. | В режиме `pasta` контейнеры изолированы друг от друга по умолчанию — прямой связи между ними нет; для взаимодействия нужен проброс портов хоста, общий pod или rootless bridge (Netavark). |

---

## Дополнительная информация

### Связанные разделы

- **[Бездемонная архитектура](./podman_daemonless_architecture.md)** — подробный разбор работы без демона.
- **[Безрутовый (Rootless) режим](./podman_rootless.md)** — механизмы маппинга UID/GID.
- **[Buildah: Концепции и практика сборки](./buildah_overview.md)** — сравнение механизмов сборки BuildKit и Buildah.

### Ссылки

- **[Введение в Podman 6.0](https://blog.podman.io/2026/07/introducing-podman-v6-0-0/)** — официальный анонс (англ.).
- **[Netavark и Aardvark](https://github.com/containers/netavark)** — документация сетевого стека.

### Рекомендации

- На Linux для новых проектов выбирайте Podman: безопаснее за счет rootless, дешевле по ресурсам, глубже интегрирован с `systemd`.
- На macOS/Windows начинайте с Podman Desktop (open source), если не требуется проприетарный функционал Docker Desktop и ваша компания не использует его лицензированную версию.
- Для Production используйте Quadlet вместо Docker Compose: контейнеры получают управление, логи и мониторинг от `systemd`.
- При переносе стеков с Docker учитывайте разницу в сетевом стеке (pasta vs bridge) и в правилах именования образов (FQIN).

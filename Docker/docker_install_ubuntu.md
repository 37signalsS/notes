# Установка Docker Engine на Ubuntu

**Актуально для:** Docker Engine 29.x (apt-репозиторий Docker, deb822-формат источников), Ubuntu 26.04 (Resolute) / 24.04 (Noble) / 22.04 (Jammy) LTS

## Определения

- **Docker Engine:** Контейнерный движок: демон `dockerd`, REST API и CLI. Устанавливается из пакетов `docker-ce` (демон), `docker-ce-cli` (клиент), `containerd.io` (bundled containerd + runc), `docker-buildx-plugin` (Buildx), `docker-compose-plugin` (Compose V2).
- **docker-ce-rootless-extras:** Пакет с инструментами rootless-режима (`dockerd-rootless-setuptool.sh`, RootlessKit); профиль AppArmor для rootlesskit поставляется вместе с пакетом.
- **Rootless Docker:** Режим работы демона и контейнеров от имени обычного пользователя через user namespaces — демон не требует root ни на этапе установки, ни в работе.
- **NVIDIA Container Toolkit:** Набор инструментов для доступа контейнеров к GPU хоста (runtime `nvidia-container-runtime` + утилита `nvidia-ctk`).
- **Convenience script:** Скрипт `get.docker.com` для неминтерактивной установки последней stable-версии; не рекомендуется для production.

## Базовые концепции

### Как устроена установка

Официальный apt-репозиторий `download.docker.com` — рекомендуемый способ установки: он гарантирует обновления безопасности и содержит плагины (Buildx, Compose), которых нет в пакетах Ubuntu (`docker.io`). Репозиторий имеет три канала:

- **stable** — текущие релизы (канал по умолчанию);
- **test** — pre-releases (beta, release-candidates) вместе со stable;
- **nightly** — ежедневные сборки (для разработчиков Docker).

Пакеты `containerd` и `runc` Docker Engine поставляет в составе `containerd.io` — отдельно установленные системные `containerd`/`runc` конфликтуют с bundled-версией и должны быть удалены до установки.

> **Примечание:** в старых версиях документации (и ряде файлов этой базы) используется однострочная форма `echo "deb [...] ... > /etc/apt/sources.list.d/docker.list`. Она по-прежнему работает, но текущий рекомендуемый формат — deb822 (`docker.sources`), приведённый ниже.

## Предварительные требования

### Поддерживаемые платформы

- **ОС:** 64-bit Ubuntu 26.04 (Resolute) LTS, 24.04 (Noble) LTS, 22.04 (Jammy) LTS. Ubuntu 20.04 и старше не поддерживаются текущими версиями Engine.
- **Архитектуры:** x86_64 (amd64), armhf, arm64, s390x, ppc64le (ppc64el).
- Производные Ubuntu (например, Linux Mint) официально не поддерживаются, хотя могут работать.

### Ограничения файрвола

> **Важно перед установкой:** опубликованные порты контейнеров (`-p`) обходят правила ufw/firewalld — Docker манипулирует цепочками `iptables` напрямую. Docker совместим только с `iptables-nft` и `iptables-legacy`; правила, созданные через `nft`, на хосте с Docker не поддерживаются. Пользовательские правила добавляйте в цепочку `DOCKER-USER` (см. [Устранение неполадок](#конфликты-с-ufw)).

### Удаление конфликтующих пакетов

Неофициальные пакеты дистрибутива (`docker.io`, `docker-compose`, `docker-compose-v2`, `docker-doc`, `docker-buildx`, `podman-docker`) и отдельные `containerd`/`runc` конфликтуют с официальными:

```bash
sudo apt remove $(dpkg --get-selections docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc | cut -f1)
# → apt может сообщить, что ни один из пакетов не установлен — это нормально
```

Данные в `/var/lib/docker/` при удалении пакетов не затрагиваются (см. [Откат и удаление](#откат-и-удаление)).

## Установка

### Вариант А: официальный apt-репозиторий (рекомендуемый)

1. **GPG-ключ и источник (deb822-формат):**

    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
    Types: deb
    URIs: https://download.docker.com/linux/ubuntu
    Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
    Components: stable
    Architectures: $(dpkg --print-architecture)
    Signed-By: /etc/apt/keyrings/docker.asc
    EOF

    sudo apt-get update
    ```

    Параметры: `Suites` — кодовое имя релиза (`noble`, `jammy`); `${UBUNTU_CODENAME:-$VERSION_CODENAME}` корректно работает и на производных дистрибутивах; `Signed-By` указывает на ключ в `/etc/apt/keyrings` (формат `.asc` не требует `gpg --dearmor`, пакет `gnupg` для репозитория Docker не нужен).

    Проверка, что репозиторий подключён:

    ```bash
    apt-cache policy docker-ce | head -4
    # → docker-ce:
    # →   Installed: (none)
    # →   Candidate: 5:29.8.2-1~ubuntu.24.04~noble
    # →   Version table:
    # →      5:29.8.2-1~ubuntu.24.04~noble 500
    # →         500 https://download.docker.com/linux/ubuntu noble/stable amd64 Packages
    ```

2. **Установка пакетов (последняя версия):**

    ```bash
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ```

    Сервис `docker` запускается автоматически (Debian-based). Проверка: `sudo systemctl status docker`.

3. **Установка конкретной версии:**

    ```bash
    apt list --all-versions docker-ce
    # → docker-ce/noble 5:29.8.2-1~ubuntu.24.04~noble amd64
    # → docker-ce/noble 5:29.8.1-1~ubuntu.24.04~noble amd64
    # → ...

    VERSION_STRING=5:29.8.2-1~ubuntu.24.04~noble
    sudo apt-get install -y docker-ce=$VERSION_STRING docker-ce-cli=$VERSION_STRING containerd.io docker-buildx-plugin docker-compose-plugin
    ```

    `docker-ce` и `docker-ce-cli` фиксируются одной строкой версии — их API/CLI версии должны совпадать.

### Вариант Б: ручная установка .deb (изолированные сети)

Когда хост не имеет доступа к `download.docker.com`:

1. Откройте `https://download.docker.com/linux/ubuntu/dists/`, выберите релиз, затем `pool/stable/<arch>/` (`amd64`, `armhf`, `arm64`, `s390x`).
2. Скачайте `containerd.io_<version>_<arch>.deb`, `docker-ce_<version>_<arch>.deb`, `docker-ce-cli_<version>_<arch>.deb`, `docker-buildx-plugin_<version>_<arch>.deb`, `docker-compose-plugin_<version>_<arch>.deb`.
3. Установите:

    ```bash
    sudo dpkg -i ./containerd.io_<version>_<arch>.deb \
      ./docker-ce_<version>_<arch>.deb \
      ./docker-ce-cli_<version>_<arch>.deb \
      ./docker-buildx-plugin_<version>_<arch>.deb \
      ./docker-compose-plugin_<version>_<arch>.deb
    ```

    Обновления — только вручную: каждый раз скачивайте новые `.deb` и повторяйте процедуру.

### Вариант В: convenience script (только dev/test)

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

Ограничения скрипта (из его исходного кода и документации):

- **Не рекомендуется для production** — всегда ставит последнюю stable-версию, что при провижининге может дать нежданный апгрейд мажорной версии;
- не предназначен для обновления существующей установки (зависимости могут остаться старыми);
- сбрасывает кастомную конфигурацию репозиториев под параметры по умолчанию;
- устанавливает зависимости и рекомендации без запроса подтверждения;
- требует root/sudo; перед запуском на EOL-дистрибутиве выдаёт deprecation-предупреждение.

Перед запуском изучите скрипт и просмотрите его действия без изменений:

```bash
sudo sh get-docker.sh --dry-run
```

Для pre-releases (канал test) существует аналог: `curl -fsSL https://test.docker.com -o test-docker.sh && sudo sh test-docker.sh`. Исходный код скрипта — в репозитории [docker/docker-install](https://github.com/docker/docker-install).

## Post-installation steps

### Запуск без sudo

Демон слушает Unix-сокет, владелец которого — root. Пакет создаёт группу `docker`, но не добавляет в неё пользователей. Добавьте пользователя:

```bash
sudo groupadd docker          # группа обычно уже создана пакетом; команда идемпотентна по факту
sudo usermod -aG docker $USER
newgrp docker                 # применить в текущей сессии; либо перелогиниться
```

Проверка членства и работоспособности:

```bash
id -nG
# → user docker ...
docker run hello-world
# → Hello from Docker!
# → This message shows that your installation appears to be working correctly.
```

> **Подводный камень:** если до добавления в группу вы запускали `sudo docker ...`, каталог `~/.docker/` мог создаться с правами root — CLI сообщит `WARNING: Error loading config file: ... permission denied`. Лечение: `sudo chown "$USER":"$USER" "$HOME/.docker" -R && sudo chmod g+rwx "$HOME/.docker" -R`.

> **Безопасность:** членство в группе `docker` эквивалентно root на хосте (можно смонтировать `/` в контейнер). Выдавайте группу только доверенным пользователям; альтернатива — [rootless-режим](#настройка-rootless-режима).

### Управление сервисом

```bash
sudo systemctl status docker
sudo systemctl enable --now docker     # идемпотентно: пакет уже включает автозапуск
sudo systemctl restart docker          # после правок /etc/docker/daemon.json
```

## Практические сценарии

### Настройка Proxy в корпоративной среде

В изолированных сетях прокси нужен демону (для скачивания образов) и клиенту (для обращений к registry API).

**А. Демон (systemd drop-in):**

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf <<EOF
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:8080"
Environment="HTTPS_PROXY=http://proxy.example.com:8080"
Environment="NO_PROXY=localhost,127.0.0.1,docker-registry.local"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

`NO_PROXY` обязательно включайте внутренние registry и диапазоны, иначе трафик к ним пойдёт через прокси. Проверка применения: `sudo systemctl show docker --property Environment`.

**Б. Клиент (`~/.docker/config.json`):**

```json
{
  "proxies": {
    "default": {
      "httpProxy": "http://proxy.example.com:8080",
      "httpsProxy": "http://proxy.example.com:8080",
      "noProxy": "localhost,127.0.0.1"
    }
  }
}
```

Если `docker run hello-world` не проходит из-за блокировки Docker Hub — настройте зеркало registry (`registry-mirrors`), см. [docker_daemon_config.md](./docker_daemon_config.md).

### Установка NVIDIA Container Toolkit (GPU)

Для GPU-ускоренных рабочих нагрузок (HPC, рендеринг, GPU-вычисления). Предварительно: на хосте должен быть установлен NVIDIA-драйвер.

```bash
sudo apt-get install -y ca-certificates curl gnupg2

# Репозиторий NVIDIA
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Регистрация runtime в Docker (модифицирует /etc/docker/daemon.json) и перезапуск
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Полезные флаги `nvidia-ctk runtime configure`: `--set-as-default` (сделать nvidia runtime дефолтным), `--dry-run` (показать изменения без применения). Для rootless-демона: `nvidia-ctk runtime configure --runtime=docker --config=$HOME/.config/docker/daemon.json`.

Проверка доступа к GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
# → таблица GPU хоста
```

### Настройка Rootless-режима

Rootless-режим предотвращает получение прав root на хосте даже при побеге из контейнера: демон работает в user namespace от обычного пользователя, SETUID-бинарники не используются (кроме `newuidmap`/`newgidmap`).

**1. Предварительные требования:**

```bash
sudo apt-get install -y uidmap dbus-user-session slirp4netns   # slirp4netns — сетевой драйвер по умолчанию; для pasta (экспериментально) — passt

# Диапазоны subuid/subgid: минимум 65 536 записей для пользователя
grep "^$USER:" /etc/subuid /etc/subgid
# → /etc/subuid:user:100000:65536
# → /etc/subgid:user:100000:65536
# Если пусто: echo "$USER:100000:65536" | sudo tee -a /etc/subuid /etc/subgid
```

**2. Установка инструментов rootless** (если `dockerd-rootless-setuptool.sh` отсутствует после установки Engine):

```bash
sudo apt-get install -y docker-ce-rootless-extras
```

**3. Проверка и установка:**

```bash
dockerd-rootless-setuptool.sh check     # диагностика всех требований
dockerd-rootless-setuptool.sh install   # создаёт systemd user-юнит и запускает демон
```

На Ubuntu 24.04+ AppArmor ограничивает непривилегированные user namespaces (`kernel.apparmor_restrict_unprivileged_userns=1`). При установке `docker-ce-rootless-extras` из deb-пакета профиль AppArmor для rootlesskit поставляется в комплекте; если `check` всё равно сообщает об ограничении — временно отключите его:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
# Постоянно — drop-in:
sudo tee /etc/sysctl.d/60-unprivileged-userns.conf <<EOF
kernel.apparmor_restrict_unprivileged_userns = 0
EOF
sudo sysctl --system
```

**4. Autostart и переменные окружения (`~/.bashrc`):**

```bash
sudo loginctl enable-linger $USER       # демон стартует при загрузке без активной сессии

export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
export PATH="$HOME/bin:$PATH"
```

**5. Управление и особенности:**

```bash
systemctl --user status docker          # управление — через systemd --user, не sudo
docker info | grep -i rootless          # → rootless
```

- Данные хранятся в `~/.local/share/docker`, а не в `/var/lib/docker`;
- rootful и rootless демоны сосуществуют: разные сокеты (`/var/run/docker.sock` vs `$XDG_RUNTIME_DIR/docker.sock`), выбор — через `DOCKER_HOST`;
- группа `docker` для rootless не требуется;
- сетевые драйверы RootlessKit: `slirp4netns` (дефолт при установленном пакете), `pasta` (экспериментальный, Docker 25.0+), `gvisor-tap-vsock` (дефолт, если ни один не установлен), `vpnkit` (legacy). Производительность сети ниже, чем в rootful; подробности — в [host_daemon_hardening.md](./Docker_security/host_daemon_hardening.md).

### Фиксация версий (Hold)

Для production, где апгрейд должен быть согласован:

```bash
# Установка конкретной версии (см. Вариант А, шаг 3)
sudo apt-get install -y docker-ce=5:29.8.2-1~ubuntu.24.04~noble docker-ce-cli=5:29.8.2-1~ubuntu.24.04~noble

# Фиксация — apt не будет обновлять пакеты автоматически
sudo apt-mark hold docker-ce docker-ce-cli containerd.io
sudo apt-mark unhold docker-ce docker-ce-cli containerd.io   # снять фиксацию
```

> **Важно:** `apt-mark hold` блокирует и обновления безопасности. Фиксируйте версии только при наличии процесса регулярного ручного обновления.

### Настройка логирования (daemon.json)

Ограничение роста логов контейнеров (дефолтный драйвер `json-file` не ограничен):

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
```

```bash
sudo systemctl restart docker
docker info | grep -A2 "Logging Driver"
# → Logging Driver: json-file
```

Все драйверы и их параметры — в [docker_logging_drivers_overview.md](./Docker_logs/docker_logging_drivers_overview.md); полный справочник `daemon.json` — в [docker_daemon_config.md](./docker_daemon_config.md).

## Валидация установки

```bash
sudo systemctl is-active docker
# → active

docker version
# → Client: Version: 29.x ...
# → Server: Engine: Version: 29.x ... API version: 1.52 (minimum version ...)

docker info | grep -E "Server Version|Storage Driver|Cgroup"
# → Server Version: 29.8.2
# → Storage Driver: overlay2 (или containerd image store на свежих установках 29.x)
# → Cgroup Driver: systemd / Cgroup Version: v2

docker run --rm hello-world
# → Hello from Docker! ... installation appears to be working correctly.
```

## Устранение неполадок

### Контейнеры не резолвят DNS

**Механизм:** встроенный DNS Docker (`127.0.0.11`) форвардит запросы к DNS-серверам из `/etc/resolv.conf` хоста. При `systemd-resolved` stub-режиме там указан `127.0.0.53` — loopback-адрес, недоступный из сетевого namespace контейнера; симптомы: `server misbehaving`, `Temporary failure in name resolution`.

Решения (по предпочтительности):

1. Явный DNS для контейнеров в `daemon.json` (ключ `dns`) — см. [docker_daemon_config.md](./docker_daemon_config.md); либо `--dns` для отдельного контейнера;
2. Указать реальные резолверы вместо stub: `sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf`;
3. Настроить `systemd-resolved` на слушание маршрутизируемого адреса (опция `DNS=` в networkd/NetworkManager).

### Конфликты с UFW

Docker обходит правила UFW, манипулируя цепочками `iptables` напрямую: опубликованный порт (`-p 80:80`) доступен извне, даже если UFW включён.

- Привязывайте порт к localhost, если внешний доступ не нужен: `-p 127.0.0.1:80:80`;
- Пользовательские правила — в цепочку `DOCKER-USER` (она обрабатывается до правил Docker):

    ```bash
    sudo iptables -I DOCKER-USER -i eth0 ! -s 192.168.1.0/24 -j DROP
    ```

- Docker совместим только с `iptables-nft`/`iptables-legacy`; правила `nft` на хосте с Docker не поддерживаются. Экспериментальный бэкенд `nftables` для containerd image store — см. [docker_daemon_config.md](./docker_daemon_config.md).

### Ошибки apt при установке

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `NO_PUBKEY ...` | Не добавлен или повреждён GPG-ключ | Повторить шаг добавления `docker.asc` (Вариант А, шаг 1) |
| `The repository ... does not have a Release file` | Неверное кодовое имя релиза в `Suites` | Проверить: `lsb_release -cs` (должно быть `noble`/`jammy`); Ubuntu 20.04 не поддерживается |
| `Unable to locate package docker-ce` | Репозиторий не подключён или не выполнен `apt-get update` | Проверить `/etc/apt/sources.list.d/docker.sources` и `apt-cache policy docker-ce` |
| `Got permission denied while trying to connect to the Docker daemon socket` | Пользователь не в группе `docker` или сессия не обновлена | `sudo usermod -aG docker $USER` + `newgrp docker` / перелогин |
| `WARNING: Error loading config file: ~/.docker/config.json - permission denied` | `~/.docker` создан с правами root после `sudo docker` | `sudo chown "$USER":"$USER" ~/.docker -R && sudo chmod g+rwx ~/.docker -R` |

### Rootless: типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `No subuid ranges found for user` | Пустые `/etc/subuid`/`/etc/subgid` | Добавить диапазон ≥65 536: `echo "$USER:100000:65536" \| sudo tee -a /etc/subuid /etc/subgid` |
| `RootlessKit failed` на Ubuntu 24.04+ | AppArmor-ограничение unprivileged userns | Профиль rootlesskit (в комплекте deb-пакета) или `kernel.apparmor_restrict_unprivileged_userns=0` (см. выше) |
| `dbus` ошибки при `systemctl --user` | Не установлен `dbus-user-session` или не выполнен relogin | `sudo apt-get install -y dbus-user-session` + перелогин |

## Лучшие практики и очистка

- **Production — только официальный репозиторий** (Вариант А); convenience script — только для dev/test и провижининга; всегда просматривайте скачанный скрипт перед запуском (`--dry-run`).
- **Фиксируйте версии** в production (Вариант А, шаг 3), но регулярно обновляйтесь — `apt-mark hold` блокирует и security-обновления.
- **Группа `docker` = root:** выдавайте минимальному кругу; для недоверенных пользователей — rootless-режим.
- **Удаляйте `get-docker.sh`** после использования: `rm get-docker.sh`.
- **Включите `live-restore`** для апгрейда демона без даунтайма контейнеров — см. [docker_daemon_config.md](./docker_daemon_config.md).

### Откат и удаление

Откат на предыдущую версию: `apt list --all-versions docker-ce` → установка нужного `VERSION_STRING` (Вариант А, шаг 3).

Полное удаление (деструктивная операция — данные не восстанавливаются):

```bash
sudo apt purge docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras
sudo rm -rf /var/lib/docker /var/lib/containerd   # образы, контейнеры, volumes, сети
sudo rm /etc/apt/sources.list.d/docker.sources /etc/apt/keyrings/docker.asc
sudo apt-get update
```

Конфигурационные файлы (`/etc/docker/daemon.json`, drop-in'ы systemd) удаляются вручную.

## Дополнительная информация

### Связанные темы

- **[Справочник daemon.json](./docker_daemon_config.md)** — все опции демона, storage, логирование, прокси, mirrors.
- **[Команды Docker CLI](./docker_commands.md)** — управление контейнерами и образами.
- **[Архитектура Docker: демон и среда выполнения](./docker_overview.md)** — компоненты Engine.
- **[Безопасность: Rootless и Hardening](./Docker_security/host_daemon_hardening.md)** — глубокое погружение в защиту хоста.
- **[Драйверы логирования](./Docker_logs/docker_logging_drivers_overview.md)** — json-file, local, fluentd, Loki и др.
- Официальная документация: [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/), [Linux post-install](https://docs.docker.com/engine/install/linux-postinstall/), [Rootless mode](https://docs.docker.com/engine/security/rootless/), [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

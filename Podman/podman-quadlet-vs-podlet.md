# Podman: Quadlet и Podlet

> Актуально для: Podman 6.x

## Определения

**Quadlet** — встроенный в Podman механизм декларативного описания контейнеров, подов, сетей, томов и образов в виде systemd unit-файлов специального формата. При старте системы или выполнении `systemctl daemon-reload` systemd автоматически транслирует такие файлы в полноценные `.service`-юниты и запускает их через Podman. Quadlet появился как развитие идеи `podman generate systemd`, но в декларативном варианте: вместо генерации юнита из уже запущенного контейнера вы описываете желаемое состояние, а systemd приводит систему к нему.

**Podlet** — отдельная утилита на Rust, которая не входит в состав Podman. Её задача — генерировать Quadlet-файлы из существующих команд `podman run`/`docker run`, файлов `docker-compose.yml` или уже работающих объектов (контейнеров, подов, сетей, томов). Podlet не создаёт контейнеры и не является рантаймом — он только генерирует текст готового Quadlet-файла для последующего размещения в каталоге systemd-генератора.

**Daemonless-архитектура** — модель управления контейнерами без центрального демона. В Podman каждый контейнер — это стандартный дочерний процесс ОС, управляемый через `conmon` и systemd (при использовании Quadlet). Подробнее см. [Бездемонная архитектура](./podman_daemonless_architecture.md).

---

## Основные концепции

### Типы Quadlet-файлов

| Расширение | Что описывает |
| :--- | :--- |
| `.container` | отдельный контейнер |
| `.pod` | под — группу контейнеров с общей сетью |
| `.volume` | именованный том |
| `.network` | сеть |
| `.image` | образ, который нужно заранее подтянуть |
| `.build` | сборка образа из Containerfile |
| `.kube` | развёртывание из Kubernetes YAML (`podman kube play`) |
| `.artifact` | OCI-артефакт |

### Каталоги размещения Quadlet-файлов

- `/etc/containers/systemd/` — системные (rootful) юниты;
- `~/.config/containers/systemd/` — пользовательские, rootless-юниты;
- `/run/containers/systemd/` — временные каталоги (приоритет выше, но очищаются при перезагрузке);
- `/usr/share/containers/systemd/` — пакетные юниты дистрибутива.

### Пример `.container`-файла

```ini
[Unit]
Description=My Web Application
After=network-online.target

[Container]
Image=docker.io/library/nginx:latest
ContainerName=nginx
PublishPort=8080:80
Volume=nginx-data:/usr/share/nginx/html:Z

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

### Пример `.pod`-файла и связанных контейнеров

Если нужно объединить несколько контейнеров в один под с общей сетью:

```ini
# web-pod.pod
[Pod]
PublishPort=8080:80
```

```ini
# web-app.container
[Container]
Image=myapp:latest
Pod=web-pod.pod

[Service]
Restart=always
```

```ini
# web-cache.container
[Container]
Image=docker.io/library/redis:latest
Pod=web-pod.pod

[Service]
Restart=always
```

Все контейнеры, привязанные к одному поду, разделяют общий сетевой namespace и видят друг друга через `localhost`.

### Пример `.volume`-файла

```ini
[Volume]
Label=app=data
```

---

## Практические сценарии

### 1. Генерация Quadlet-файлов через Podlet

Podlet поддерживает три режима генерации:

**Из команды запуска:**

```bash
podlet podman run -d -p 8080:80 -v nginx-data:/usr/share/nginx/html:Z --name nginx nginx:latest
```

На выходе — готовый `.container`-файл со всеми нужными секциями.

**Из `docker-compose.yml`:**

```bash
podlet compose docker-compose.yml
```

Podlet разберёт файл и создаст по отдельному `.container`-файлу на каждый сервис, либо сгруппирует связанные сервисы в один `.pod` вместе с сопутствующими `.container`-файлами.

**Из уже работающего объекта:**

```bash
podlet generate container nginx
```

Удобно, если вы сначала быстро подняли контейнер командой в терминале, а потом решили закрепить результат декларативно.

### 2. Управление Quadlet-юнитами

```bash
# Применить изменения в Quadlet-файлах
systemctl daemon-reload

# Включить и запустить юнит
systemctl enable --now nginx.container

# Проверить статус
systemctl status nginx.container

# Просмотр логов
journalctl -u nginx.container -f
```

### 3. Миграция с Docker Compose на Quadlet

Типичный рабочий процесс:

```bash
# 1. Установить podlet (отдельный инструмент, не входит в Podman)
brew install podlet          # macOS
# или
cargo install podlet         # из исходников
# или скачать бинарник из https://github.com/containers/podlet

# 2. Сгенерировать Quadlet-файлы из compose.yaml
podlet -i -a compose compose.yaml

# 3. Разместить файлы в каталог юнитов
mkdir -p ~/.config/containers/systemd/
mv *.container *.network *.volume ~/.config/containers/systemd/

# 4. Применить конфигурацию
systemctl --user daemon-reload
systemctl --user start my-app.service
systemctl --user status my-app.service
```

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

> **Важно:** Podlet не является полным конвертером. Он возвращает ошибку при неподдерживаемых опциях Compose: `build:`, `deploy.resources`, сложные `ipam:` блоки. Сгенерированные файлы **обязательно проверять перед запуском**.

---

## Операции и команды

### Основные команды Podlet

| Задача | Команда |
| :--- | :--- |
| Генерация из команды `podman run` | `podlet podman run ...` |
| Генерация из `docker-compose.yml` | `podlet compose docker-compose.yml` |
| Генерация из работающего контейнера | `podlet generate container <имя>` |
| Генерация из работающего пода | `podlet generate pod <имя>` |
| Генерация из сети | `podlet generate network <имя>` |
| Генерация из тома | `podlet generate volume <имя>` |
| Запись в текущий каталог | `podlet -f . compose docker-compose.yml` |
| Запись прямо в каталог юнитов | `podlet -u compose docker-compose.yml` |
| Добавить секцию `[Install]` | `podlet -i ...` |
| Абсолютные пути для bind-mount | `podlet -a ...` |

### Основные команды systemd для Quadlet-юнитов

| Задача | Команда |
| :--- | :--- |
| Применить изменения | `systemctl daemon-reload` |
| Включить и запустить | `systemctl enable --now <имя>.container` |
| Проверить статус | `systemctl status <имя>.container` |
| Просмотр логов | `journalctl -u <имя>.container -f` |
| Остановить | `systemctl stop <имя>.container` |
| Отключить автозапуск | `systemctl disable <имя>.container` |

---

## Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `podlet: unsupported option` | Compose-файл использует опции, не поддерживаемые podlet | Удалите `build:`, `deploy.resources`, сложные `ipam:` из compose.yaml перед конвертацией. |
| Quadlet-юнит не стартует | Ошибка в синтаксисе unit-файла | `systemctl status <имя>.container`, `journalctl -u <имя>.container` |
| Контейнер не стартует после перезагрузки | Отсутствует секция `[Install]` с `WantedBy=` | Добавьте `[Install] WantedBy=multi-user.target` |
| Контейнер падает при старте | Неверные пути или права на тома | Проверьте SELinux-метки (`:Z`/`:z`), права на хосте |
| `short name resolution` | Podman не разрешает короткие имена образов | Используйте FQIN (`docker.io/library/nginx:latest`) или настройте `registries.conf` |
| Podlet генерирует некорректный файл | Неподдерживаемая опция Compose | Проверьте вывод `podlet ... 2>&1`, доработайте compose.yaml |

---

## Рекомендации

### Best Practices

- **Включайте `[Install]` секцию** в каждый Quadlet-файл для автозапуска при загрузке системы.
- **Проверяйте сгенерированные Podlet-файлы** перед деплоем — podlet не обрабатывает `build:`, `deploy.resources` и сложные `ipam:` блоки.
- **Используйте `Notify=healthy`** для сервисов с healthcheck, чтобы systemd правильно отслеживал готовность контейнера.
- **Для production используйте Quadlet** вместо Docker Compose: контейнеры получают управление, логи и мониторинг от systemd.
- **Размещайте `.container`-файлы** в `/etc/containers/systemd/` (rootful) или `~/.config/containers/systemd/` (rootless).

### Когда Quadlet — не то, что нужно

Quadlet ориентирован на single-node инфраструктуру. Если вам требуется:
- горизонтальное автомасштабирование под нагрузкой;
- HA-кластер из нескольких физических узлов;
- multi-region deployment с распределением нагрузки между дата-центрами;

— здесь нужен полноценный Kubernetes. Quadlet отлично закрывает потребности self-hosted и single-node production, но сознательно не пытается конкурировать с оркестрацией на уровне кластера.

---

## Дополнительная информация

### Связь с другими инструментами

```
Docker Compose / podman run
        │
        ▼
     Podlet   ← генерирует Quadlet-файлы
        │
        ▼
    Quadlet   ← декларативный формат
        │
        ▼
     systemd  ← превращает Quadlet в .service и запускает
        │
        ▼
     Podman   ← реально запускает контейнеры/поды
```

### Сравнение с Docker Compose

| Критерий | Docker Compose | Quadlet (+ Podlet) |
| :--- | :--- | :--- |
| Требует демон | Да | Нет |
| Rootless | Ограниченно | По умолчанию |
| Автозапуск при старте системы | Через обходные пути (`restart: always` + сторонний init) | Нативно, через systemd `[Install]` |
| Интеграция с systemd | Отсутствует | Полная |
| Централизованные логи | Через `docker compose logs` | Через `journalctl`, вместе со всеми остальными сервисами системы |
| Формат конфигурации | YAML (`docker-compose.yml`) | INI-подобные systemd-юниты |
| Один хост | Да | Да |

### Сценарии использования

| Сценарий | Рекомендация |
| :--- | :--- |
| **Homelab** | Nextcloud, Jellyfin, Plex, Traefik, Caddy, nginx, Prometheus, Grafana — типичный набор self-hosted сервисов, которые прекрасно живут как Quadlet-юниты. |
| **VPS / выделенный сервер** | Веб-приложения, приватные API, раннеры CI/CD — один надёжный хост без затрат на поддержку кластера. |
| **Edge / IoT** | Минимальное потребление ресурсов, rootless-режим по умолчанию и простое сопровождение на слабом железе. |

### См. также

- **[Бездемонная архитектура](./podman_daemonless_architecture.md)** — роль conmon, Quadlet, systemd.
- **[Миграция с Docker](./migration-from-docker.md)** — пошаговый переход с Docker Compose на Quadlet.
- **[Podman Compose](./podman-compose.md)** — запуск Compose-файлов через Podman.
- **[Автообновление и откат в Podman](./podman_auto_update.md)** — `AutoUpdate=registry` в Quadlet.

### Ссылки

- **[Официальный сайт Podman](https://podman.io/)**
- **[Документация по Quadlet (man podman-systemd.unit)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)**
- **[Репозиторий Podlet на GitHub](https://github.com/containers/podlet)**

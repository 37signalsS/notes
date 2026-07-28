# Миграция с Docker на Podman

## Определения

**Миграция на Podman** — комплексный процесс перевода контейнерной инфраструктуры с Docker на Podman. Главный вектор миграции — переход от монолитного привилегированного демона (`dockerd`) к бездемонной (**daemonless**) архитектуре и работе без прав суперпользователя (**rootless**).

**Quadlet** — нативный инструмент Podman для декларативного описания контейнеров, сетей и томов в виде юнитов **systemd**. Является рекомендуемым стандартом для промышленной эксплуатации (Production) вместо классического Docker Compose.

**Pasta (Pack A Subtle Tap Abstraction)** — сетевой стек нового поколения (введен в Podman 5.0), заменяющий `slirp4netns` для rootless-контейнеров. Обеспечивает более высокую производительность и нативную поддержку IPv6 без использования NAT.

---

## Мотивация миграции

1.  **Повышение безопасности**: Rootless-режим гарантирует, что даже при полном взломе приложения злоумышленник получит права обычного пользователя, а не root-доступ к хосту.
2.  **Архитектурная устойчивость**: Отсутствие центрального демона устраняет единую точку отказа. Каждый контейнер — это стандартный дочерний процесс операционной системы.
3.  **Интеграция с systemd**: Podman «из коробки» использует системный планировщик для управления жизненным циклом, зависимостями и сбором логов через `journald`.
4.  **Совместимость с Kubernetes**: Podman использует концепцию **Pods** (групп контейнеров), что позволяет экспортировать локальные конфигурации напрямую в YAML-манифесты Kubernetes.

---

## Практические сценарии

### 1. Подготовка системы к Rootless-режиму

Для полноценной работы без прав root необходимо настроить маппинг идентификаторов и системные лимиты.

#### Настройка UID/GID (subuid/subgid)
Убедитесь, что для пользователя выделен диапазон дополнительных ID (обычно 65536 на пользователя):
```bash
cat /etc/subuid
# → user:100000:65536
```

#### Разрешение низких портов и Linger
Чтобы разрешить запуск сервисов на портах < 1024 и гарантировать работу контейнеров после выхода из SSH:
```bash
# Разрешаем порты от 80
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/90-podman.conf
sudo sysctl -p /etc/sysctl.d/90-podman.conf

# Включаем Linger для пользователя
sudo loginctl enable-linger $USER
```

### 2. Перенос Docker Compose на Podman 5.x

Podman 5.x значительно улучшил поддержку Compose Specification, позволяя запускать большинство файлов без изменений.

#### Вариант А: Прямой запуск (Docker Compose V2)
Установите пакет `podman-docker` и используйте привычный CLI:
```bash
# Podman эмулирует сокет и API Docker
docker compose up -d
```

#### Вариант Б: Конвертация в Quadlet (Рекомендуется)
Для повышения надежности используйте утилиту `podlet` для генерации systemd-юнитов.

```bash
# Генерация юнитов из compose.yaml
podlet -i -a compose compose.yaml

# Размещение файлов (для rootless-пользователя)
mkdir -p ~/.config/containers/systemd/
mv *.container *.network ~/.config/containers/systemd/

# Применение конфигурации
systemctl --user daemon-reload
systemctl --user start my-app.service
```

### 3. Настройка сетевого стека Pasta

В Podman 5.0 стек `pasta` используется по умолчанию для rootless-режима. Он позволяет контейнеру видеть IP-адрес хоста напрямую.

```bash
# Проверка используемого исполнителя
podman info --format '{{ .Host.Pasta.Executable }}'

# Принудительное использование pasta (если не по умолчанию)
podman run --network=pasta ...
```

### 4. Работа с Docker Socket

Если ваши инструменты (CI/CD агенты, мониторинг) требуют `/var/run/docker.sock`, Podman может эмулировать его:

```bash
# Для системного уровня (root)
sudo systemctl enable --now podman.socket

# Для пользователя (rootless)
systemctl --user enable --now podman.socket
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
```

---

## Особенности и ограничения миграции

- **Явные реестры (Fully Qualified Image Names)**: Podman (в отличие от Docker) по соображениям безопасности требует указывать полный путь к образу: `docker.io/library/nginx` вместо просто `nginx`.
- **Права на тома (Volume Permissions)**: В rootless-режиме UID 0 внутри контейнера — это ваш UID на хосте. При монтировании существующих папок может потребоваться `podman unshare chown -R 0:0 /data`.
- **Миграция БД Podman**: При переходе с Podman 4 на 5 происходит автоматическая миграция базы данных с BoltDB на SQLite. Рекомендуется сделать бэкап `~/.local/share/containers/storage` перед обновлением.
- **Отсутствие Docker Swarm**: Podman не поддерживает Swarm. Рекомендуемой альтернативой является переход на **Kubernetes** или использование **Pods** в связке с Quadlet.
- **Cgroups v2**: Podman 5.0 требует Cgroups v2. На старых дистрибутивах (RHEL 7, Debian 10) миграция может потребовать обновления ядра.

---

## Дополнительная информация

### Связанные разделы
- **[Quadlet: Декларативные контейнеры](./podman_daemonless_architecture.md)** — подробное руководство по написанию `.container` файлов.
- **[Rootless режим](./podman_rootless.md)** — глубокое погружение в механизмы изоляции.
- **[Podman Compose](./podman-compose.md)** — особенности работы с YAML-файлами.
- **[Управление зависимостями](./podman-dependencies.md)** — как заменить `depends_on` в systemd.

### Ссылки
- **[Official Podman Migration Guide](https://podman.io/docs/migration)** (англ.)
- **[Podman 5.0 Release Notes](https://blog.podman.io/2024/03/podman-5-0-released/)** (архитектурные изменения)

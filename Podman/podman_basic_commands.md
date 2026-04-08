# Podman: Основные команды

## Определения

**Podman (Pod Manager)** — инструмент управления OCI-совместимыми контейнерами с архитектурой без демона (daemonless). Полная замена Docker CLI с поддержкой rootless-режима по умолчанию. Работает как часть экосистемы специализированных утилит: **[Buildah](../Docker/alternative_runtimes_and_tools.md)** (сборка образов), **[Skopeo](../Docker/alternative_runtimes_and_tools.md)** (копирование между реестрами), **[CRI-O](../Docker/alternative_runtimes_and_tools.md)** (CRI для Kubernetes).

**Daemonless-архитектура** — модель без центрального привилегированного демона. Каждая команда запускает отдельный процесс, который выполняет задачу и завершается. Жизненным циклом контейнеров управляют легковесные процессы-мониторы `conmon`. Подробнее: [Daemonless архитектура Podman](./podman_daemonless_architecture.md).

## Основные концепции

### Установка

**RHEL и совместимые (AlmaLinux, Rocky Linux):**

```bash
dnf module enable container-tools
dnf module install container-tools
```

**Fedora:**

```bash
dnf install podman
```

**Ubuntu/Debian:**

```bash
echo "deb https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/xUbuntu_$(lsb_release -rs)/ /" | sudo tee /etc/apt/sources.list.d/devel:kubic:libcontainers:stable.list
wget -qO - "https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/xUbuntu_$(lsb_release -rs)/Release.key" | sudo apt-key add -
sudo apt update && sudo apt install podman
```

**macOS/Windows (через Podman Desktop):**

```bash
brew install podman
podman machine init && podman machine start
```

**Проверка установки:**

```bash
podman --version
podman info
```

### Работа с образами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Поиск | `podman search <образ>` | Поиск образов в реестрах |
| Скачивание | `podman pull <образ>` | Скачать образ из реестра |
| Список | `podman images` | Показать локальные образы |
| Тегирование | `podman tag <образ> <новое_имя>` | Добавить тег для пуша в реестр |
| Инспекция | `podman inspect <образ>` | Показать метаданные (порты, переменные, пользователь) |
| Удаление | `podman rmi <образ>` | Удалить локальный образ |

### Работа с контейнерами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Запуск | `podman run -d --name <имя> -p <хост>:<контейнер> <образ>` | Создать и запустить контейнер |
| Список (запущенные) | `podman ps` | Показать запущенные контейнеры |
| Список (все) | `podman ps -a` | Показать все контейнеры |
| Логи | `podman logs <контейнер>` | Показать логи (`-f` — follow, `--tail N`) |
| Выполнить команду | `podman exec -it <контейнер> <команда>` | Выполнить команду в работающем контейнере |
| Остановка | `podman stop <контейнер>` | Остановить контейнер |
| Запуск | `podman start <контейнер>` | Запустить остановленный контейнер |
| Удаление | `podman rm <контейнер>` | Удалить контейнер |

### Политики перезапуска (`--restart`)

| Политика | Поведение |
| :--- | :--- |
| `no` (по умолчанию) | Никогда не перезапускать |
| `on-failure[:max-retries]` | Только при ошибке (exit code ≠ 0) |
| `always` | Всегда перезапускать, даже после `stop` |
| `unless-stopped` | Всегда, кроме случаев явной остановки (рекомендуется для production) |

### Ключевые особенности Podman

- **Rootless по умолчанию** — контейнеры запускаются от непривилегированного пользователя. Подробнее: [Rootless режим](./podman_rootless.md)
- **Совместимость с Docker CLI** — `alias docker=podman` для прозрачной миграции
- **Нативная поддержка подов** — группировка контейнеров по аналогии с Kubernetes
- **Интеграция с systemd** — генерация unit-файлов для автозапуска ([Daemonless архитектура](./podman_daemonless_architecture.md))
- **Автообновление** — встроенный механизм updates/rollback через `podman auto-update`. Подробнее: [Автообновление и откат](./podman_auto_update.md)
- **Экономия ресурсов** — 0 МБ памяти в режиме простоя (нет демона)

### Очистка системы (Prune)

| Команда | Описание |
| :--- | :--- |
| `podman system prune` | Удаление остановленных контейнеров, dangling образов, сетей |
| `podman container prune` | Удаление остановленных контейнеров |
| `podman image prune` | Удаление dangling образов (`-a` — все неиспользуемые) |
| `podman volume prune` | Удаление неиспользуемых томов |

**Dangling images** — образы без тега (`<none>`), появляются при пересборке с тем же тегом.

## Практические сценарии

### Запуск веб-сервера Nginx

```bash
# Запуск в фоновом режиме с пробросом портов
podman run -d --name nginx -p 8080:80 nginx

# Проверка работы
curl http://localhost:8080

# Просмотр логов
podman logs nginx

# Вход в контейнер
podman exec -it nginx /bin/sh
```

### Использование Volume

Подробная документация: [Хранилище и работа с файловой системой](./podman_volumes_and_storage.md).

```bash
# Bind mount — монтирование директории хоста
podman run -d --name myapp -v /home/user/data:/data myimage

# Named volume — управление через Podman
podman volume create mydata
podman run -d --name myapp -v mydata:/data myimage

# SELinux relabel (RHEL/Fedora)
podman run -d --name myapp -v /home/user/data:/data:Z myimage
```

### Работа с подами

```bash
# Создание пода
podman pod create --name mypod -p 8080:80

# Запуск контейнера в поде
podman run -d --pod mypod --name web nginx

# Список подов
podman pod ps

# Остановка/удаление пода
podman pod stop mypod
podman pod rm mypod
```

### Генерация Kubernetes-манифестов

```bash
# Экспорт пода/контейнера в Kubernetes YAML
podman generate kube mypod > mypod.yaml

# Запуск Kubernetes-манифеста локально
podman play kube mypod.yaml
```

### Миграция с Docker

```bash
# Алиас для совместимости
alias docker=podman

# Импорт Docker-образов
podman load < docker-save-output.tar

# Экспорт образов для Docker
podman save -o output.tar image:tag
```

### Работа с локальным реестром

```bash
# Запуск реестра
mkdir -p ~/registry
podman run -d --name registry \
  -p 5000:5000 \
  -v ~/registry:/var/lib/registry:z \
  registry
```

**Настройка доверия (без HTTPS) в `/etc/containers/registries.conf`:**

```toml
[[registry]]
location = "localhost:5000"
insecure = true
```

**Загрузка образа в локальный реестр:**

```bash
podman pull docker.io/library/nginx
podman tag docker.io/library/nginx localhost:5000/nginx
podman push localhost:5000/nginx
```

**Копирование через Skopeo:**

```bash
skopeo copy docker://docker.io/library/httpd docker://localhost:5000/httpd
```

### Cockpit интеграция

После установки `container-tools` в Cockpit (`https://<сервер>:9090`) появляется вкладка **Podman Containers** для управления контейнерами через веб-интерфейс.

```bash
systemctl enable --now cockpit.socket
```

### Получение IP-адреса контейнера

```bash
podman inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' my-container
```

### Логирование Nginx в STDOUT/STDERR

Приложения должны писать логи в стандартные потоки для сбора через `podman logs`:

```dockerfile
RUN ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log
```

## Дополнительная информация

### Бенчмарки производительности

Полная таблица сравнения: [Podman vs Docker](./podman_vs_docker.md).

Кратко: Docker быстрее для отдельных операций (запуск контейнера на 15%, pull образов на 10%), Podman эффективнее для масштабирования (экономия памяти 65%, на 30% меньше потребление RAM при 100 контейнерах).

### Сетевые драйверы

| Драйвер | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Netavark** | Сетевой бэкенд по умолчанию (Podman 4+) | Rootful режим |
| **pasta** | Современная замена slirp4netns | Rootless (рекомендуется) |
| **slirp4netns** | Виртуальный сетевой стек с NAT | Rootless (legacy) |
| **Aardvark-dns** | DNS для контейнеров | Замена dnsmasq (Podman 4+) |

Подробнее: [Rootless режим](./podman_rootless.md).

### Интеграция с SELinux и MCS

При старте контейнера с SELinux ему присваивается уникальная метка MCS (Multi-Category Security): `system_u:system_r:container_t:s0:c123,c456`. Это обеспечивает строгую изоляцию между контейнерами на уровне ядра. Флаги `:z` и `:Z` управляют relabel для общего и приватного доступа соответственно.

Подробнее: [Хранилище и работа с файловой системой](./podman_volumes_and_storage.md).

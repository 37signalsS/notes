# Podman: Основные команды

## Определения

**Podman (Pod Manager)** — инструмент управления контейнерами OCI-совместимыми контейнерами с архитектурой без демона (daemonless). Полная замена Docker CLI с поддержкой rootless-режима по умолчанию.

## Основные концепции

### Ключевые особенности Podman

- **Daemonless-архитектура** — нет центрального демона, каждый контейнер запускается как независимый процесс
- **Rootless по умолчанию** — контейнеры запускаются от имени непривилегированного пользователя
- **Совместимость с Docker CLI** — команды работают идентично (`alias docker=podman`)
- **Нативная поддержка подов** — группировка контейнеров по аналогии с Kubernetes
- **Интеграция с systemd** — генерация unit-файлов для автозапуска контейнеров
- **Автообновление контейнеров** — встроенный механизм updates/rollback через `podman auto-update`
- **Экономия ресурсов** — на 65% меньше памяти в режиме простоя по сравнению с Docker

## Установка

### RHEL и совместимые дистрибутивы (AlmaLinux, Rocky Linux)

В RHEL и подобных дистрибутивах Podman устанавливается через модули:

```bash
# Поиск модуля
dnf module list | grep container

# Включение модуля (обычно container-tools)
dnf module enable container-tools

# Установка
dnf module install container-tools
```

### Fedora

```bash
dnf install podman
```

### Ubuntu/Debian

```bash
# Добавление репозитория
echo "deb https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/xUbuntu_$(lsb_release -rs)/ /" | sudo tee /etc/apt/sources.list.d/devel:kubic:libcontainers:stable.list
wget -qO - "https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/xUbuntu_$(lsb_release -rs)/Release.key" | sudo apt-key add -
sudo apt update
sudo apt install podman
```

### macOS/Windows

Для macOS и Windows используется Podman Desktop с виртуальной машиной:

```bash
# macOS (Homebrew)
brew install podman

# Инициализация VM
podman machine init
podman machine start
```

### Проверка установки

```bash
podman --version
podman info
```

## Основные концепции

### Работа с образами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Поиск образов** | `podman search <образ>` | Поиск образов в реестрах |
| **Скачивание** | `podman pull <образ>` | Скачать образ из реестра |
| **Список образов** | `podman images` | Показать локальные образы |
| **Тегирование** | `podman tag <образ> <новое_имя>` | Добавить тег (например, для пуша в локальный реестр) |
| **Инспекция** | `podman inspect <образ>` | Показать метаданные образа (порты, переменные, пользователь) |
| **Удаление** | `podman rmi <образ>` | Удалить локальный образ |

### Работа с контейнерами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Запуск** | `podman run -d --name <имя> -p <порт_хост>:<порт_контейнер> <образ>` | Создать и запустить контейнер |
| **Список (работающие)** | `podman ps` | Показать запущенные контейнеры |
| **Список (все)** | `podman ps -a` | Показать все контейнеры |
| **Логи** | `podman logs <контейнер>` | Показать логи контейнера |
| **Выполнить команду** | `podman exec -it <контейнер> <команда>` | Выполнить команду в работающем контейнере |
| **Остановка** | `podman stop <контейнер>` | Остановить контейнер |
| **Запуск** | `podman start <контейнер>` | Запустить остановленный контейнер |
| **Удаление** | `podman rm <контейнер>` | Удалить контейнер |

### Практические примеры

**Запуск веб-сервера Nginx:**

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

**Использование Volume:**

```bash
# Монтирование директории
podman run -d --name myapp -v /home/user/data:/data myimage

# Ключ -Z для SELinux (RHEL)
podman run -d --name myapp -v /home/user/data:/data:Z myimage
```

## Работа с локальным реестром

Для экономии трафика и работы в изолированных сетях можно поднять локальный реестр образов.

**Запуск реестра:**

```bash
# Создание директории для хранения образов
mkdir -p ~/registry

# Запуск контейнера с реестром
podman run -d --name registry \
  -p 5000:5000 \
  -v ~/registry:/var/lib/registry:z \
  registry
```

**Настройка политики доверия (без HTTPS):**

В файле `/etc/containers/registries.conf`:

```toml
[[registry]]
location = "localhost:5000"
insecure = true
```

**Загрузка образа в локальный реестр:**

```bash
# Скачивание официального образа
podman pull docker.io/library/nginx

# Тегирование для локального реестра
podman tag docker.io/library/nginx localhost:5000/nginx

# Загрузка
podman push localhost:5000/nginx
```

**Использование Skopeo для копирования:**

```bash
# Копирование образа из Docker Hub в локальный реестр
skopeo copy docker://docker.io/library/httpd docker://localhost:5000/httpd
```

## Практические сценарии

### Работа с подами

Podman поддерживает концепцию подов (группы контейнеров с общими ресурсами), аналогичную Kubernetes:

```bash
# Создание пода
podman pod create --name mypod -p 8080:80

# Запуск контейнера в поде
podman run -d --pod mypod --name web nginx

# Список подов
podman pod ps

# Остановка пода (останавливает все контейнеры в поде)
podman pod stop mypod

# Удаление пода
podman pod rm mypod
```

### Генерация Kubernetes-манифестов

```bash
# Экспорт существующего контейнера/пода в Kubernetes YAML
podman generate kube mypod > mypod.yaml

# Запуск Kubernetes-манифеста локально
podman play kube mypod.yaml
```

### Миграция с Docker

```bash
# Создание алиаса для совместимости
alias docker=podman

# Импорт Docker-образов
podman load < docker-save-output.tar

# Экспорт образов для Docker
podman save -o output.tar image:tag
```

## Дополнительная информация

### Cockpit интеграция

Podman интегрирован в **Cockpit** — веб-интерфейс для администрирования Linux-серверов.

После установки модуля `container-tools` в Cockpit появляется вкладка **Podman Containers**, где можно:

- Управлять контейнерами (запуск, остановка, удаление)
- Просматривать логи
- Подключаться к контейнеру через терминал
- Создавать и управлять Pod'ами

Для активации запустите сервис:

```bash
systemctl enable --now cockpit.socket
```

Доступ через: `https://<сервер>:9090`

### Экосистема инструментов Podman

Podman следует Unix-философии и является частью набора специализированных утилит:

| Инструмент | Назначение |
| :--- | :--- |
| **Podman** | Управление контейнерами и подами | этот файл |
| **Buildah** | Сборка OCI-образов | [Альтернативные среды выполнения](../Docker/alternative_runtimes_and_tools.md) |
| **Skopeo** | Копирование образов между реестрами | [Альтернативные среды выполнения](../Docker/alternative_runtimes_and_tools.md) |
| **CRI-O** | CRI-совместимая среда для Kubernetes | [Альтернативные среды выполнения](../Docker/alternative_runtimes_and_tools.md) |

### Производительность и бенчмарки

| Операция | Podman 5.3 | Docker 27.x | Примечание |
| :--- | :--- | :--- | :--- |
| Запуск контейнера | 180-220 мс | 150-180 мс | Docker на 15% быстрее |
| Pull образа (1 ГБ) | 2,1 с | 1,9 с | Docker на 10% быстрее |
| Использование памяти (idle) | 0 МБ | 140-180 МБ | Podman экономит 65% |
| 100 контейнеров | 2,1-2,6 ГБ | 3,2-4,1 ГБ | Podman на 30% меньше |

> **Вывод:** Docker быстрее для отдельных операций, Podman эффективнее для масштабирования и экономии ресурсов.

## Связанные темы

- **Архитектура:** [Daemonless архитектура Podman](./podman_daemonless_architecture.md)
- **Rootless режим:** [Rootless режим в Podman](./podman_rootless.md)
- **Сравнение с Docker:** [Podman vs Docker](./podman_vs_docker.md)
- **Автообновление:** [Автообновление и откат контейнеров](./podman_auto_update.md)
- **Экосистема инструментов:** [Альтернативные среды выполнения](../Docker/alternative_runtimes_and_tools.md)
- **Изоляция в Linux:** [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md)

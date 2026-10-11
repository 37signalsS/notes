# Podman Machine

## Определения

**Podman Machine** — утилита для управления виртуальными машинами (VM), которые предоставляют среду Linux для запуска Podman на macOS и Windows. Поскольку Podman использует Linux-специфичные технологии (namespaces, cgroups), на не-Linux хостах требуется виртуальная машина.

**WSL (Windows Subsystem for Linux)** — подсистема Windows для запуска ELF-бинарников Linux. Podman может использовать WSL2 как драйвер для Podman Machine на Windows.

**QEMU** — эмулятор процессора, используемый Podman Machine на macOS для виртуализации x86_64/ARM64 контейнеров.

**gvproxy** — прокси для сетевого взаимодействия между хостом и виртуальной машиной Podman Machine.

**userneternet** — пользовательская сеть (user-mode networking) для Podman Machine, обеспечивающая проброс портов без привилегий root.

---

## Теоретический блок

### Архитектура Podman Machine

```
┌─────────────────────────────────────────────────────────────┐
│                     Хост (macOS/Windows)                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Podman CLI (podman ...)                 │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │ gRPC                              │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │           podman-machine-api (daemon)                │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                   │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │              Виртуальная машина (QEMU/WSL2)         │    │
│  │  ┌─────────────────────────────────────────────┐    │    │
│  │  │         Podman (rootless daemon)            │    │    │
│  │  │         Container storage (overlay)         │    │    │
│  │  │         Netavark + aardvark-dns             │    │    │
│  │  └─────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Поддерживаемые платформы

| Платформа | Драйвер VM | Архитектура | Статус |
|---|---|---|---|
| macOS (Intel) | QEMU | x86_64 | Стабильно |
| macOS (Apple Silicon) | QEMU | ARM64 | Стабильно |
| Windows (Hyper-V) | Hyper-V | x86_64 | Стабильно |
| Windows (WSL2) | WSL2 | x86_64 | Стабильно |
| Linux | Нет (нативно) | x86_64/ARM64 | Нативно |

### Podman Machine vs Docker Desktop

| Аспект | Podman Machine | Docker Desktop |
|---|---|---|
| Лицензия | Apache 2.0 (бесплатно) | Коммерческая (для организаций) |
| Daemon | Rootless, daemonless | Docker daemon (root) |
| VM | QEMU/WSL2/Hyper-V | HyperKit/Hyper-V/WSL2 |
| Нагрузка | Минимальная | Средняя |
| Kubernetes | Podman kube play | Встроенный K8s |
| Интеграция с IDE | Базовая | Отличная (VS Code, etc.) |

---

## Практический блок

### 1. Установка Podman Machine

#### macOS (Homebrew)

```bash
# Установка Podman (включает podman-machine)
brew install podman

# Проверка версии
podman --version
podman machine --version

# Инициализация VM
podman machine init

# Запуск VM
podman machine start

# Проверка статуса
podman machine list
```

#### Windows (WinGet)

```powershell
# Установка Podman
winget install RedHat.Podman

# Установка Podman Desktop (GUI)
winget install RedHat.Podman-Desktop

# Инициализация VM (WSL2)
podman machine init --user-mode-networking

# Запуск VM
podman machine start
```

#### Windows (Chocolatey)

```powershell
choco install podman
podman machine init
podman machine start
```

### 2. Управление VM

```bash
# Список машин
podman machine ls

# Информация о машине
podman machine inspect

# Остановка
podman machine stop

# Запуск
podman machine start

# Перезапуск
podman machine stop && podman machine start

# Удаление
podman machine rm

# Сброс (удаление и пересоздание)
podman machine rm -f
podman machine init
podman machine start
```

### 3. Настройка VM

#### Изменение ресурсов

```bash
# Инициализация с настройками ресурсов
podman machine init \
  --cpus 4 \
  --memory 8192 \
  --disk-size 100

# Изменение настроек (после создания)
podman machine set --cpus 4
podman machine set --memory 8192
podman machine set --disk-size 100
```

#### Настройка сети

```bash
# Проброс портов (macOS)
podman machine init --experimental-net-userland

# WSL2 с пользовательской сетью
podman machine init --user-mode-networking

# Проверка сетевых настроек
podman machine inspect | jq '.Networking'
```

#### Настройка SSH

```bash
# Подключение к VM через SSH
podman machine ssh

# Выполнение команд в VM
podman machine ssh -- ls -la /etc/containers/

# Копирование файлов
podman machine ssh -- cat /etc/os-release
```

### 4. Работа с контейнерами через Podman Machine

```bash
# Все команды podman работают как обычно
podman run -d -p 8080:80 nginx:alpine

# Проверка контейнеров
podman ps

# Сборка образов
podman build -t my-app .

# Подключение к реестрам
podman login docker.io
podman push my-app:latest docker.io/myuser/my-app:latest

# Работа с подами
podman pod create --name my-pod -p 8080:80
podman run --pod my-pod -d nginx:alpine
```

### 5. Подключение к Docker Hub

```bash
# Настройка Docker-совместимости
podman machine ssh -- sudo ln -s /usr/bin/podman /usr/bin/docker

# Или использовать podman-docker
brew install podman-docker  # macOS

# Проверка
docker version  # Должен показать Podman
```

### 6. Интеграция с IDE

#### VS Code

```json
// settings.json
{
  "docker.path": "/opt/homebrew/bin/podman",
  "docker.composePath": "/opt/homebrew/bin/podman-compose",
  "docker.dockerPath": "/opt/homebrew/bin/podman"
}
```

#### Podman Desktop

```bash
# Установка Podman Desktop
brew install --cask podman-desktop  # macOS

# Запуск
open /Applications/Podman\ Desktop.app
```

### 7. Работа с Kubernetes

```bash
# Локальный K8s через Podman
podman kube play my-pod.yaml

# Генерация K8s манифеста из пода
podman pod create --name my-pod -p 8080:80
podman run --pod my-pod -d nginx:alpine
podman kube generate my-pod > my-pod.yaml

# Остановка
podman kube down my-pod.yaml
```

### 8. Отладка Podman Machine

```bash
# Проверка логов VM
podman machine ssh -- journalctl -u podman

# Проверка хранилища
podman machine ssh -- podman system df

# Проверка сетей
podman machine ssh -- podman network ls

# Очистка VM
podman machine ssh -- podman system prune -af

# Перезапуск Podman service
podman machine ssh -- sudo systemctl restart podman
```

---

## Дополнительная информация

### Производительность

| Параметр | Рекомендация |
|---|---|
| CPU | 2-4 ядра для разработки |
| RAM | 4-8 ГБ для контейнеров |
| Disk | 50-100 ГБ для образов |
| Disk type | SSD рекомендуется |

### Типичные проблемы

| Проблема | Решение |
|---|---|
| VM не запускается | `podman machine rm && podman machine init` |
| Медленная работа | Увеличить CPU/RAM через `podman machine set` |
| Порт не пробрасывается | Проверить `podman port`, использовать `--publish-all` |
| SSH не работает | `podman machine stop && podman machine start` |
| Disk full | `podman machine ssh -- podman system prune -af` |
| Сеть не работает | `podman machine stop && podman machine start` |

### Переход с Docker Desktop

```bash
# 1. Установить Podman
brew install podman

# 2. Инициализировать VM
podman machine init
podman machine start

# 3. Настроить Docker-совместимость
brew install podman-docker

# 4. Остановить Docker Desktop
# (вручную через GUI)

# 5. Проверить
docker version  # Должен показать Podman
podman ps
```

### Ссылки

- **[Podman vs Docker](./podman_vs_docker.md)** — сравнение Podman и Docker
- **[Rootless](./podman_rootless.md)** — rootless режим
- **[Podman基本コマンド](./podman_basic_commands.md)** — CLI команды
- **[Podman Compose](./podman-compose.md)** — Compose совместимость

# force reindex test

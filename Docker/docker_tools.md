# Инструменты управления Docker (TUI, GUI, CLI)

## Определения

**TUI (Terminal User Interface)** — интерактивные консольные клиенты для управления Docker. Позволяют мониторить и управлять контейнерами, образами, сетями и томами в реальном времени внутри терминала.

## Основные концепции

### Классификация инструментов управления

| Категория | Инструмент | Особенности | Когда использовать |
| :--- | :--- | :--- | :--- |
| **TUI** | **lazydocker** | Поддержка Docker Compose, ASCII-графики, логи | Ежедневная работа, быстрая отладка |
| **TUI** | **oxker** | Написан на Rust, экстремально быстрый | Мониторинг на слабых машинах |
| **TUI** | **docker-tui** | Поддержка MCP (Model Context Protocol) | Интеграция с ИИ-агентами (Claude и др.) |
| **TUI** | **ctop** | Интерфейс в стиле `htop` | Диагностика потребления ресурсов (CPU/Mem) |
| **GUI** | **Portainer** | Управление стеками, пользователями, RBAC | Управление парком серверов, доступ для команд |
| **GUI** | **Yacht** | Упор на шаблоны приложений и простоту | Домашние лаборатории, простые проекты |
| **Utility CLI** | **Skopeo** | Работа с образами без Docker-демона | Синхронизация реестров, инспекция манифестов |

### Взаимодействие с Docker API

Все инструменты взаимодействуют с Docker через API. Основные способы подключения:
1. **Unix Socket:** `/var/run/docker.sock` — стандарт для локального управления.
2. **TCP Socket:** Дистанционное управление (требует настройки TLS для безопасности). См. **[Безопасность хоста и демона](./Docker_security/host_daemon_hardening.md)**.
3. **SSH:** Современный и безопасный способ удаленного подключения через Docker Context.

### Специализированные инструменты анализа
Для глубокого анализа безопасности и структуры образов используются специализированные средства:
- **[dive](./Dockerfile/dockerfile_optimization_tools.md)** — исследование слоев образа и поиск лишних данных.
- **[dockle](./Dockerfile/dockerfile_optimization_tools.md)** — проверка образов на соответствие лучшим практикам безопасности.
- **Dozle** — специализированный веб-интерфейс только для просмотра логов в реальном времени.

## Практические сценарии

### lazydocker: Полнофункциональное TUI-управление

Инструмент предоставляет наиболее полную визуализацию состояния Docker-окружения, включая графы потребления ресурсов.

**Установка (версия v0.25.x+):**
```bash
# Для macOS через Homebrew
brew install jesseduffield/lazydocker/lazydocker

# Для Linux
curl https://raw.githubusercontent.com/jesseduffield/lazydocker/master/scripts/install_update_linux.sh | bash
```

**Ключевые возможности:**
- Просмотр логов контейнеров в реальном времени с поддержкой скроллинга.
- Визуализация Docker Compose проектов и связей между сервисами.
- Выполнение Bulk-команд (остановка всех контейнеров, очистка неиспользуемых данных).

### docker-tui: Интеграция с ИИ (MCP)

Инструмент примечателен встроенным сервером **Model Context Protocol (MCP)**, который позволяет ИИ-агентам (например, Claude Desktop) напрямую взаимодействовать с Docker-окружением.

**Установка:**
```bash
# Через cargo (требуется Rust)
cargo install docker-tui
```

**Особенности:**
- Предоставляет ИИ-контекст о запущенных контейнерах и их состоянии.
- Высокая производительность и низкое потребление ресурсов хоста.

### Skopeo: Копирование образов между реестрами

`skopeo` уникален тем, что позволяет манипулировать образами без их предварительного скачивания (`docker pull`) и без запущенного Docker-демона.

**Сценарий: Копирование из Docker Hub в локальный реестр:**
```bash
# Копирование образа с авторизацией
skopeo copy --src-creds user:pass --dest-creds user:pass \
    docker://docker.io/library/nginx:latest \
    docker://registry.local/infra/nginx:latest

# Инспекция манифеста удаленного образа без скачивания
skopeo inspect docker://docker.io/library/alpine:latest
```

### Portainer: Централизованное GUI-управление

Используется для предоставления графического интерфейса к Docker-хостам или кластерам Swarm.

**Быстрый запуск Portainer Community Edition (CE):**
```bash
# Создание тома для данных
docker volume create portainer_data

# Запуск контейнера с монтированием сокета
docker run -d -p 8000:8000 -p 9443:9443 --name portainer --restart=always \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v portainer_data:/data \
    portainer/portainer-ce:latest
```
*Результат:* Интерфейс доступен по адресу `https://localhost:9443`.

### ctop: Мониторинг в реальном времени

Позволяет быстро идентифицировать контейнеры, вызывающие перегрузку системы.

**Установка (v0.7.7):**
```bash
sudo wget https://github.com/bcicen/ctop/releases/download/v0.7.7/ctop-0.7.7-linux-amd64 -O /usr/local/bin/ctop
sudo chmod +x /usr/local/bin/ctop
```

## Дополнительная информация

**Официальные ресурсы:**
- [lazydocker GitHub](https://github.com/jesseduffield/lazydocker)
- [Portainer Official Site](https://www.portainer.io/)
- [Skopeo GitHub](https://github.com/containers/skopeo)
- [oxker GitHub](https://github.com/mrvillage/oxker)

**Связанные темы:**
- **[Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)** — Podman, Buildah и другие.
- **[Инструменты оптимизации Dockerfile](./Dockerfile/dockerfile_optimization_tools.md)** — dive, dockle, hadolint.
- **[Безопасность Docker: Обзор](./Docker_security/overview.md)** — общие принципы защиты контейнеров.
- **[Docker Context](./docker_context.md)** — управление подключениями к удаленным хостам.

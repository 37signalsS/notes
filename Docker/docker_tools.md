# Инструменты для работы с Docker (TUI)

## Определения

**TUI (Terminal User Interface)** — интерактивные консольные клиенты для управления Docker. Позволяют мониторить и управлять контейнерами, образами, сетями и томами в реальном времени без использования GUI.

## Основные концепции

### Сравнение TUI-инструментов

| Инструмент | Язык | Особенности | Когда использовать |
| :--- | :--- | :--- | :--- |
| **lazydocker** | Go | Полнофункциональный UI, Docker Compose, ASCII-графики | Ежедневная работа, глубокий мониторинг |
| **oxker** | Rust | Высокая скорость, современный интерфейс | Быстрый просмотр и управление |
| **docker-tui** | Rust | Поддержка MCP (Model Context Protocol), логи | Интеграция с ИИ-агентами (Claude и др.) |
| **ctop** | Go | Мониторинг метрик в стиле `htop` | Быстрая диагностика нагрузки CPU/Mem |
| **dry** | Go | Управление без мыши, поддержка Swarm | Работа в чистом CLI, Swarm-кластеры |

### Интеграция с экосистемой

TUI-инструменты взаимодействуют с Docker через API (Unix-сокет `/var/run/docker.sock` или TCP). Это позволяет им работать без установки дополнительных фоновых процессов (демонов).

**Специализированные инструменты:**

- **[dive](./Dockerfile/dockerfile_optimization_tools.md)** — анализ слоев образа (TUI)
- **[dockle](./Dockerfile/dockerfile_optimization_tools.md)** — аудит безопасности образов
- **Dozle** — легковесный веб-интерфейс для логов (альтернатива TUI)

## Практические сценарии

### lazydocker: Полнофункциональное управление

Наиболее популярный инструмент с поддержкой Docker Compose и наглядными графиками ресурсов.

**Установка:**

```bash
# Официальный скрипт для Linux/macOS
curl https://raw.githubusercontent.com/jesseduffield/lazydocker/master/scripts/install_update_linux.sh | bash

# Через Homebrew (macOS)
brew install jesseduffield/lazydocker/lazydocker
```

**Основные горячие клавиши:**

| Клавиша | Действие |
| :--- | :--- |
| **Стрелки / hjkl** | Навигация по спискам |
| **Enter** | Просмотр деталей или логов |
| **b** | Меню команд (Bulk commands) |
| **s** | Остановить контейнер |
| **r** | Перезапустить |
| **d** | Удалить (с подтверждением) |
| **x** | Выполнить команду внутри (exec) |

### docker-tui: Интеграция с ИИ

Современный инструмент на Rust, который примечателен встроенным MCP-сервером.

**Особенности:**
- Позволяет ИИ-агентам (например, Claude Desktop) напрямую взаимодействовать с вашим Docker-окружением.
- Высокая производительность и низкое потребление ресурсов.

**Установка:**
```bash
# Через cargo
cargo install docker-tui
```

### ctop: Быстрая диагностика метрик

Идеален для случаев, когда нужно быстро увидеть, какой контейнер потребляет больше всего ресурсов, без переключения между вкладками.

**Установка (Linux):**
```bash
sudo wget https://github.com/bcicen/ctop/releases/download/v0.7.7/ctop-0.7.7-linux-amd64 -O /usr/local/bin/ctop
sudo chmod +x /usr/local/bin/ctop
```

## Дополнительная информация

**Официальные репозитории:**
- [lazydocker](https://github.com/jesseduffield/lazydocker)
- [oxker](https://github.com/mrvillage/oxker)
- [docker-tui](https://github.com/skanehira/docker-tui)
- [ctop](https://github.com/bcicen/ctop)
- [dry](https://github.com/moncho/dry)

**Связанные темы:**
- [Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)
- [Инструменты оптимизации Dockerfile](./Dockerfile/dockerfile_optimization_tools.md)
- [Безопасность Docker](./Docker_security/overview.md)

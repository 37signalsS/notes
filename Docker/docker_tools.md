# Инструменты для работы с Docker (TUI)

## Определения

**TUI (Terminal User Interface)** — интерактивные консольные клиенты для управления Docker. Позволяют мониторить и управлять контейнерами, образами, сетями и томами в реальном времени без использования GUI.

## Основные концепции

### Сравнение TUI-инструментов

| Инструмент | Язык | Особенности | Когда использовать |
| :--- | :--- | :--- | :--- |
| **lazydocker** | Go | Полнофункциональный UI, Docker Compose, prune | Ежедневная работа, мониторинг ресурсов |
| **oxker** | Rust | Минимализм, высокая скорость | Быстрый просмотр статуса |
| **dry** | Go | Управление без мыши, акцент на клавиатуре | Работа в чистом CLI |
| **ctop** | Go | Мониторинг в стиле `htop` | Быстрая диагностика нагрузки |

### Интеграция с экосистемой

TUI-инструменты работают через Docker API (Unix-сокет `/var/run/docker.sock` или TCP). Не требуют установки дополнительных демонов.

**Альтернативы для анализа образов:**
- **[dive](../Dockerfile/dockerfile_optimization_tools.md)** — исследование слоев образа
- **[dockle](../Dockerfile/dockerfile_optimization_tools.md)** — аудит безопасности

## Практические сценарии

### lazydocker: Ежедневная работа

**Установка:**

```bash
# Официальный скрипт
curl https://raw.githubusercontent.com/jesseduffield/lazydocker/master/scripts/install_update_linux.sh | bash

# Или через Go
go install github.com/jesseduffield/lazydocker@latest
```

**Горячие клавиши:**

| Клавиша | Действие |
| :--- | :--- |
| **Стрелки / hjkl** | Навигация |
| **Enter** | Детали/логи |
| **b** | Меню действий |
| **s** | Остановить контейнер |
| **r** | Перезапустить |
| **d** | Удалить |
| **x** | Выполнить команду (exec) |
| **q** | Выход |

**Сценарии использования:**
- Мониторинг CPU/Memory в реальном времени
- Просмотр логов нескольких контейнеров одновременно
- Очистка ресурсов (`prune`) через меню
- Управление Docker Compose проектами

### ctop: Мониторинг в стиле htop

**Установка и запуск:**

```bash
# Установка
wget https://github.com/bcicen/ctop/releases/download/v0.7.7/ctop-0.7.7-linux-amd64 -O /usr/local/bin/ctop
chmod +x /usr/local/bin/ctop

# Запуск
ctop
```

**Особенности:** Отображает метрики всех контейнеров в одной таблице (аналогично `htop` для процессов). Поддерживает фильтрацию, сортировку по CPU/Memory.

### oxker: Быстрый просмотр

**Установка:**

```bash
# Через cargo (Rust)
cargo install oxker

# Или скачать бинарник
# https://github.com/mrvillage/oxker/releases
```

**Особенности:** Минималистичный интерфейс, низкое потребление ресурсов. Подходит для быстрой проверки статуса контейнеров.

## Дополнительная информация

**Репозитории:** [lazydocker](https://github.com/jesseduffield/lazydocker), [oxker](https://github.com/mrvillage/oxker), [dry](https://github.com/moncho/dry), [ctop](https://github.com/bcicen/ctop).

**Связанные темы:**
- [Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)
- [Инструменты оптимизации Dockerfile](./Dockerfile/dockerfile_optimization_tools.md)

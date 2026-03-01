# Инструкции Dockerfile: Обзор

## Определения

**Инструкции Dockerfile** — это команды в файле `Dockerfile` для пошаговой сборки Docker-образа. Каждая инструкция создаёт новый слой, что позволяет Docker кэшировать результаты и оптимизировать повторные сборки.

## Основные концепции

Dockerfile поддерживает следующие основные инструкции:

| Инструкция | Назначение | Раздел |
| :--- | :--- | :--- |
| `FROM` | Базовый образ | [Базовый образ и метаданные](./base_image_and_metadata.md) |
| `RUN` | Выполнение команд при сборке | [Build-time команды](./build_time_commands.md) |
| `COPY` / `ADD` | Копирование файлов | [Копирование файлов](./copying_files.md) |
| `WORKDIR` | Рабочий каталог | [Рабочий контекст](./working_context.md) |
| `ENV` | Переменные окружения | [Переменные](./environment_variables.md) |
| `ARG` | Аргументы сборки | [Переменные](./environment_variables.md) |
| `EXPOSE` | Порты | [Сеть и порты](./networking_ports.md) |
| `VOLUME` | Тома | [Данные и хранилища](./data_storage.md) |
| `CMD` / `ENTRYPOINT` | Запуск контейнера | [Выполнение при запуске](./runtime_execution.md) |
| `HEALTHCHECK` | Проверка здоровья | [Состояние и сигналы](./health_signals.md) |
| `LABEL` | Метаданные | [Базовый образ и метаданные](./base_image_and_metadata.md) |

## Дополнительная информация

- Следование **[лучшим практикам](../Docker_best_practices/build_optimization.md)** — ключ к эффективным и безопасным образам
- Подробнее о контексте сборки см. **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)**
- Подробнее о BuildKit см. **[Dockerfile BuildKit](../dockerfile_buildkit.md)**

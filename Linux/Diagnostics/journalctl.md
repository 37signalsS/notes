# `journalctl`: Просмотр и анализ логов Systemd

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[journalctl/](./journalctl/)**.

## Навигация

- **[journalctl/journalctl_overview.md](./journalctl/journalctl_overview.md)** — определения, концепции, хранение
- **[journalctl/journalctl_usage.md](./journalctl/journalctl_usage.md)** — просмотр, фильтрация, форматирование
- **[journalctl/journalctl_management.md](./journalctl/journalctl_management.md)** — управление хранением, очистка, интеграция

## Краткое описание

**`journalctl`** — утилита командной строки для просмотра, фильтрации и анализа логов, собранных службой `systemd-journald`.

**Ключевые особенности:**

- Централизованное хранение логов
- Структурированный бинарный формат
- Быстрая фильтрация по метаданным
- Поддержка различных форматов вывода (JSON, syslog)

## Основные команды

| Команда | Описание |
|---------|----------|
| `journalctl` | Все логи |
| `journalctl -f` | Логи в реальном времени |
| `journalctl -u <service>` | Логи сервиса |
| `journalctl -b` | Логи с последней загрузки |
| `journalctl -p err` | Только ошибки |
| `journalctl --vacuum-size=500M` | Очистка до 500 МБ |

## Связанные документы

- **[journald.md](../SystemAdministration/Logging/journald.md)** — конфигурация демона
- **[rsyslog](../SystemAdministration/Logging/rsyslog.md)** — традиционная система логирования
- **[dmesg](./Kernel/dmesg/index.md)** — логи ядра

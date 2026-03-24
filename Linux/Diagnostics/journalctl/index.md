# journalctl — Просмотр и анализ логов Systemd

## Навигация

**Основная информация:**
- **[journalctl_overview.md](./journalctl_overview.md)** — определения, концепции, хранение
- **[journalctl_usage.md](./journalctl_usage.md)** — просмотр, фильтрация, форматирование
- **[journalctl_management.md](./journalctl_management.md)** — управление хранением, очистка, интеграция

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

**Системные службы:**
- **[journald.md](../SystemAdministration/Logging/journald.md)** — конфигурация демона
- **[systemd overview](../Core/systemd/overview.md)** — общие концепции systemd

**Другие системы логирования:**
- **[rsyslog](../SystemAdministration/Logging/rsyslog.md)** — традиционная система
- **[dmesg](./Kernel/dmesg/index.md)** — логи ядра
- **[auditd](../SystemAdministration/Logging/auditd.md)** — аудит безопасности

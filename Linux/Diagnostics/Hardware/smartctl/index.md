# Диагностика дисков с помощью smartctl

Инструменты для мониторинга и диагностики состояния дисков.

## Структура

- **[smart_concepts.md](./smart_concepts.md)** — Определения, концепции S.M.A.R.T., атрибуты для HDD/SSD/NVMe
- **[disk_health_check.md](./disk_health_check.md)** — Проверка здоровья, запуск тестов, мониторинг ошибок
- **[smartd_monitoring.md](./smartd_monitoring.md)** — Настройка автоматического мониторинга через smartd
- **[troubleshooting.md](./troubleshooting.md)** — Диагностика проблем

## Быстрый старт

```bash
# Быстрая проверка здоровья
sudo smartctl -H /dev/sda

# Полная информация
sudo smartctl -a /dev/sda

# Запустить длинный тест
sudo smartctl -t long /dev/sda
```

## Связанные темы

- [Инвентаризация оборудования](./hardware_listing.md)
- [RAID management](../../FileSystems/raid_management.md)
- [iostat](../Filesystem/iostat.md)
- [iotop](../Filesystem/iotop.md)

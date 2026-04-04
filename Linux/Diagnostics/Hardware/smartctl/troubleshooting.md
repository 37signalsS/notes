# Диагностика проблем с smartctl

## Определения

**Troubleshooting smartctl** — процесс диагностики проблем, связанных с чтением S.M.A.R.T.-данных, интерпретацией результатов самодиагностики и работой с дисками в нестандартных конфигурациях (RAID-контроллеры, NVMe). Базовые концепции S.M.A.R.T. см. в [smart_concepts](./smart_concepts.md).

## Основные концепции

### Типичные проблемы при работе со smartctl

| Проблема | Причина | Решение |
|----------|---------|---------|
| Диск не поддерживает S.M.A.R.T | Старые диски, RAID-контроллеры без passthrough | Указать тип контроллера через `-d` |
| Ошибки чтения атрибутов | Отключён S.M.A.R.T, проблемы с драйверами | Включить через `-s on`, проверить `dmesg` |
| Неполная информация для NVMe | Формат вывода отличается от ATA | Использовать `nvme-cli` для детальной диагностики |

### Интерпретация результатов самодиагностики

| Статус | Описание |
|--------|----------|
| `Completed without error` | Тест пройден успешно |
| `Completed: read failure` | Ошибки чтения (bad sectors) |
| `Completed: servo failure` | Проблемы с сервоприводом |
| `Completed: electrical failure` | Проблемы с электроникой |
| `Aborted by host` | Тест прерван пользователем |

## Практические сценарии

### Диск не поддерживает S.M.A.R.T

```bash
# Некоторые диски (особенно в RAID или старые) не поддерживают S.M.A.R.T.
# Принудительное включение (может не работать)
sudo smartctl -s on /dev/sda

# Для RAID-контроллеров требуется указать тип
sudo smartctl -d megaraid,0 -a /dev/sda
```

### Ошибки чтения атрибутов

```bash
# Проверить поддержку S.M.A.R.T.
sudo smartctl -i /dev/sda

# Проверить логи ядра на ошибки диска
dmesg | grep -i "sd[a-z]"
dmesg | grep -i "I/O error"
```

### NVMe диск показывает неполную информацию

```bash
# Использовать специальный формат вывода
sudo smartctl -a /dev/nvme0n1

# Или использовать nvme-cli для детальной диагностики
sudo nvme smart-log /dev/nvme0n1
sudo nvme health-info /dev/nvme0n1
```

## Дополнительная информация

### Связанные инструменты

Ручная проверка здоровья дисков — [disk_health_check](./disk_health_check.md). Концепции и атрибуты S.M.A.R.T. — [smart_concepts](./smart_concepts.md). Автоматический мониторинг через [smartd_monitoring](./smartd_monitoring.md). Мониторинг производительности дисков — [iostat](../Filesystem/iostat.md), [iotop](../Filesystem/iotop.md), [fio](../Filesystem/fio.md). Инвентаризация оборудования — [lsblk/lsscsi](../hardware_listing.md). Управление RAID-массивами — [mdadm](../../../FileSystems/raid_management.md).

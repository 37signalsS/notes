# Диагностика проблем с дисками

## Диск не поддерживает S.M.A.R.T

```bash
# Некоторые диски (особенно в RAID или старые) не поддерживают S.M.A.R.T.
# Принудительное включение (может не работать)
sudo smartctl -s on /dev/sda

# Для некоторых RAID-контроллеров требуется указать тип
sudo smartctl -d megaraid,0 -a /dev/sda
```

## Ошибки чтения атрибутов

```bash
# Если smartctl не может прочитать атрибуты
# Проверить поддержку S.M.A.R.T.
sudo smartctl -i /dev/sda

# Проверить логи ядра на ошибки диска
dmesg | grep -i "sd[a-z]"
dmesg | grep -i "I/O error"
```

## NVMe диск показывает неполную информацию

```bash
# Для NVMe дисков используйте специальный формат вывода
sudo smartctl -a /dev/nvme0n1

# Или используйте nvme-cli
sudo nvme smart-log /dev/nvme0n1
sudo nvme health-info /dev/nvme0n1
```

## Интерпретация результатов самопроверки

| Статус | Описание |
|--------|----------|
| `Completed without error` | Тест пройден успешно |
| `Completed: read failure` | Ошибки чтения (bad sectors) |
| `Completed: servo failure` | Проблемы с сервоприводом |
| `Completed: electrical failure` | Проблемы с электроникой |
| `Aborted by host` | Тест прерван пользователем |

## Связанные инструменты

- **`iostat`, `iotop`**: Мониторинг производительности дисков — см. [iostat](../Filesystem/iostat.md), [iotop](../Filesystem/iotop.md)
- **`fio`**: Тестирование производительности — см. [fio](../Filesystem/fio.md)
- **`lsblk`, `lsscsi`**: Инвентаризация дисков — см. [Инвентаризация оборудования](./hardware_listing.md)
- **`mdadm`**: Управление RAID — см. [RAID management](../../FileSystems/raid_management.md)
- **`nvme-cli`**: Утилиты для NVMe дисков

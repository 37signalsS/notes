# Проверка здоровья дисков с помощью smartctl

## Определение имени диска

```bash
# Список всех дисков
lsblk

# Список SCSI/SATA устройств
lsscsi

# NVMe диски
ls /dev/nvme*
```

**Имена дисков:**

- SATA/SCSI: `/dev/sda`, `/dev/sdb`, `/dev/nvme0n1`
- NVMe: `/dev/nvme0n1`, `/dev/nvme1n1`

## Быстрая проверка здоровья диска

```bash
# Общий статус здоровья (ATA/SATA)
sudo smartctl -H /dev/sda

# Общий статус здоровья (NVMe)
sudo smartctl -H /dev/nvme0n1

# Проверка с автоопределением типа диска
sudo smartctl -a /dev/sda
```

**Возможные результаты:**

- `PASSED` — диск исправен
- `FAILED` — диск неисправен, требуется замена
- `DISK FAILURE IS IMMINENT` — скорый отказ

## Просмотр всех атрибутов S.M.A.R.T

```bash
# Полная информация (ATA/SATA)
sudo smartctl -a /dev/sda

# Полная информация (NVMe)
sudo smartctl -a /dev/nvme0n1

# Только атрибуты
sudo smartctl -A /dev/sda

# С дополнительной информацией о диске
sudo smartctl -i /dev/sda
```

## Запуск тестов самодиагностики

`smartctl` может инициировать встроенные в диск тесты:

| Тип теста | Длительность | Описание |
|-----------|--------------|----------|
| `short` | 2-5 минут | Быстрая проверка электроники и части поверхности |
| `long` | 1-8 часов | Полное сканирование поверхности |
| `conveyance` | 1-5 минут | Тест после транспортировки (не все диски поддерживают) |

```bash
# Запустить короткий тест в фоновом режиме
sudo smartctl -t short /dev/sda

# Запустить длинный тест в фоновом режиме
sudo smartctl -t long /dev/sda

# Посмотреть результаты последнего теста
sudo smartctl -l selftest /dev/sda

# Полная история самопроверок
sudo smartctl -l selftest /dev/sda

# Прервать текущий тест
sudo smartctl -X /dev/sda
```

**Интерпретация результатов самопроверки:**

- `Completed without error` — тест пройден
- `Completed: read failure` — ошибки чтения (bad sectors)
- `Completed: servo failure` — проблемы с сервоприводом
- `Completed: electrical failure` — проблемы с электроникой
- `Aborted by host` — тест прерван пользователем

## Мониторинг ошибок диска

```bash
# Журнал ошибок (ATA)
sudo smartctl -l error /dev/sda

# Журнал ошибок (NVMe)
sudo smartctl -l error /dev/nvme0n1

# Журнал дефектов (grown defects list)
sudo smartctl -l defect /dev/sda

# Статистика по секторам (SATA)
sudo smartctl -l xselftest /dev/sda
```

## Диагностика проблем с производительностью

```bash
# Проверка температуры
sudo smartctl -A /dev/sda | grep -i temperature

# Проверка количества записанных данных (для SSD)
sudo smartctl -A /dev/sda | grep -E "Total_LBAs_Written|Data_Units_Written"

# Проверка износа SSD
sudo smartctl -A /dev/sda | grep -E "Wear_Leveling|Media_Wearout|Percentage_Used"

# Проверка CRC ошибок (проблемы с кабелем SATA)
sudo smartctl -A /dev/sda | grep -i CRC
```

## Проверка дисков в RAID-массивах

```bash
# Для аппаратных RAID может потребоваться указание типа контроллера
sudo smartctl -d megaraid,0 -a /dev/sda  # LSI MegaRAID, первый диск
sudo smartctl -d 3ware,0 -a /dev/twe0    # 3ware RAID

# Для soft RAID (mdadm)
sudo smartctl -a /dev/sda  # Проверка физических дисков
```

Подробнее см. [Управление RAID в Linux](../../FileSystems/raid_management.md).

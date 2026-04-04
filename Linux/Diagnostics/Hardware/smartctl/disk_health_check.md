# Проверка здоровья дисков с помощью smartctl

## Определения

**`smartctl`** — утилита из пакета `smartmontools` для чтения и анализа данных S.M.A.R.T. Подробные концепции и атрибуты см. в [smart_concepts](./smart_concepts.md).

**Ключевые типы накопителей:**

- **HDD (ATA/SATA)** — `/dev/sda`, `/dev/sdb`
- **NVMe** — `/dev/nvme0n1`, `/dev/nvme1n1`
- **SAS** — `/dev/sda` (протокол SCSI)

## Основные концепции

### Различия ATA и NVMe

| Аспект | ATA/SATA | NVMe |
|--------|----------|------|
| Флаг статуса | `smartctl -H` | `smartctl -H` |
| Полная информация | `smartctl -a` | `smartctl -a` |
| Ключевые атрибуты износа | `Wear_Leveling`, `Total_LBAs_Written` | `Percentage Used`, `Media Wearout` |
| Тесты самодиагностики | `short`, `long`, `conveyance` | Аналогично (зависит от диска) |

### Результаты проверки здоровья

| Статус | Значение |
|--------|----------|
| `PASSED` | Диск исправен |
| `FAILED` | Диск неисправен, требуется замена |
| `DISK FAILURE IS IMMINENT` | Скорый отказ — немедленная замена |

## Практические сценарии

### Определение имени диска

```bash
# Список всех дисков
lsblk

# Список SCSI/SATA устройств
lsscsi

# NVMe диски
ls /dev/nvme*
```

Подробнее об инвентаризации оборудования см. [hardware_listing](../hardware_listing.md).

### Быстрая проверка здоровья

```bash
# Общий статус здоровья (ATA/SATA)
sudo smartctl -H /dev/sda

# Общий статус здоровья (NVMe)
sudo smartctl -H /dev/nvme0n1

# Полная информация с автоопределением типа
sudo smartctl -a /dev/sda
```

### Просмотр атрибутов S.M.A.R.T.

```bash
# Полная информация (ATA/SATA)
sudo smartctl -a /dev/sda

# Полная информация (NVMe)
sudo smartctl -a /dev/nvme0n1

# Только атрибуты (без заголовка)
sudo smartctl -A /dev/sda

# Информация о диске (модель, серийный номер, версия прошивки)
sudo smartctl -i /dev/sda
```

Подробнее о ключевых атрибутах для HDD/SSD/NVMe см. [smart_concepts](./smart_concepts.md).

### Запуск тестов самодиагностики

| Тип теста | Длительность | Описание |
|-----------|--------------|----------|
| `short` | 2-5 мин | Быстрая проверка электроники и части поверхности |
| `long` | 1-8 ч | Полное сканирование поверхности |
| `conveyance` | 1-5 мин | Тест после транспортировки (не все диски поддерживают) |

```bash
# Запустить короткий тест (фоновый режим)
sudo smartctl -t short /dev/sda

# Запустить полный тест (фоновый режим)
sudo smartctl -t long /dev/sda

# Результаты последнего теста
sudo smartctl -l selftest /dev/sda

# Прервать текущий тест
sudo smartctl -X /dev/sda
```

**Интерпретация результатов:**

| Статус | Значение |
|--------|----------|
| `Completed without error` | Тест пройден |
| `Completed: read failure` | Ошибки чтения (bad sectors) |
| `Completed: servo failure` | Проблемы с сервоприводом |
| `Completed: electrical failure` | Проблемы с электроникой |
| `Aborted by host` | Тест прерван пользователем |

### Мониторинг ошибок

```bash
# Журнал ошибок (ATA)
sudo smartctl -l error /dev/sda

# Журнал ошибок (NVMe)
sudo smartctl -l error /dev/nvme0n1

# Журнал дефектов (grown defects list)
sudo smartctl -l defect /dev/sda
```

### Диагностика проблем с производительностью

```bash
# Температура
sudo smartctl -A /dev/sda | grep -i temperature

# Объём записанных данных (SSD)
sudo smartctl -A /dev/sda | grep -E "Total_LBAs_Written|Data_Units_Written"

# Износ SSD
sudo smartctl -A /dev/sda | grep -E "Wear_Leveling|Media_Wearout|Percentage_Used"

# CRC-ошибки (проблемы с кабелем SATA)
sudo smartctl -A /dev/sda | grep -i CRC
```

Рекомендуемые пороги для замены дисков см. в [smart_concepts](./smart_concepts.md#recommended-thresholds).

### Проверка дисков в RAID-массивах

```bash
# Аппаратный RAID (LSI MegaRAID, первый диск)
sudo smartctl -d megaraid,0 -a /dev/sda

# Аппаратный RAID (3ware)
sudo smartctl -d 3ware,0 -a /dev/twe0

# Soft RAID (mdadm) — проверка физических дисков
sudo smartctl -a /dev/sda
```

Подробнее об управлении RAID см. [raid_management](../../../FileSystems/raid_management.md).

## Дополнительная информация

### Надёжность S.M.A.R. диагностики

| Аспект | Надёжность | Примечания |
|--------|------------|------------|
| Раннее предупреждение | Средняя | ~50-70% отказов предсказуемы |
| Reallocated_Sectors | Высокая | Надёжный индикатор деградации HDD |
| Wear_Leveling (SSD) | Высокая | Точно отражает износ флеш-памяти |
| Температура | Средняя | Важно для долгосрочной надёжности |

**Важно:** S.M.A.R.T. не гарантирует обнаружение всех сбоев. Регулярные бэкапы обязательны.

### Автоматический мониторинг

Для автоматического мониторинга и оповещений используйте `smartd`. Подробнее см. [smartd_monitoring](./smartd_monitoring.md).

### Диагностика сложных проблем

Для комплексной диагностики ошибок диска, интерпретации атрибутов и восстановления данных см. [troubleshooting](./troubleshooting.md).

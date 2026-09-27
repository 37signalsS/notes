# Диагностика дисков с помощью smartctl

## Определения

**`smartctl`** — основная утилита командной строки из пакета `smartmontools`, предназначенная для управления и мониторинга систем S.M.A.R.T. на накопителях (HDD, SSD, NVMe). Позволяет считывать атрибуты здоровья, запускать тесты самодиагностики и извлекать журналы ошибок.

**S.M.A.R.T. (Self-Monitoring, Analysis and Reporting Technology)** — встроенная система самодиагностики накопителя. Она непрерывно отслеживает критические параметры (температуру, износ ячеек, количество переназначенных секторов) и сигнализирует о возможной деградации устройства до момента потери данных.

**`smartd`** — фоновый демон для автоматического мониторинга. Выполняет проверки по расписанию и отправляет алерты (email, скрипты) при изменении статуса диска.

**`smartctl_exporter`** — компонент для экспорта метрик S.M.A.R.T. в формате Prometheus, используемый для визуализации в Grafana и алертинга.

---

## Базовые концепции

### Инструментарий и архитектура

Эффективная диагностика в Linux строится на связке инструментов:
- **Ручной анализ:** `smartctl` для мгновенной проверки состояния и запуска глубоких тестов (`short`/`long`).
- **Автоматизация:** `smartd` для непрерывного контроля парка дисков.
- **Экспорт метрик:** `smartctl_exporter` для интеграции с Prometheus и Grafana в инфраструктурах bare metal.
- **Вспомогательные утилиты:** `nvme-cli` для глубокой диагностики NVMe (error log, persistent event log, telemetry), которые `smartctl` не покрывает.

### Поддержка протоколов и типов накопителей

Интерпретация данных зависит от интерфейса и поколения устройства:
- **SATA (HDD/SSD):** Использует классическую таблицу атрибутов с пороговыми значениями (Value, Worst, Threshold).
- **NVMe 1.x/2.0:** Использует упрощенный Health Log Page с ключевыми индикаторами: `Critical Warning`, `Percentage Used` (износ) и `Data Units Written`.
- **NVMe ZNS (Zoned Namespaces):** Современный стандарт (2026+), требующий мониторинга специфических метрик зон (например, `Open Zones Limit`).
- **RAID-контроллеры (LSI, HP, Adaptec):** Команды часто требуют инкапсуляции через флаг `-d` (например, `-d megaraid,N`) для доступа к физическому диску за контроллером.

Подробная теоретическая база доступна в разделе [Определения и концепции S.M.A.R.T.](./smart_concepts.md).

---

## Практические сценарии

### Основные команды

```bash
# Список всех дисков с поддержкой SMART
sudo smartctl --scan

# Общая информация о диске (модель, серийный номер, версия прошивки)
sudo smartctl -i /dev/sda

# Краткий вердикт о состоянии (Health Status)
sudo smartctl -H /dev/sda
# → result: PASSED (ОК) или FAILED (требуется замена)

# Таблица показателей (атрибутов) — только для SATA/SAS
sudo smartctl -A /dev/sda

# Полный вывод атрибутов, логов и результатов тестов
sudo smartctl -a /dev/sda

# Запуск короткого самотеста (2–5 мин) в фоновом режиме
sudo smartctl -t short /dev/sda

# Запуск расширенного самотеста (1–20 часов)
sudo smartctl -t long /dev/sda

# Просмотр журнала результатов самотестирования
sudo smartctl -l selftest /dev/sda

# Просмотр журнала ошибок (Error Log)
sudo smartctl -l error /dev/sda

# Отмена запущенного теста
sudo smartctl -X /dev/sda
```

### Диагностика современных NVMe накопителей

```bash
# Просмотр лога здоровья NVMe (износ, температура, ошибки)
sudo smartctl -a /dev/nvme0n1

# Вывод в формате JSON для автоматизации и скриптов (v7.0+)
sudo smartctl -a /dev/nvme0n1 -j

# Журнал ошибок NVMe
sudo smartctl -l error /dev/nvme0n1

# Журнал самотестирования NVMe
sudo smartctl -l selftest /dev/nvme0n1
```

### Работа с RAID-контроллерами

```bash
# Автоматический поиск всех дисков за контроллерами
sudo smartctl --scan-open

# LSI / Broadcom MegaRAID (диск в слоте 0)
sudo smartctl -d megaraid,0 -a /dev/sda

# HP Smart Array (HPE)
sudo smartctl -d cciss,0 -a /dev/sda

# Dell PERC (обычно использует драйвер megaraid)
sudo smartctl -d megaraid,1 -a /dev/sdb
```

### Внешние USB-накопители и док-станции

```bash
# Универсальная трансляция SAT (SCSI to ATA Translation)
sudo smartctl -d sat -a /dev/sdb

# Для старых контроллеров JMicron
sudo smartctl -d jmicron -a /dev/sdb

# Если устройство является NVMe-диском в USB-боксе
sudo smartctl -d sntjmicron -a /dev/sdb
```

### Принудительное включение SMART

Если диагностика поддерживается, но деактивирована:

```bash
# Активация мониторинга и автоматического сохранения логов
sudo smartctl -s on -o on -S on /dev/sda
```

### Автоматизация через JSON

Для интеграции с скриптами мониторинга используйте флаг `--json`:

```bash
# Проверка здоровья через jq
sudo smartctl -H /dev/nvme0n1 --json | jq '.smart_status.passed'

# Извлечение температуры SATA-диска
sudo smartctl -a /dev/sda --json | jq '.temperature.current'

# Фильтрация критических атрибутов NVMe
sudo smartctl -a /dev/nvme0n1 --json | jq '{percentage_used: .nvme_smart_health_information_log.percentage_used, critical_warning: .nvme_smart_health_information_log.critical_warning}'
```

### Алгоритм глубокой диагностики

1. **Верификация:** Проверьте поддержку S.M.A.R.T. через `sudo smartctl -i /dev/sdX`.
2. **Общий вердикт:** Выполните `sudo smartctl -H /dev/sdX`. Если `FAILED` или `FAILURE IS IMMINENT` — диск подлежит немедленной замене.
3. **Анализ критических ID:** Для SATA-дисков следите за `Reallocated_Sector_Ct` (ID 5) и `Current_Pending_Sector` (ID 197). Рост значений — признак деградации.
4. **Запуск тестов:** Выполните `sudo smartctl -t short /dev/sdX` (2-5 мин) или `long` (несколько часов) для сканирования поверхности.
5. **Проверка результатов:** `sudo smartctl -l selftest /dev/sdX`. Статус `Completed: read failure` требует замены диска.
6. **Корреляция с логами ядра:** Сопоставьте ошибки SMART с `dmesg | grep -iE "sd[a-z]|ata|nvme|error|timeout|reset"` для исключения проблем с шиной или кабелем.

Пошаговое руководство см. в файле [Проверка здоровья дисков](./disk_health_check.md).

### Интеграция с мониторингом (Prometheus)

Для сбора метрик в инфраструктурах bare metal используйте `smartctl_exporter`. Ключевые метрики для алертинга:
- `smartctl_device_critical_warning` — критическое состояние железа.
- `smartctl_device_percentage_used` — достижение лимита ресурса (TBW).
- `smartctl_device_temperature_celsius` — перегрев накопителя.

### Пороговые значения температуры

| Тип накопителя | Норма | Предупреждение | Критично | Действие |
| :--- | :--- | :--- | :--- | :--- |
| **HDD (SATA/SAS)** | 20–40°C | > 45°C | > 55°C | Проверка вентиляции, прогноз замены |
| **SSD (SATA)** | 30–50°C | > 60°C | > 70°C | Снижение нагрузки, улучшение охлаждения |
| **NVMe** | 30–60°C | > 70°C | > 80°C | Троттлинг, возможна деградация производительности |

---

## Дополнительная информация

### Ограничения S.M.A.R.T.

Система S.M.A.R.T. является инструментом предсказания, а не гарантией. Она выявляет постепенную деградацию (например, износ ячеек SSD или механический износ HDD), но не может предсказать мгновенный выход из строя контроллера или блока питания.

**Рекомендация:** Используйте S.M.A.R.T. для планирования замены оборудования, но всегда поддерживайте актуальные резервные копии.

### Быстрое устранение неисправностей

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` | Запуск от обычного пользователя. | `sudo smartctl ...` |
| `Device open failed` | Устройство занято или путь неверный. | Проверьте через `lsblk` или `fdisk -l`. |
| `Device does not support SMART` | Неверный тип устройства или SMART выключен. | Используйте флаг `-d` или `-s on`. |
| `Read SMART Data failed` | Сбой контроллера или несовместимый USB-мост. | Попробуйте другой тип драйвера (`-d sat`). |
| `Aborted by host` | Перегрев диска. | Проверьте температуру, дайте остыть. |

Детальное руководство по troubleshooting см. в файле [Решение проблем (Troubleshooting)](./troubleshooting.md).

### Связанные темы

- [Автоматический мониторинг (smartd)](./smartd_monitoring.md) — настройка алертов, Ansible-деплой, Alertmanager, отладка.
- [Теория и концепции S.M.A.R.T.](./smart_concepts.md) — разбор ID атрибутов и логики.
- [Проверка здоровья дисков](./disk_health_check.md) — пошаговые тесты при получении алерта.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — ошибки доступа, работа с RAID, LVM/multipath/dm-crypt.
- [smartctl_exporter: установка и настройка](./smartctl_exporter.md) — деплой Prometheus-exporter (systemd, Docker, K8s).
- [Мониторинг SMART в Kubernetes](./smartctl_kubernetes.md) — DaemonSet для bare-metal кластеров.
- [Диагностика NVMe: AER и Reset](../nvme-errors-diagnostics.md) — анализ PCIe-ошибок, когда SMART показывает PASSED, но диск нестабилен.
- [Инвентаризация оборудования](../hardware_listing.md) — поиск имен устройств в системе.
- [Диагностика через dmesg](../../Kernel/dmesg/troubleshooting.md) — поиск системных ошибок ввода-вывода.
- [Мониторинг RAID-массивов](../../FileSystems/RAID/monitoring.md) — PromQL-запросы и alerting-правила для RAID + SMART.
- [Основы дискового хранения](../../FileSystems/disk_storage_fundamentals.md) — Write Amplification, TBW, over-provisioning.

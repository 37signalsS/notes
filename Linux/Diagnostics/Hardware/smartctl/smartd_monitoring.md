# Автоматический мониторинг дисков с smartd

## Настройка smartd для автоматического мониторинга

**Конфигурационный файл:** `/etc/smartd.conf`

### Базовая конфигурация

```bash
# Пример конфигурации
# Мониторить все диски с отправкой email при проблемах
DEVICESCAN -H -m admin@example.com

# Мониторить конкретный диск с проверкой всех атрибутов
/dev/sda -H -f -t -l error -l selftest -m admin@example.com

# Мониторить NVMe диск
/dev/nvme0n1 -H -m admin@example.com

# Отправка email только при изменении статуса
/dev/sda -H -m admin@example.com -M onchange

# Отправка email при любом событии
/dev/sda -H -m admin@example.com -M daily
```

### Параметры smartd

| Параметр | Описание |
|----------|----------|
| `-H` | Проверка здоровья диска |
| `-f` | Проверка атрибутов failure |
| `-t` | Проверка всех атрибутов |
| `-l error` | Мониторинг журнала ошибок |
| `-l selftest` | Мониторинг журналов самотестирования |
| `-m` | Email для уведомлений |
| `-M onchange` | Отправлять только при изменении статуса |
| `-M daily` | Отправлять ежедневные отчёты |

## Запуск и управление smartd

```bash
# Запуск демона
sudo systemctl enable --now smartd

# Проверка статуса
sudo systemctl status smartd

# Просмотр логов
journalctl -u smartd -f

# Тестовое уведомление
sudo smartctl -t /dev/sda
```

## Диагностика проблем

### Диск не поддерживает S.M.A.R.T

```bash
# Некоторые диски (особенно в RAID или старые) не поддерживают S.M.A.R.T.
# Принудительное включение (может не работать)
sudo smartctl -s on /dev/sda

# Для некоторых RAID-контроллеров требуется указать тип
sudo smartctl -d megaraid,0 -a /dev/sda
```

### Ошибки чтения атрибутов

```bash
# Если smartctl не может прочитать атрибуты
# Проверить поддержку S.M.A.R.T.
sudo smartctl -i /dev/sda

# Проверить логи ядра на ошибки диска
dmesg | grep -i "sd[a-z]"
dmesg | grep -i "I/O error"
```

### NVMe диск показывает неполную информацию

```bash
# Для NVMe дисков используйте специальный формат вывода
sudo smartctl -a /dev/nvme0n1

# Или используйте nvme-cli
sudo nvme smart-log /dev/nvme0n1
sudo nvme health-info /dev/nvme0n1
```

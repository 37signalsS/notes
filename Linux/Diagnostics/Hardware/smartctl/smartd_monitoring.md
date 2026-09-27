# Автоматический мониторинг дисков с помощью smartd

## Определения

**`smartd`** — системный демон из пакета `smartmontools`, предназначенный для непрерывного фонового мониторинга состояния накопителей. Он автоматически опрашивает атрибуты S.M.A.R.T., запускает запланированные тесты самодиагностики и отправляет уведомления при обнаружении признаков деградации оборудования.

**`/etc/smartd.conf`** — основной конфигурационный файл демона, в котором описываются правила сканирования дисков, расписания тестов и методы оповещения.

**`smartd-drivedb`** — база данных параметров и порогов для сотен моделей дисков. Позволяет `smartd` корректно интерпретировать вендор-специфичные атрибуты. Обновляется командой `update-smart-drivedb`.

**SMARTD_FAILTYPE** — тип события, сгенерированного `smartd`: `EmailTest`, `Health`, `Usage`, `SelfTest`.

---

## Базовые концепции

### Принцип работы и архитектура

Демон `smartd` работает в модели опроса (polling) с реакцией на события.

1.  **Инициализация:** При старте systemd-службы `smartd` читает `/etc/smartd.conf` и выполняет сканирование устройств (`DEVICESCAN` или явный список).
2.  **Опрос (Polling):** С заданным интервалом (по умолчанию 1800 секунд / 30 минут, настраивается флагом `-i`) демон считывает атрибуты здоровья всех указанных устройств.
3.  **Анализ:** Изменения атрибутов, провалы тестов или статус `FAILED`/`FAILURE IS IMMINENT` триггерят события.
4.  **Реакция:** Выполняются действия из конфигурации: отправка email (`-m`), запуск скрипта (`-M exec`) или логирование.

Для понимания внутренней логики работы протоколов ATA/SATA, NVMe и SAS, а также механики самотестирования, см. [Теория и концепции S.M.A.R.T.](./smart_concepts.md).

### Ключевые флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| **`-d <type>`** | Тип устройства: `ata`, `scsi`, `nvme`, `megaraid,N`, `cciss,N`, `aacraid,N`. |
| **`-i <N>`** | Интервал опроса в секундах (по умолчанию 1800). |
| **`-n <mode>`** | Режим проверки standby-дисков: `q` (тихий), `nocheck`. |
| **`-q <type>`** | Тип вывода: `errorsonly`, `silent`. |
| **`-r <type>`** | Дополнительный вывод: `a` (атрибуты), `H` (здоровье). |
| **`-D`** | Режим отладки (debug). |
| **`-c`** | Проверка конфигурации (dry-run). |
| **`-p`** | Изменение планировщика (scheduler) на диск. |

### Логирование и отладка

`smartd` пишет события в syslog/journald. Для отладки используйте:

```bash
# Просмотр логов systemd
sudo journalctl -u smartd -n 100 --no-pager

# Режим отладки в foreground
sudo smartd -D -d

# Проверка конфигурации без запуска
sudo smartd -c
```

### Безопасность

Демон работает от имени `root` для доступа к блочным устройствам. Скрипты, вызываемые через `-M exec`, также выполняются с привилегиями root. Рекомендации:

- Устанавливайте права `0700` на скрипты оповещения.
- Не хардкодите секреты в конфигурацию — используйте переменные окружения или vault.
- Ограничьте сетевой доступ на хосте, если скрипты отправляют данные во внешние системы.

---

## Практические сценарии

### Верификация и запуск службы

```bash
# Проверка статуса systemd-службы
sudo systemctl status smartd

# Просмотр PID и активных устройств
ps aux | grep smartd

# Тестовый запуск в foreground с debug-логированием
sudo smartd -D -d

# Применение новой конфигурации
sudo systemctl reload smartd
```

### Настройка универсального мониторинга

Типовая конфигурация для большинства серверов (в файле `/etc/smartd.conf`):

```text
DEVICESCAN -a -o on -S on -W 4,45,55 -n standby,q -m admin@example.com -M exec /usr/local/bin/smartd-notify.sh
```

*   `-W 4,45,55`: Логировать изменения температуры на 4°C, предупреждать при 45°C, критично при 55°C.
*   `-n standby,q`: Не будить диск, если он в режиме энергосбережения.

### Расписание регулярных тестов

Для глубокой проверки поверхности HDD/SSD рекомендуется следующее расписание:

```text
# /dev/sda: Short-тест каждую ночь в 02:00, Long-тест по воскресеньям в 03:00
/dev/sda -a -d ata -s (S/../.././02|L/../../7/03) -m root@localhost
```

### Конфигурация для конкретных устройств

Вместо `DEVICESCAN` можно использовать явное указание устройств для тонкой настройки:

```text
# SATA HDD — полный мониторинг, ежедневный short-тест
/dev/sda -a -d ata -s (S/../.././02) -m admin@example.com

# NVMe SSD — мониторинг износа и температуры
/dev/nvme0n1 -a -d nvme -s (S/../.././02) -m admin@example.com

# Диск за RAID-контроллером (LSI MegaRAID, слот 0)
/dev/sda -a -d megaraid,0 -m admin@example.com
```

Для детальной работы с RAID, USB-дисками и дисками в standby см. [Решение проблем (Troubleshooting)](./troubleshooting.md).

### Переменные окружения для скриптов оповещения

При вызове скрипта через `-M exec`, `smartd` передает детальную информацию через переменные окружения:

- **`SMARTD_DEVICE`** — путь к устройству (например, `/dev/nvme0n1`).
- **`SMARTD_MESSAGE`** — текст сообщения об ошибке.
- **`SMARTD_FAILTYPE`** — тип сбоя (`EmailTest`, `Health`, `Usage`, `SelfTest`).
- **`SMARTD_FULLMESSAGE`** — полный отчет утилиты.
- **`SMARTD_TFIRST`** — время первого появления проблемы.
- **`SMARTD_TLAST`** — время последнего появления проблемы.

**Пример скрипта для Telegram (`/usr/local/bin/smartd-notify.sh`):**

```bash
#!/bin/bash
TOKEN="YOUR_BOT_TOKEN"
CHAT_ID="YOUR_CHAT_ID"
TEXT="⚠️ SMARTD ALERT on $(hostname):
Device: $SMARTD_DEVICE
Type: $SMARTD_FAILTYPE
Message: $SMARTD_MESSAGE"

curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
     -d "chat_id=$CHAT_ID" \
     -d "text=$TEXT"
```

**Пример скрипта для webhook (Slack, Discord, custom):**

```bash
#!/bin/bash
WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"
PAYLOAD="{\"text\":\"SMARTD ALERT: $SMARTD_DEVICE — $SMARTD_FAILTYPE: $SMARTD_MESSAGE\"}"

curl -s -X POST "$WEBHOOK_URL" \
     -H "Content-Type: application/json" \
     -d "$PAYLOAD"
```

### Управление и отладка службы

```bash
# Проверка синтаксиса конфигурации и тестовый прогон
sudo smartd -d

# Обновление конфигурации без полной остановки (если поддерживает дистрибутив)
sudo systemctl reload smartd

# Просмотр последних событий мониторинга
sudo journalctl -u smartd -n 50 --no-pager

# Проверка активных устройств (если поддерживается версия smartmontools)
sudo smartctl --scan-open
```

### Обновление базы данных моделей

Новые модели дисков могут распознаваться некорректно без обновления `smartd-drivedb`:

```bash
# Обновление базы данных
sudo update-smart-drivedb

# Автоматическое обновление через cron (еженедельно)
0 3 * * 0 root /usr/sbin/update-smart-drivedb
```

---

## Дополнительная информация

### Деплой smartd через Ansible

Для управления конфигурацией smartd на ферме серверов используйте Ansible-роль.

#### Структура роли

```
roles/
  smartd/
    ├── tasks/
    │   └── main.yml
    ├── templates/
    │   └── smartd.conf.j2
    ├── handlers/
    │   └── main.yml
    └── defaults/
        └── main.yml
```

#### Пример tasks/main.yml

```yaml
- name: Install smartmontools
  package:
    name: smartmontools
    state: present

- name: Deploy smartd configuration
  template:
    src: smartd.conf.j2
    dest: /etc/smartd.conf
    owner: root
    group: root
    mode: '0644'
  notify: Reload smartd

- name: Enable and start smartd
  systemd:
    name: smartd
    state: started
    enabled: yes

- name: Deploy alert script
  copy:
    src: smartd-notify.sh
    dest: /usr/local/bin/smartd-notify.sh
    owner: root
    group: root
    mode: '0700'
```

#### Шаблон smartd.conf.j2

```text
# {{ ansible_managed }}
# Host: {{ inventory_hostname }}
DEVICESCAN -a -o on -S on -W 4,{{ smartd_temp_warn | default(45) }},{{ smartd_temp_crit | default(55) }} -n standby,q -m {{ smartd_email | default('root@localhost') }} -M exec /usr/local/bin/smartd-notify.sh
```

#### Групповая переменная (inventory)

```yaml
# inventory/production.yml
all:
  children:
    db_servers:
      vars:
        smartd_temp_warn: 40
        smartd_temp_crit: 50
        smartd_email: dba-team@example.com
```

### Интеграция с Alertmanager через Prometheus

Для маршрутизации SMART-алертов через Alertmanager используйте `smartctl_exporter` + Prometheus alerting rules.

#### Arrowтектура алертинга

```
smartctl_exporter → Prometheus → Alertmanager → Email / PagerDuty / Telegram
```

#### Пример alerting-правил (Prometheus rules)

```yaml
groups:
  - name: smartctl_alerts
    rules:
      - alert: DiskTemperatureCritical
        expr: smartctl_device_temperature_celsius > 55
        for: 5m
        labels:
          severity: critical
          team: sre
        annotations:
          summary: "Disk {{ $labels.device }} temperature critical: {{ $value }}C"
          runbook_url: "https://wiki.internal/runbooks/disk-replacement"

      - alert: DiskSSDWearWarning
        expr: smartctl_device_percentage_used > 80
        for: 1h
        labels:
          severity: warning
          team: sre
        annotations:
          summary: "SSD {{ $labels.device }} wear: {{ $value }}%"

      - alert: DiskSMARTDown
        expr: up{job="smartctl"} == 0
        for: 5m
        labels:
          severity: warning
```

#### Конфигурация Alertmanager (route)

```yaml
# alertmanager.yml
route:
  group_by: ['alertname', 'device']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        team: sre
      receiver: 'sre-pagerduty'
    - match:
        severity: critical
      receiver: 'sre-pagerduty'
      continue: true
    - match:
        severity: warning
      receiver: 'sre-email'

receivers:
  - name: 'default'
    email_configs:
      - to: 'ops@example.com'

  - name: 'sre-pagerduty'
    pagerduty_configs:
      - service_key: '<your-key>'

  - name: 'sre-email'
    email_configs:
      - to: 'sre@example.com'
        send_resolved: true
```

### Отладка smartd через strace

Если `smartd` не отправляет алерты при проблемах, используйте `strace` для трассировки системных вызовов.

#### Прослушивание системных вызовов

```bash
# Найти PID smartd
pidof smartd

# Трассировка открытий файлов и отправки данных
sudo strace -p $(pidof smartd) -e trace=open,openat,read,write,sendto -f 2>&1 | tee /tmp/smartd-strace.log

# Только сетевые вызовы (для отладки email/webhook)
sudo strace -p $(pidof smartd) -e trace=connect,sendto,recvfrom -f 2>&1

# Фильтрация по device path
sudo strace -p $(pidof smartd) -e trace=openat -f 2>&1 | grep "/dev/sd"
```

#### Интерпретация результатов

| Syscall | Ожидаемое поведение | Проблема |
| :--- | :--- | :--- |
| `openat("/dev/sda", O_RDONLY)` | Успешно | `ENOENT` или `EACCES` — устройство недоступно |
| `read(fd, ...)` | Возврат данных | `EIO` — ошибка чтения SMART |
| `sendto(sock, ...)` | Отправка email/webhook | `ECONNREFUSED` — SMTP-сервер недоступен |
| `write(fd, "smartd", ...)` | Логирование в syslog | Отсутствие = проблема с lstat/log |

#### Отладка конфигурации

```bash
# Проверка конфигурации (dry-run)
sudo smartd -c /etc/smartd.conf

# Запуск в foreground с отладочным выводом
sudo smartd -D -d -i 10

# Проверка, что DEVICESCAN находит все устройства
sudo smartd --scan
```

### Правила udev для автоматического SMART-мониторинга при hot-plug

Правила udev позволяют автоматически запускать проверку SMART при подключении нового диска.

#### Пример udev-правила

```bash
# /etc/udev/rules.d/99-smart-hotplug.rules

# При подключении нового блочного устройства — запустить smartctl
ACTION=="add", SUBSYSTEM=="block", KERNEL=="sd[a-z]", RUN+="/usr/local/bin/smart-hotplug.sh %k"
ACTION=="add", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", RUN+="/usr/local/bin/smart-hotplug.sh %k"
```

#### Скрипт smart-hotplug.sh

```bash
#!/bin/bash
# /usr/local/bin/smart-hotplug.sh
DEVICE="$1"
LOG="/var/log/smart-hotplug.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') Device added: /dev/$DEVICE" >> "$LOG"

# Ожидание инициализации устройства
sleep 3

# Проверка SMART-статуса
if sudo smartctl -H "/dev/$DEVICE" > /dev/null 2>&1; then
  RESULT=$(sudo smartctl -H "/dev/$DEVICE" | grep -i "result")
  echo "$(date '+%Y-%m-%d %H:%M:%S') SMART check /dev/$DEVICE: $RESULT" >> "$LOG"

  # Алерт при проблемах
  if echo "$RESULT" | grep -qiE "FAILED|IMMINENT"; then
    logger -t smart-hotplug "CRITICAL: /dev/$DEVICE — $RESULT"
    # Отправка алерта (email, webhook)
    curl -s -X POST "https://hooks.slack.com/services/XXX" \
      -d "{\"text\":\"CRITICAL: Disk /dev/$DEVICE added with status: $RESULT\"}"
  fi
else
  echo "$(date '+%Y-%m-%d %H:%M:%S') SMART unavailable for /dev/$DEVICE" >> "$LOG"
fi
```

```bash
# Активация правила
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=block
```

### Альтернативы: netdata и telegraf для SMART-метрик

Помимо `smartctl_exporter`, сбор SMART-метрик возможен через другие инструменты.

#### Telegraf: input plugin `smart`

```toml
# /etc/telegraf/telegraf.d/smart.conf
[[inputs.smart]]
  interval = "60s"
  device = "/dev/sda"
  # Или автообнаружение:
  # device = []
  attributes = ["temperature", "power_on_hours", "wear_leveling", "available_spare"]
  taginclude = ["device"]

[[outputs.prometheus_client]]
  listen = ":9226"
```

```bash
# Установка telegraf (Ubuntu/Debian)
sudo apt install telegraf
sudo systemctl enable --now telegraf
```

#### Netdata: встроенный мониторинг дисков

Netdata автоматически определяет SMART-метрики через `smartctl` и отображает их в веб-интерфеесе.

```bash
# Netdata автоматически находит smartctl
# Метрики доступны в: http://netdata:19999/#storage-smart*

# Конфигурация (опционально)
# /etc/netdata/python.d/smartctl.conf
# changed_devices:
#   '/dev/sda': yes
#   '/dev/nvme0n1': yes
```

#### Сравнение инструментов

| Критерий | smartctl_exporter | Telegraf (smart) | Netdata |
| :--- | :--- | :--- | :--- |
| **Назначение** | Только SMART | Универсальный агент | Универсальный мониторинг |
| **Prometheus-native** | Да | Через prometheus_client | Через export |
| **Конфигурация** | YAML | TOML | Автоматическая |
| **Дополнительные метрики** | Нет | Да (CPU, RAM, net) | Да (всё-в-одном) |
| **Деплой в K8s** | DaemonSet | DaemonSet | DaemonSet |
| **Нагрузка** | Минимальная | Средняя | Средняя |

### Формат расписания (Regexp)

Директива `-s` использует формат `T/MM/DD/d/HH`:
- `T`: Тип (S - Short, L - Long, C - Conveyor, O - Offline).
- `MM/DD/d`: Месяц / День / День недели (1-7, где 1 — Понедельник).
- `HH`: Час (00-23).
- `.` — любое значение.

### Отладка отсутствия алертов

Если `smartd` не отправляет уведомления при проблемах:

1. **Проверьте статус службы:** `sudo systemctl status smartd`.
2. **Проверьте синтаксис:** `sudo smartd -d` (вывод в foreground).
3. **Проверьте логи:** `sudo journalctl -u smartd -n 50 --no-pager`.
4. **Проверьте права скрипта:** Скрипт через `-M exec` должен быть исполняемым (`chmod +x`).
5. **Проверьте конфигурацию:** Убедитесь, что директива `-m` или `-M exec` указана для устройства.

### Интеграция с инфраструктурой мониторинга

Для сбора метрик в инфраструктурах bare metal и виртуализации используйте `smartctl_exporter` для интеграции с Prometheus и Grafana. Ключевые метрики для алертинга:
- `smartctl_device_critical_warning` — критическое состояние железа.
- `smartctl_device_percentage_used` — достижение лимита ресурса (TBW).
- `smartctl_device_temperature_celsius` — перегрев накопителя.

### Связанные темы

- [Теория S.M.A.R.T.](./smart_concepts.md) — разбор атрибутов, износа и архитектуры smartd.
- [Ручная проверка (smartctl)](./disk_health_check.md) — пошаговые тесты при получении алерта.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — работа с RAID, USB, LVM/multipath, корреляция с dmesg.
- [smartctl_exporter: установка и настройка](./smartctl_exporter.md) — деплой Prometheus-exporter.
- [Мониторинг SMART в Kubernetes](./smartctl_kubernetes.md) — DaemonSet для K8s.
- [Мониторинг RAID-массивов](../../FileSystems/RAID/monitoring.md) — PromQL-запросы и alerting-правила для RAID + SMART.
- [Основы дискового хранения](../../FileSystems/disk_storage_fundamentals.md) — Write Amplification, TBW, over-provisioning, I/O scheduler.
- [Главная страница раздела](./index.md) — навигация.

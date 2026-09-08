# Обзор юнитов systemd

## Определения

* **Юнит (Unit)** — это базовый объект управления в `systemd`, представляющий системный ресурс, службу или абстрактное состояние. Каждый юнит описывается текстовым файлом конфигурации, расширение которого определяет его функциональную роль.
* **Экземпляр юнита (Unit Instance)** — динамический объект в памяти менеджера `systemd`, представляющий текущее состояние ресурса.
* **Таргет (Target)** — специальный тип юнита, используемый для логической группировки других юнитов и задания целевого состояния системы (аналог runlevels в SysVinit).
* **Слайс (Slice)** — концепция иерархической группировки юнитов для управления ресурсами (CPU, RAM) через контрольные группы (cgroups).
* **Юнит-файл (Unit file)** — текстовый конфигурационный файл в формате INI, описывающий объект. Расширение определяет тип (`.service`, `.socket`, `.mount` и др.).
* **Шаблонный юнит (Template Unit)** — файл с символом `@` в имени (например, `user@.service`), позволяющий запускать несколько экземпляров службы на основе одной конфигурации.
* **Транзиентный юнит (Transient Unit)** — динамически создаваемый объект (через API или `systemd-run`), существующий только до завершения задачи или перезагрузки.
* **Статический юнит (Static Unit)** — юнит без секции `[Install]`, который не может быть включен через `systemctl enable`, но активируется автоматически через зависимости.
* **Генератор (Generator)** — вспомогательная программа, которая динамически создает юниты при каждой загрузке (например, `systemd-fstab-generator` превращает записи `/etc/fstab` в `.mount` юниты).
* **Drop-in (переопределение)** — фрагмент конфигурации в `/etc/systemd/system/<unit>.d/`, который дополняет или переопределяет параметры основного unit-файла.
* **Маскировка (Masking)** — привязка unit-файла к `/dev/null`, предотвращающая активацию юнита. Сильнее отключения (`disable`).
* **Экспозиция (Exposure)** — метрика безопасности `systemd-analyze security`, оценивающая уровень изоляции юнита (0 — идеально, 10 — полностью открыт).

## Основные концепции

### Типы юнитов

`systemd` управляет 12 основными типами объектов.

| Тип юнита | Описание | Основное назначение |
| :--- | :--- | :--- |
| **`.service`** | Процесс или демон. | Запуск приложений, баз данных и фоновых задач. |
| **`.socket`** | IPC-канал или сетевой сокет. | Реализация Socket Activation (ленивый запуск служб). |
| **`.timer`** | Таймер событий. | Запуск задач по расписанию или через интервалы времени. |
| **`.path`** | Мониторинг файловой системы. | Активация юнитов при изменении файлов или папок. |
| **`.mount`** | Точка монтирования. | Декларативное управление ФС (интеграция с `/etc/fstab`). |
| **`.automount`** | Отложенное монтирование. | Монтаж раздела только при фактическом обращении. |
| **`.target`** | Логическая точка синхронизации. | Определение режимов загрузки и групп зависимостей. |
| **`.slice`** | Ресурсный контейнер. | Изоляция и лимитирование ресурсов для групп юнитов. |
| **`.scope`** | Внешний процесс. | Управление процессами, запущенными вне systemd (сессии). |
| **`.swap`** | Раздел подкачки. | Управление областями swap. |
| **`.device`** | Устройство. | Представление оборудования, опознанного ядром и udev. |
| **`.link`** | Сетевое устройство. | Управление именованием интерфейсов через Predictable Network Interface Names. |

### Состояния юнита

Понимание статуса юнита требует анализа трех ключевых параметров:

1. **Load State**: Статус загрузки конфигурации (`loaded`, `not-found`, `error`, `masked`).
2. **Active State**: Высокоуровневое состояние (`active`, `reloading`, `inactive`, `failed`, `activating`, `deactivating`).
3. **Sub State**: Низкоуровневое, специфичное для типа состояние (например, для сервисов: `running`, `exited`, `dead`).

#### Жизненный цикл юнита

Каждый юнит проходит через следующие состояния:

1. **Обнаружение**: `systemd` сканирует стандартные пути (`/etc/systemd/system/`, `/run/systemd/system/`, `/usr/lib/systemd/system/`) в порядке убывания приоритета.
2. **Загрузка**: Парсинг файла конфигурации. При ошибках синтаксиса состояние становится `error`. Если файл привязан к `/dev/null` (masked) — `masked`.
3. **Активация**: Выполнение зависимостей (`After=`, `Requires=`), условий (`Condition...`) и команды запуска (`ExecStart=`).
4. **Активное состояние**: Юнит выполняет свою функцию (процесс работает, сокет слушает, том смонтирован).
5. **Деактивация**: Корректная остановка (`ExecStop=`) или принудительное завершение.
6. **Неактивное состояние**: Юнит остановлен, но конфигурация остается загруженной. При повторном запуске используется существующий экземпляр.
7. **Очистка**: При `daemon-reload` или удалении файла конфигурации юнит полностью выгружается (`not-found`).

### Жизненный цикл экземпляра юнита

```
  ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐
  │  not-found │────▶│   loaded  │────▶│ activating│────▶│   active  │
  └───────────┘     └───────────┘     └───────────┘     └───────────┘
                            ▲                 │                  │
                            │                 │                  ▼
                            │                 │            ┌───────────┐
                            │                 │            │ deactivating│
                            │                 │            └───────────┘
                            │                 │                  │
                            │                 ▼                  ▼
                            │            ┌───────────┐     ┌───────────┐
                            └────────────│ inactive  │◀────│  failed   │
                                         └───────────┘     └───────────┘
```

### Механизмы активации и группировки

* **Socket Activation**: `systemd` создает сокет от имени службы. Служба запускается только при поступлении первого пакета, что устраняет необходимость ждать полной готовности демона при загрузке.
* **Slice и иерархия**: Все юниты распределены по слайсам. По умолчанию существуют `system.slice` (системные службы), `user.slice` (пользовательские сессии) и `machine.slice` (виртуальные машины/контейнеры).
* **Scopes vs Services**: В отличие от сервисов, `.scope` создаются только программно через API `systemd` для процессов, которые уже запущены (например, форки сессий SSH или контейнеры).
* **Default Target Selection**: При загрузке systemd определяет целевой таргет из `/etc/systemd/system/default.target` (симлинк). Если он отсутствует — используется `multi-user.target` или `graphical.target` в зависимости от наличия GUI.

### Открытие конфигурации и приоритеты

`systemd` ищет файлы юнитов в нескольких директориях. При обнаружении нескольких файлов с одинаковым именем используется порядок приоритета:

1. `/etc/systemd/system/` — Локальные настройки администратора (наивысший приоритет).
2. `/run/systemd/system/` — Динамические юниты, созданные в процессе работы.
3. `/usr/lib/systemd/system/` — Юниты, поставляемые пакетами дистрибутива.
4. `/lib/systemd/system/` — Системные юниты (символическая ссылка на `/usr/lib` на большинстве дистрибутивов).

Для просмотра путей поиска используется `systemd-analyze unit-paths`.

### Системные таргеты (Состояния системы)

| Таргет | Описание | Аналог SysV |
| :--- | :--- | :--- |
| `poweroff.target` | Завершение работы и выключение питания. | 0 |
| `rescue.target` | Однопользовательский режим (базовая система). | 1 |
| `multi-user.target` | Многопользовательский режим без GUI (сервер). | 3 |
| `graphical.target` | Полноценная система с графической оболочкой. | 5 |
| `reboot.target` | Перезагрузка системы. | 6 |
| `emergency.target` | Аварийный режим (минимум служб, корень в RO). | - |
| `soft-reboot.target` | (v254+) Перезагрузка только userspace без ядра. | - |

### Шаблонные юниты и экземпляры

Шаблонные юниты содержат символ `@` в имени (например, `app@.service`). При запуске указывается экземпляр:

```bash
# %i будет заменено на 'production'
sudo systemctl start app@production.service
```

Внутри юнит-файла доступны спецификаторы:
* **`%n`** — полное имя экземпляра (`app@production.service`)
* **`%p`** — префикс до `@` (`app`)
* **`%i`** — экземпляр после `@` (`production`)
* **`%u`** — пользователь службы (`root` или значение `User=`)
* **`%h`** — домашняя директория пользователя

Подробнее о спецификаторах и структуре юнит-файлов: [Структура юнит-файла](./systemd_unit_file_structure.md).

### Различие типов юнитов

* **Статические юниты**: Нет секции `[Install]`. Нельзя включить через `enable`. Активируются только через зависимости или явный `start`. Примеры: генераторы `fstab`, `getty`.
* **Генерируемые юниты**: Создаются автоматически из других источников (fstab, udev, crypttab). Не имеют файлов на диске в обычном понимании. Их конфигурацию можно переопределить через drop-in.
* **Транзиентные юниты**: Создаются динамически через D-Bus API или `systemd-run`. Имеют пометку `Transient=yes`. Удаляются при завершении или перезагрузке.
* **Алиасы**: Юнит может иметь альтернативное имя через `Alias=` в `[Install]`. `systemctl status ssh.service` может показывать `sshd.service` как алиас.
* **Юниты `.link`**: Файлы конфигурации для стабильного именования сетевых интерфейсов. `systemd` создает их из данных `udev` и переименовывает интерфейсы согласно политике Predictable Network Interface Names (`eno1`, `enp3s0f1`, `ens18`). Путь: `/etc/systemd/link/*.link`.

### Спецификаторы и экранирование

Для шаблонных юнитов и путей файловых систем используются спецификаторы и правила экранирования:

| Спецификатор | Значение | Пример |
| :--- | :--- | :--- |
| **`%n`** | Полное имя экземпляра | `app@production.service` |
| **`%p`** | Префикс до `@` | `app` |
| **`%i`** | Экземпляр после `@` | `production` |
| **`%u`** | Пользователь службы | `root` или значение `User=` |
| **`%h`** | Домашняя директория пользователя | `/root` |
| **`%f`** | Раскрытый путь (из экранированного) | `/mnt/data share` |

Для имен юнитов, основанных на путях (`.mount`, `.path`, `.device`), используется алгоритм экранирования:
1. Ведущий и конечный слэши удаляются.
2. Остальные слэши заменяются на дефисы (`-`).
3. Спецсимволы заменяются на шестнадцатеричные коды.
4. Утилита для работы с именами: `systemd-escape "/mnt/data share"` → `mnt-data\x20share`.

### Интеграция с контрольными группами (cgroups)

Каждый активный юнит принадлежит к контрольной группе (cgroup) в иерархии `systemd`:

* **Slice-иерархия**: По умолчанию все сервисы попадают в `system.slice`. Пользовательские сессии — в `user.slice`. Виртуальные машины — в `machine.slice`.
* **Delegation**: Для корректного применения лимитов ресурсов родительский slice должен иметь `Delegate=yes`. Без этого подгруппы не смогут управляться отдельно.
* **Трекинг процессов**: `systemd` отслеживает все процессы в cgroup юнита. При остановке сервиса все дочерние процессы получают SIGTERM/SIGKILL согласно `KillMode=`.
* **Аккаунтинг**: Включение `CPUAccounting=yes`, `MemoryAccounting=yes`, `IOAccounting=yes` позволяет `systemd-cgtop` отображать реальное потребление.

Для просмотра иерархии:
```bash
systemd-cgls
systemd-cgtop
```

## Практические сценарии

### Создание сервисного юнита

Создайте файл `/etc/systemd/system/myapp.service`:

```ini
[Unit]
Description=My Application
After=network.target

[Service]
Type=simple
User=app
Group=app
WorkingDirectory=/opt/myapp
ExecStart=/opt/myapp/bin/myapp --config /etc/myapp/config.yaml
Restart=on-failure
RestartSec=5
Environment=APP_ENV=production

[Install]
WantedBy=multi-user.target
```

Примените изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp.service
# → Проверка статуса
systemctl status myapp.service
# → Active: active (running) since ...
```

### Создание таймера

Таймеры заменяют cron с поддержкой зависимостей и календарных выражений.

Файл `/etc/systemd/system/backup.timer`:

```ini
[Unit]
Description=Daily backup at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Файл `/etc/systemd/system/backup.service`:

```ini
[Unit]
Description=Backup job

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now backup.timer
# → Проверка следующего запуска
systemctl list-timers backup.timer
```

### Создание монтируемого юнита

Для сложных сценариев монтирования (NFS, VPN-зависимые тома):

```ini
# /etc/systemd/system/mnt-backup.mount
[Unit]
Description=Backup volume
After=network-online.target
Wants=network-online.target

[Mount]
What=server:/export/backup
Where=/mnt/backup
Type=nfs
Options=noatime,hard,intr

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-backup.mount
# → Проверка статуса монтирования
systemctl status mnt-backup.mount
mount | grep backup
```

### Создание сокета с активацией службы

Служба запускается только при первом подключении:

```ini
# /etc/systemd/system/myapp.socket
[Unit]
Description=MyApp socket

[Socket]
ListenStream=8080
Accept=no

[Install]
WantedBy=sockets.target
```

```ini
# /etc/systemd/system/myapp@.service
[Unit]
Description=MyApp instance for %i

[Service]
Type=simple
ExecStart=/opt/myapp/bin/myapp --id %i
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp.socket
# → При первом подключении systemd запустит myapp@.service
systemctl status myapp.socket
```

### Создание юнита path (мониторинг файловой системы)

```ini
# /etc/systemd/system/watched.path
[Unit]
Description=Watch /etc/myapp/config.yaml

[Path]
PathModified=/etc/myapp/config.yaml

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/reload-config.service
[Unit]
Description=Reload myapp configuration

[Service]
Type=oneshot
ExecStart=/usr/bin/kill -HUP $(cat /run/myapp.pid)
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now watched.path
# При изменении файла сработает reload-config.service (если связан)
```

### Использование systemd-run для временных задач

```bash
# Запуск разовой задачи с лимитом памяти
sudo systemd-run --unit=one-time-backup \
  --description="Daily backup job" \
  --property=MemoryMax=1G \
  --property=CPUQuota=50% \
  --requires=network-online.target \
  --after=network-online.target \
  /usr/local/bin/backup.sh

# Фоновый сервис с автоматической остановкой через 1 час
sudo systemd-run --unit=temp-monitor \
  --property=MemoryMax=512M \
  --timer-property=AccuracySec=1min \
  --remain-after-exit=yes \
  /usr/local/bin/monitor.sh
```

Подробнее: [Временные задачи (systemd-run)](./systemd_run.md).

### Жесткая изоляция сервисов (Sandboxing)

Для production-сервисов применяйте декларативные директивы безопасности. Пример минимального hardening для веб-сервиса:

```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=MyApp Service
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=myapp
Group=myapp
WorkingDirectory=/opt/myapp
ExecStart=/opt/myapp/bin/myapp
Restart=on-failure
RestartSec=5

# Лимиты ресурсов
MemoryMax=512M
CPUQuota=50%
TasksMax=128
IOWeight=50

# Изоляция ФС
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/myapp /var/log/myapp
ReadOnlyPaths=/etc/myapp/config.yaml

# Изоляция ядра и оборудования
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
MemoryDenyWriteExecute=yes
NoNewPrivileges=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
```

Применение:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp.service
# Проверка уровня безопасности
systemd-analyze security myapp.service
```

### Управление ресурсами через slice

Группируйте сервисы для совместного управления ресурсами:

```ini
# /etc/systemd/system/myapp.slice
[Slice]
CPUWeight=100
MemoryMax=2G
IOWeight=50
TasksMax=512

# /etc/systemd/system/myapp-frontend.service
[Unit]
Slice=myapp.slice

[Service]
ExecStart=/opt/myapp/frontend
MemoryMax=512M
CPUQuota=40%
```

```bash
# Просмотр потребления ресурсов slice
systemd-cgtop
systemctl status myapp.slice

# Проверка параметров cgroup
systemctl show myapp.slice -p CPUWeight -p MemoryMax -p IOWeight
```

### Использование run0 (v256+)

```bash
# Выполнение команды с привилегиями root без sudo
run0 --user=www-data ls /var/www/html

# Аналог sudo systemctl restart
run0 systemctl restart nginx.service
```

### Работа с шаблонными экземплярами

```ini
# /etc/systemd/system/vpn@.service
[Unit]
Description=VPN Tunnel for %i
After=network-online.target
Wants=network-online.target
BindsTo=sys-subsystem-net-devices-tun%i.device
After=sys-subsystem-net-devices-tun%i.device

[Service]
Type=simple
ExecStart=/usr/bin/openvpn --config /etc/openvpn/%i.conf

[Install]
WantedBy=multi-user.target
```

```bash
# Запуск конкретного экземпляра
sudo systemctl start vpn@client-office.service
sudo systemctl enable vpn@client-office.service

# Список всех экземпляров
systemctl list-unit-files 'vpn@*'
```

### Drop-in переопределения

```bash
# Создание переопределения
sudo systemctl edit nginx.service
```

Создаст `/etc/systemd/system/nginx.service.d/override.conf`:

```ini
[Service]
RestartSec=10
Environment="NGINX_ENV=prod"
```

При необходимости полной замены:

```bash
sudo systemctl edit --full nginx.service
```

### Диагностика проблем загрузки юнитов

```bash
# Проверка синтаксиса конкретного юнита
systemd-analyze verify /etc/systemd/system/myapp.service

# Проверка всех юнитов в каталоге
find /etc/systemd/system -name '*.service' -exec systemd-analyze verify {} +

# Просмотр путей поиска
systemd-analyze unit-paths

# Поиск локальных изменений
systemd-delta

# Детальный статус с логикой
systemctl show myapp.service -p FragmentPath -p DropInPaths -p ConditionResult

# Проверка результата условий
systemctl show myapp.service -p ConditionResult

# Проверка, что юнит загружен из ожидаемого источника
systemctl show myapp.service -p FragmentPath
```

### Изоляция через кастомный таргет

Создайте `/etc/systemd/system/maintenance.target`:

```ini
[Unit]
Description=Maintenance Mode
Conflicts=nginx.service postgresql.service
After=nginx.service postgresql.service
```

Активация:

```bash
sudo systemctl isolate maintenance.target
# Возврат к нормальному режиму
sudo systemctl default
```

### Очистка и обслуживание

```bash
# Удаление drop-in переопределения
sudo rm /etc/systemd/system/my-app.service.d/override.conf

# Полная откатка к системной версии
sudo systemctl revert my-app.service

# Удаление симлинка автозапуска
sudo systemctl disable my-app.service

# Снятие маскировки
sudo systemctl unmask my-app.service

# Перезагрузка конфигурации
sudo systemctl daemon-reload

# Проверка после изменений
systemctl is-active my-app.service
systemctl is-enabled my-app.service
systemd-analyze verify /etc/systemd/system/my-app.service
```

### Мониторинг и наблюдаемость

```bash
# Просмотр дерева контрольных групп
systemd-cgls

# Интерактивный мониторинг потребления ресурсов
systemd-cgtop

# Просмотр логов сервиса в реальном времени
journalctl -u nginx.service -f

# Логи с текущей загрузки
journalctl -b

# Фильтр по приоритету
journalctl -u sshd.service -p err --since today

# Просмотр всех failed-юнитов
systemctl --failed

# Список всех загруженных, но неактивных юнитов
systemctl list-units --all --state=inactive

# Юниты, тормозящие загрузку
systemd-analyze blame

# Аудит безопасности юнита (Exposure Level)
systemd-analyze security nginx.service

# Визуализация дерева зависимостей
systemd-analyze dot nginx.service | dot -Tsvg > nginx-deps.svg

# Проверка использования ресурсов конкретным юнитом
systemctl show nginx.service -p MemoryCurrent -p CPUUsageNSec -p TasksCurrent
```

### Ротация и хранение логов journald

Настройка `/etc/systemd/journald.conf` для production:

```ini
[Journal]
Storage=persistent
Compress=yes
Seal=yes
SplitMode=uid
MaxRetentionSec=1week
SystemMaxUse=1G
SystemKeepFree=2G
MaxFileSec=1day
ForwardToSyslog=no
ForwardToWall=no
```

```bash
# Применение настроек
sudo systemctl restart systemd-journald

# Проверка размера журналов
journalctl --disk-usage
# → Archived and active journals take up 1.2G on disk.

# Очистка старых записей
sudo journalctl --vacuum-time=7d
sudo journalctl --vacuum-size=500M
```

### Работа с Predictable Network Interface Names

`.link` юниты управляют стабильным именованием интерфейсов:

```bash
# Просмотр текущих link-юнитов
systemd-analyze verify /etc/systemd/link/*.link

# Список интерфейсов с их MAC и текущим именем
networkctl list

# Статус конкретного интерфейса
networkctl status eth0
```

Пример `.link` файла для фиксации имени интерфейса по MAC:

```ini
# /etc/systemd/link/10-enp3s0.link
[Match]
MACAddress=00:11:22:33:44:55

[Link]
Name=enp3s0
```

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Unit not found` | Файл отсутствует или ошибка в имени. | `systemd-analyze unit-paths`; проверьте расширение и экранирование. | Создайте юнит или исправьте имя. |
| `Unit is masked` | Юнит привязан к `/dev/null`. | `systemctl status <unit>` | `systemctl unmask <unit> && systemctl daemon-reload` |
| `Dependency failed` | Не удалось запустить зависимый юнит. | `systemctl list-dependencies <unit>`; проверьте failed-юниты. | Исправьте или отключите проблемную зависимость. |
| `Condition... failed` | Условие не выполнено. | `systemctl show <unit> -p ConditionResult` | Создайте путь/ресурс или измените условие. |
| `Ordering cycle` | Противоречивые `After=`/`Before=`. | `systemd-analyze critical-chain <unit>` | Пересмотрите порядок зависимостей. |
| `Failed at step cgroup` | Ошибка delegation или права cgroup. | `journalctl -u <unit> -n 30` | Проверьте `Delegate=yes` в родительском slice. |
| `Unit entered failed state` | Процесс завершился с ненулевым кодом. | `journalctl -u <unit> -n 100` | Проверьте `ExecStart`, права, зависимости. |
| `Job is queued but not starting` | Блокирующая зависимость или `Condition*`. | `systemctl list-jobs` | Убедитесь, что условия выполнены. |
| `Reload failed` | Юнит не поддерживает перезагрузку. | `journalctl -u <unit> -n 50` | Используйте `restart` или проверьте конфигурацию. |
| `Timeout start failed` | `ExecStart=` не завершился за `TimeoutStartSec=`. | `journalctl -u <unit> -b` | Увеличьте таймаут или исправьте приложение. |
| `Mount unit failed` | Ошибка в `/etc/fstab` или устройство недоступно. | `journalctl -b -t systemd-fstab-generator` | Проверьте UUID, опции монтирования. |
| `Conflicts= не останавливает цель` | `Conflicts=` работает только при активации. | `systemctl status <unit>` | Используйте `systemctl stop` явно. |
| `PartOf= не останавливает ребенка` | `PartOf=` срабатывает только при stop/restart родителя. | `systemctl show <parent> -p PartOf` | Добавьте `BindsTo=` для каскадного падения. |
| `BindsTo= срабатывает на missing device` | Устройство отключено, но юнит должен оставаться активным. | `systemctl status <unit>` | Замените `BindsTo=` на `Requires=` для временно исчезающих устройств. |
| `Unit stuck in activating` | Долгий прогрев приложения или `Type=simple` для демона с fork(). | `systemctl show <unit> -p Type,Result` | Используйте `Type=notify` или `Type=exec`; проверьте `TimeoutStartSec=`. |
| `Resource limit exceeded` | Достигнут лимит `MemoryMax=`, `CPUQuota=`, `TasksMax=`. | `systemctl show <unit> -p MemoryCurrent,CPUUsageNSec,TasksCurrent` | Увеличьте лимиты или оптимизируйте приложение. |
| `Exposure Level >= 7` | Отсутствуют директивы sandboxing. | `systemd-analyze security <unit>` | Добавьте `ProtectSystem=strict`, `PrivateDevices=yes`, `NoNewPrivileges=yes`. |
| `Journal logs disk full` | `SystemMaxUse` исчерпан или не настроен. | `journalctl --disk-usage` | Настройте `MaxRetentionSec` и `SystemMaxUse` в `/etc/systemd/journald.conf`. |
| `Interface renamed unexpectedly` | Отсутствует или конфликтует `.link` юнит. | `networkctl list`; `systemd-analyze verify /etc/systemd/link/*.link` | Создайте `.link` файл с правильным `[Match]`. |

## Рекомендации по эксплуатации (Best Practices)

1. **Валидация перед применением**: Всегда запускайте `systemd-analyze verify /etc/systemd/system/my-service.service` после создания или изменения юнита. Используйте `systemd-analyze security` для оценки уровня изоляции.
2. **Drop-in вместо правки**: Используйте `systemctl edit` для внесения изменений; это сохраняет возможность обновления пакетов без конфликтов.
3. **Храните конфигурацию в Git**: Коммит-хук с `systemd-analyze verify` предотвращает опечатки и синтаксические ошибки.
4. **Отключайте ненужное**: `systemctl disable --now <service>` для неиспользуемых сервисов. Регулярно проверяйте `systemctl list-units --type=service --state=running`.
5. **Проверка после перезагрузки**: После изменений в критичных для загрузки юнитах выполняйте `systemctl daemon-reload && systemctl restart <unit>` и проверяйте `systemctl is-active`.
6. **Используйте `Wants=` вместо `Requires=`** где возможно: слабые связи повышают отказоустойчивость.
7. **Socket-activation для редких сервисов**: Убирает их из критической цепи загрузки.
8. **Ограничивайте ресурсы**: Добавляйте `MemoryMax=`, `CPUQuota=`, `TasksMax=`, `IOWeight=` в production-юниты.
9. **Изоляция процессов**: Запускайте сервисы от выделенных пользователей (`User=`, `Group=`) с минимальными привилегиями.
10. **Credentials для секретов**: Храните пароли и ключи в `systemd-creds` (v250+), а не в открытом виде в unit-файлах.
11. **Journald для логирования**: Не перенаправляйте stdout/stderr в файлы вручную. Используйте встроенное логирование `journald`.
12. **Аккаунтинг ресурсов**: Включайте `CPUAccounting=yes`, `MemoryAccounting=yes`, `IOAccounting=yes` для детализированной наблюдаемости через `systemd-cgtop`.
13. **Группируйте через slice**: Для связанных сервисов создавайте отдельный `.slice` с предuplifted лимитами, а не задавайте лимиты на каждый юнит индивидуально.
14. **Валидируйте зависимости**: Регулярно запускайте `systemd-delta` для обнаружения локальных изменений и `systemd-analyze critical-chain` для проверки целостности графа.
15. **KillMode=mixed**: Для сервисов, которые порождают дочерние процессы, используйте `KillMode=mixed` — SIGTERM получит только главный процесс, а SIGKILL — все остальные.
16. **Регулярно аудитуйте security exposure**: `systemd-analyze security <unit>` — метрика показывает уровень изоляции. Цель для production-сервисов — `< 5.0`.
17. **Избегайте глубоких цепочек `After=`**: Каждый уровень добавляет латентность. Где возможно, группируйте сервисы под общим таргетом.
18. **Используйте `Condition...` для прозрачности**: Вместо скриптов проверок в `ExecStartPre` применяйте декларативные условия (`ConditionPathExists=`, `ConditionDirectoryNotEmpty=`, `ConditionVirtualization=`).
19. **Перезагрузка без потерь**: Для сервисов с длительным прогревом используйте `Type=notify` или `Type=notify-reload` (v253+), чтобы `systemd` знал точный момент готовности.
20. **Ограничение `TasksMax`**: Устанавливайте `TasksMax=` для защиты от fork-бомб, особенно для публично доступных сервисов.

## Ограничения и особенности

* **Статические юниты**: Некоторые юниты (`.socket`, `.device`, `.mount` из fstab) имеют статус `static` — их нельзя включить/выключить через `enable/disable`. Они активируются только через зависимости.
* **Условия (Condition*)**: Они пропускают запуск без ошибки. `systemctl status` покажет `inactive (dead)` с пометкой `condition`, что может сбивать с толку в скриптах.
* **daemon-reload не перезапускает процессы**: Если вы изменили `User=` или `Environment=`, изменения вступят в силу только после `restart`.
* **network-online.target**: Может никогда не наступить, если `systemd-networkd-wait-online` или `NetworkManager-wait-online` зависают.
* **After= на failed-юниты**: Если юнит, указанный в `After=`, завершился с ошибкой, текущий юнит все равно может запуститься при слабой связи (`Wants=`). Сильная связь (`Requires=`) откажет.
* **Циклические зависимости**: `systemd` принудительно разрывает циклы, удаляя одну из связей. Это может привести к неожиданному поведению.
* **Masked dependencies**: Если юнит А требует юнит Б, а юнит Б замаскирован, запуск А завершится ошибкой, даже если Б не требуется для фактической работы.
* **KillMode=control-group**: По умолчанию systemd убивает все процессы в cgroup при остановке. Для приложений с дочерними процессами используйте `KillMode=mixed`.
* **Temporary users**: `DynamicUser=yes` создает пользователя на время работы сервиса. При остановке пользователь удаляется, но файлы в `/var/lib/` могут остаться.
* **Совместимость**: В дистрибутивах с systemd < 230 некоторые директивы и команды (`calendar`, `inspect-elf`, `run0`) отсутствуют.
* **Генераторы**: Ошибки в `/etc/fstab` (неверный UUID, опции) создают юниты с состоянием `failed`, блокируя загрузку зависимых сервисов.
* **Predictable Network Interface Names**: На ядрах ≥ 3.15 интерфейсы переименовываются автоматически. Старые имена (`eth0`) могут исчезнуть. Используйте `.link` юниты для фиксации имен.
* **Conflicts= и порядок запуска**: `Conflicts=` не влияет на порядок запуска. Добавьте `Before=` или `After=`, если нужна детерминированная последовательность.
* **Condition* директивы и скрипты**: `ConditionPathExists=!/var/run/backup.lock` проверяет состояние только в момент активации. Для гонок используйте `ExecCondition=` с `flock`.
* **daemon-reload и running процессы**: Изменения в unit-файле не применяются к running процессам автоматически. Всегда выполняйте `systemctl restart` после `daemon-reload` для критичных параметров.
* **Static units и drop-in**: Статические юниты (генерируемые из fstab или udev) не имеют файлов на диске. Их конфигурацию можно переопределить только через drop-in в `/etc/systemd/system/`.
* **Slice delegation**: На некоторых дистрибутивах `Delegate=yes` не наследуется автоматически. Проверяйте родительский slice явно: `systemctl show -.slice -p Delegate`.
* **cgroup v1 limitations**: В системах с cgroup v1 отсутствует поддержка `CPUQuotaPeriodSec=`, `MemoryPressure=` и других современных директив. Рекомендуется переход на cgroup v2.
* **Journald storage modes**: `Storage=volatile` (по умолчанию на некоторых дистрибутивах) теряет логи при перезагрузке. Для production используйте `Storage=persistent` с `SystemMaxUse=`.
* **Overlapping monotonic timers**: `OnBootSec=` и `OnStartupSec=` ведут себя одинаково, но `OnStartupSec=` точнее для контейнеров, где `systemd` запускается после частичной инициализации.

## Дополнительная информация

### Пути и приоритеты конфигурации

1. `/etc/systemd/system/` — Локальные настройки администратора (наивысший приоритет).
2. `/run/systemd/system/` — Динамические юниты, созданные в процессе работы.
3. `/usr/lib/systemd/system/` — Юниты, поставляемые пакетами дистрибутива.

### Новое в версиях 255 и 256

* **`run0`**: Новая утилита для выполнения команд с привилегиями, использующая механизмы `systemd` вместо SUID (заменяет `sudo`).
* **`.v/` Директории**: Поддержка версионированных директорий для юнитов и конфигов (автоматический выбор последней версии через `systemd-vpick`).
* **Preserve FD Store**: Возможность сохранения открытых файловых дескрипторов при `kexec` или `soft-reboot`, что позволяет службам сохранять состояние при перезагрузке userspace.
* **Deprecations**: Официально объявлено об устаревании скриптов SysVinit и поддержки контрольных групп cgroup v1.
* **`Type=notify-reload`** (v253+): Нативная перезагрузка через протокол уведомлений без `ExecReload`. При `systemctl reload` `systemd` ожидает `RELOADING=1` → `READY=1`.
* **`ConditionCredential=`** (v250+): Проверка наличия секрета в директории `/run/credentials/`.
* **`ExecSearchPath=`** (v250+): Список путей для поиска исполняемых файлов, аналогичный `$PATH`.
* **`systemd-analyze security`**: Утилита для аудита уровня изоляции юнита по шкале 0–10.
* **Predictable Network Interface Names**: По умолчанию на ядрах ≥ 3.15 systemd использует стабильные имена (`eno1`, `enp3s0f1`, `ens18`) вместо `eth0`. Управляется через `.link` юниты.

### См. также
* [Структура юнит-файла](./systemd_unit_file_structure.md) — разбор секций `[Unit]`, `[Service]` и `[Install]`.
* [Управление зависимостями](./systemd_dependencies.md) — механизмы `Wants`, `Requires`, `Before` и `After`.
* [Типы сервисов](./systemd_service_types.md) — детальный разбор директивы `Type=`.
* [Временные задачи (systemd-run)](./systemd_run.md) — динамические юниты без файлов конфигурации.
* [Таймеры systemd](./timers.md) — планирование задач и отладка расписаний.

# Структура юнит-файла systemd

## Определения

* **Юнит-файл (Unit file)** — текстовый конфигурационный файл в формате INI, описывающий системный ресурс или службу. Расширение определяет тип объекта (`.service`, `.socket`, `.mount` и др.).
* **Секция** — логический блок параметров в квадратных скобках (например, `[Unit]`).
* **Директива** — инструкция вида `Ключ=Значение`. Повторение некоторых ключей дополняет список значений, других — перезаписывает (последнее значение побеждает).
* **Спецификатор (Specifier)** — подстановочный знак (например, `%i`, `%u`), который заменяется на динамические данные в момент загрузки юнита.
* **Шаблонный юнит (Template Unit)** — файл с символом `@` в имени (`user@.service`), позволяющий запускать несколько экземпляров службы на основе одной конфигурации.
* **Drop-in (переопределение)** — фрагмент конфигурации в `/etc/systemd/system/<unit>.d/`, который дополняет или переопределяет параметры основного unit-файла без его изменения.
* **Статический юнит (Static Unit)** — юнит без секции `[Install]`, который нельзя включить через `systemctl enable`, но который активируется автоматически через зависимости.
* **Маскированный юнит (Masked Unit)** — юнит, привязанный к `/dev/null`, предотвращающий его активацию даже вручную.

---

## Основные концепции

### Базовые секции и их назначение

| Секция | Описание | Применимость |
| :--- | :--- | :--- |
| **`[Unit]`** | Метаданные, условия запуска и описание зависимостей. | Все типы юнитов. |
| **`[Service]`** | Параметры запуска процесса и управления ресурсами. | Только для `.service`. |
| **`[Socket]`** | Описание сетевых портов или IPC-каналов, параметры accept. | Только для `.socket`. |
| **`[Timer]`** | Расписание активации связанного сервиса. | Только для `.timer`. |
| **`[Mount]`** | Параметры точки монтирования ФС. | Только для `.mount`. |
| **`[Install]`** | Логика связывания юнита с таргетами (автозагрузка). | Все типы юнитов. |

### Правила именования и экранирования

Если имя юнита основано на пути в файловой системе (например, `.mount` или `.path`), systemd использует алгоритм экранирования:
*   Ведущий и конечный слэши удаляются.
*   Остальные слэши заменяются на дефисы (`-`).
*   Спецсимволы заменяются на их шестнадцатеричные коды.
*   Утилита для работы с именами: `systemd-escape "/mnt/data share"` → `mnt-data\x20share`.
*   Для обратного преобразования используется `systemd-unescape`.

> **Практический нюанс:** При создании `.mount` юнитов для путей с пробелами всегда проверяйте экранированное имя через `systemctl list-unit-files | grep mount`. Если имя не совпадает — юнит не загрузится.

---

## Секция [Unit]: Метаданные и условия

### Логика зависимостей

*   **`After=` / `Before=`**: Порядок запуска. Не создает жесткой зависимости (если один упал, другой все равно может запуститься).
*   **`Requires=`**: Жесткая зависимость. Если зависимый юнит падает, текущий юнит также останавливается.
*   **`Wants=`**: Мягкая зависимость. Попытка запустить указанный юнит, но его неудача не блокирует текущий.
*   **`Requisite=`**: Проверочная зависимость. Если указанный юнит не активен — текущий не запускается, но не пытается активировать зависимый.
*   **`BindsTo=`**: Жесткая связь жизненных циклов. Если зависимый юнит исчезает (например, устройство извлечено), текущий мгновенно останавливается.
*   **`PartOf=`**: Групповая связь. Остановка/рестарт родителя повлечет те же действия для ребенка.

> **SRE-практика:** Всегда комбинируйте `After=` с `Requires=` или `Wants=`. Без `After=` оба юнита стартуют параллельно, что приводит к ошибкам, если основной обращается к еще не готовой зависимости.

### Условия (Conditions) и Проверки (Assertions)

Директивы `Condition...` позволяют пропустить запуск без ошибки, если условие не выполнено. `Assert...` — прерывают запуск с критической ошибкой.

| Директива | Назначение |
| :--- | :--- |
| `ConditionPathExists=` | Проверка наличия файла или директории. Префикс `!` инвертирует условие. |
| `ConditionDirectoryNotEmpty=` | Проверка, что директория содержит файлы. |
| `ConditionCredential=` | (v250+) Наличие секрета (Credential) в системе. |
| `ConditionVirtualization=` | Проверка типа контейнера или гипервизора. |
| `ConditionEnvironment=` | Наличие переменной окружения. |
| `ConditionSecurity=` | Проверка наличия security-фичи (например, `ConditionSecurity=selinux`). |
| `ConditionACPower=` | Проверка, что система работает от сети, а не от батареи. |
| `ConditionKernelCommandLine=` | Проверка параметра ядра в командной строке загрузчика. |
| `AssertPathExists=` | Аналог `ConditionPathExists=`, но при невыполнении — критическая ошибка (failed). |
| `AssertVirtualization=` | Аналог `ConditionVirtualization=`, но с отказом при несоответствии. |

> **Практический пример:** Для сервиса, работающего только на bare-metal, используйте `AssertVirtualization=!container`. Это предотвратит запуск в Docker/Podman с понятной ошибкой в логах.

---

## Секция [Service]: Жизненный цикл и безопасность

### Порядок выполнения команд

1.  **`ExecCondition=`**: (v243+) Команда-фильтр. Если вернет не 0, юнит считается пропущенным (не ошибка).
2.  **`ExecStartPre=`**: Подготовка (например, `mkdir -p /run/app`). Сбой прерывает запуск.
3.  **`ExecStart=`**: Основной процесс. Несколько команд допустимы только для `Type=oneshot`.
4.  **`ExecStartPost=`**: Действия после успешного запуска. Сбой не влияет на статус сервиса.
5.  **`ExecReload=`**: Перезагрузка конфигурации (вызывается через `systemctl reload`).
6.  **`ExecStop=`**: Команда для корректного завершения (Graceful Shutdown).
7.  **`ExecStopPost=`**: Очистка ресурсов после остановки (выполняется всегда, даже при сбое `ExecStop=`).

### Типы сервисов

Директива `Type=` определяет алгоритм запуска и момент готовности. Подробный разбор каждого типа, критериев готовности и связанных директив — в [Типы сервисов systemd](./systemd_service_types.md).

### Политики перезапуска

| Директива | Описание |
| :--- | :--- |
| **`Restart=`** | `no` (по умолчанию), `on-success`, `on-failure`, `on-abnormal`, `on-watchdog`, `always`. |
| **`RestartSec=`** | Задержка перед перезапуском. По умолчанию 0.1s. |
| **`StartLimitIntervalSec=`** | Временное окно для подсчета сбоев. По умолчанию 10s. |
| **`StartLimitBurst=`** | Максимум перезапусков в окне `StartLimitIntervalSec=`. По умолчанию 5. |

При превышении лимита юнит переходит в `failed` и не запускается до `systemctl reset-failed` или истечения интервала.

> **SRE-практика:** Комбинируйте `Restart=on-failure` с `StartLimitIntervalSec=300` и `StartLimitBurst=3`. Это предотвращает бесконечный цикл перезапусков при деградации кода и потреблении CPU.

### Окружение и рабочие каталоги

| Директива | Описание |
| :--- | :--- |
| **`Environment=`** | Переменные окружения inline (`KEY=VALUE`). |
| **`EnvironmentFile=`** | Путь к файлу с переменными (стандартный формат `KEY=VALUE`). Префикс `-` подавляет ошибку, если файл отсутствует. |
| **`WorkingDirectory=`** | Рабочая директория для `ExecStart=`. По умолчанию корень `/`. |
| **`UMask=`** | Маска создания файлов. По умолчанию `0022` (0644/0755). |
| **`SupplementaryGroups=`** | Дополнительные группы для процесса (например, `docker`, `adm` для доступа к логам). |

### Стандартные потоки и логирование

| Директива | Описание |
| :--- | :--- |
| **`StandardOutput=`** | Куда направлять stdout. `journal` (по умолчанию), `syslog`, `kmsg`, `file:/path/to/file`, `null`. |
| **`StandardError=`** | Куда направлять stderr. Те же значения, что и `StandardOutput=`. |
| **`StandardInput=`** | Откуда читать stdin. `null` (по умолчанию), `tty`, `socket`. |
| **`SyslogIdentifier=`** | Идентификатор для журнала (по умолчанию имя сервиса). Полезно, если `ExecStart=` вызывает скрипт, который пишет в journal под своим именем. |

### Ресурсы и лимиты

| Директива | Описание |
| :--- | :--- |
| **`CPUQuota=`** | Ограничение CPU в процентах (`50%` = половина ядра). |
| **`CPUWeight=`** | Вес для fair scheduling. По умолчанию 100. |
| **`MemoryMax=`** | Жесткий лимит памяти (cgroup v2). |
| **`MemoryHigh=`** | Мягкий лимит — при превышении происходит throttling. |
| **`TasksMax=`** | Максимум задач (потоков/процессов) в cgroup. |
| **`IOWeight=`** | Вес для планировщика I/O. |
| **`IOReadBandwidthMax=`** | Лимит чтения на устройство (`/dev/sda 1M`). |
| **`IOWriteBandwidthMax=`** | Лимит записи на устройство. |

### Песочница и изоляция

Краткий обзор ключевых директив. Полный контрольный список и настройки — в [Практические сценарии systemd](./systemd_practical_scenarios.md).

| Директива | Описание |
| :--- | :--- |
| **`ProtectSystem=`** | `full` (read-only `/etc`, `/usr`), `strict` (read-only вся ФС кроме `/dev`, `/proc`, `/sys`). |
| **`ProtectHome=`** | `read-only`, `tmpfs` (пустой tmpfs в `/home`), `yes` (полная защита). |
| **`PrivateTmp=`** | Изолированный `/tmp` и `/var/tmp` для сервиса. |
| **`PrivateDevices=`** | Доступ только к `/dev/null`, `/dev/zero`, `/dev/random`, `/dev/urandom`. |
| **`ProtectKernelTunables=`** | Монтирует `/proc/sys`, `/sys` как read-only. |
| **`ProtectKernelModules=`** | Запрещает загрузку/выгрузку модулей ядра. |
| **`ProtectControlGroups=`** | Запрещает запись в cgroup. |
| **`RestrictAddressFamilies=`** | Ограничение семейств адресов (`AF_INET`, `AF_INET6`, `AF_UNIX`, `AF_NETLINK`). |
| **`RestrictNamespaces=`** | Запрет создания новых namespaces. |
| **`RestrictSUIDSGID=`** | Запрет создания SUID/SGID файлов. |
| **`NoNewPrivileges=`** | Запрет получения новых привилегий (например, через SUID). |
| **`MemoryDenyWriteExecute=`** | Запрет создания исполняемой памяти (защита от эксплойтов). |
| **`SystemCallArchitectures=`** | Ограничение архитектуры syscall (обычно `native`). |

### Завершение работы и сигналы

| Директива | Описание |
| :--- | :--- |
| **`KillMode=`** | `control-group` (по умолчанию — убить все в cgroup), `main` (только главный процесс), `mixed` (SIGTERM главному, SIGKILL остальным), `none`. |
| **`KillSignal=`** | Сигнал для graceful shutdown. По умолчанию `SIGTERM`. |
| **`SendSIGKILL=`** | Отправлять ли `SIGKILL` после таймаута. По умолчанию `yes`. |
| **`TimeoutStopSec=`** | Таймаут ожидания graceful shutdown. По умолчанию `DefaultTimeoutStopSec=90s`. |
| **`ExecStop=`** | Команда graceful shutdown. Если не указана — отправка `KillSignal=`. |
| **`ExecStopPost=`** | Очистка после остановки (выполняется всегда). |

### Дополнительные директивы

| Директива | Описание |
| :--- | :--- |
| **`User=` / `Group=`** | Пользователь и группа для запуска процесса. |
| **`DynamicUser=`** | (v236+) Создавать временного пользователя при старте, удалять при остановке. |
| **`SupplementaryGroups=`** | Дополнительные группы для доступа к ресурсам (например, `docker`, `disk`). |
| **`WorkingDirectory=`** | Рабочая директория процесса. |
| **`ExecSearchPath=`** | (v250+) Пути поиска исполняемых файлов (аналог `$PATH`). |
| **`ExitType=`** | `cgroup` — считать сервис остановленным после завершения всех процессов в cgroup. |

---

## Секция [Socket]: Сетевые сокеты и IPC

### Назначение и активация

Socket activation позволяет `systemd` создать сокет до запуска сервиса. Сервис активируется только при поступлении первого подключения, что экономит ресурсы на простаивающих хостах.

| Директива | Описание |
| :--- | :--- |
| **`ListenStream=`** | TCP-сокет (например, `80`, `443`, `/run/app.sock`). |
| **`ListenDatagram=`** | UDP-сокет. |
| **`ListenSequentialPacket=`** | Unix-sequenced packet сокет. |
| **`Accept=`** | `yes` — `systemd` запускает экземпляр сервиса на каждое подключение. `no` (по умолчанию) — один сервис на все подключения. |
| **`Service=`** | Имя сервиса, который активируется сокетом (если отличается от базового имени). |

### Пример структуры

```ini
[Unit]
Description=TCP port 8080 socket

[Socket]
ListenStream=8080
Accept=no

[Install]
WantedBy=sockets.target
```

Связанный сервис должен иметь `Type=simple` (по умолчанию) или `Type=notify`, если приложение поддерживает `sd_notify`.

---

## Секция [Install]: Связывание

Определяет, что произойдет при выполнении `systemctl enable`.

*   **`WantedBy=`**: Создает символическую ссылку в директории `.wants/` указанного юнита (обычно `multi-user.target`). Слабая связь.
*   **`RequiredBy=`**: Создает символическую ссылку в `.requires/` указанного юнита. Сильная связь.
*   **`Alias=`**: Альтернативное имя юнита.
*   **`Also=`**: Список юнитов, которые нужно включить/выключить вместе с текущим.
*   **`DefaultInstance=`**: Для шаблонов — экземпляр по умолчанию, если он не указан при включении.

> **Важно:** Юниты без секции `[Install]` (например, `Type=oneshot` с `RemainAfterExit=yes`) считаются статическими. Их нельзя включить через `systemctl enable`, но они активируются через зависимости.

---

## Спецификаторы (Specifiers)

Спецификаторы позволяют делать юнит-файлы универсальными, особенно в шаблонах.

| Код | Значение | Пример (для `app@admin.service`) |
| :--- | :--- | :--- |
| **`%n`** | Полное имя юнита | `app@admin.service` |
| **`%p`** | Имя (префикс до `@`) | `app` |
| **`%i`** | Имя экземпляра (после `@`) | `admin` |
| **`%u`** | Имя пользователя службы | `root` (или значение `User=`) |
| **`%h`** | Домашняя директория пользователя | `/home/admin` |
| **`%f`** | Раскрытый путь (из экранированного) | Если `%i` был `mnt-data`, `%f` вернет `/mnt/data` |
| **`%t`** | Директория рантайма пользователя | `/run/user/1000` |
| **`%S`** | Директория состояния | `/var/lib` |
| **`%C`** | Кэш-директория | `/var/cache` |
| **`%m`** | Machine ID | `/etc/machine-id` содержимое |

---

## Практические сценарии

### Использование шаблонов (OpenVPN)

Файл `/etc/systemd/system/ovpn@.service` позволяет запускать конфигурации одной командой:
```bash
sudo systemctl start ovpn@client-office.service
# Внутри юнита %i будет заменено на 'client-office'
```

Параметр `%i` подставляется из имени экземпляра. Для именования используйте только латинские буквы, цифры, дефисы и подчеркивания.

### Drop-in переопределения

Для изменения `RestartSec` в Nginx без правки основного файла:
```bash
sudo systemctl edit nginx.service
```
Создаст `/etc/systemd/system/nginx.service.d/override.conf`:
```ini
[Service]
RestartSec=10s
```

> **SRE-практика:** Никогда не редактируйте unit-файлы из пакетов напрямую. Всегда используйте drop-in (`systemctl edit` или файлы в `.d/`). При обновлении пакета ваши изменения не будут затерты.

### Валидация и диагностика unit-файлов

```bash
# Проверка синтаксиса конкретного юнита
systemd-analyze verify /etc/systemd/system/myapp.service

# Оценка безопасности (Exposure score)
systemd-analyze security myapp.service

# Просмотр реальной конфигурации с учетом drop-ins
systemctl cat myapp.service

# Поиск локальных изменений относительно пакетов
systemd-delta --type=modified

# Дерево зависимостей для визуализации связей
systemctl list-dependencies --all myapp.service
```

### Полный пример production-сервиса

```ini
[Unit]
Description=My Application
After=network-online.target
Wants=network-online.target
ConditionPathExists=/etc/myapp/config.yaml

[Service]
Type=exec
User=app
Group=app
SupplementaryGroups=app-data
WorkingDirectory=/opt/myapp
EnvironmentFile=/etc/myapp/env
UMask=0027

ExecStart=/usr/bin/myapp --config /etc/myapp/config.yaml
ExecStartPost=/usr/local/bin/register-in-consul.sh
ExecStop=/usr/bin/myapp --shutdown
ExecStopPost=/usr/bin/cleanup-tmp.sh

Restart=on-failure
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=3

StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp

CPUQuota=50%
MemoryMax=512M
TasksMax=256

ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=/var/lib/myapp /var/log/myapp
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
SystemCallArchitectures=native
RestrictSUIDSGID=yes
NoNewPrivileges=yes

KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

---

## Дополнительная информация

### Иерархия путей

1.  `/etc/systemd/system/` — Локальные настройки (высший приоритет).
2.  `/run/systemd/system/` — Рантайм-юниты (созданные динамически).
3.  `/usr/lib/systemd/system/` — Юниты от пакетов (низший приоритет).

Для просмотра всех путей поиска:
```bash
systemd-analyze unit-paths
```

### Диагностика

Подробно о поиске реальной конфигурации, drop-in переопределениях и управлении сервисами: [Управление службами (systemctl)](./service_management.md).

### См. также
* [Обзор юнитов systemd](./systemd_units_overview.md) — классификация и жизненный цикл.
* [Типы сервисов systemd](./systemd_service_types.md) — детальный разбор параметра `Type=`.
* [Практические сценарии systemd](./systemd_practical_scenarios.md) — песочница, отладка и эксплуатация.

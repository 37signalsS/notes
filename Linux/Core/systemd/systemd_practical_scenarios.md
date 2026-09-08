# Практические сценарии и паттерны systemd

## Определения

* **Паттерны активации** — типовые архитектурные решения по управлению жизненным циклом служб в зависимости от внешних событий (сеть, файловая система, оборудование).
* **Sandboxing (Песочница)** — применение декларативных директив изоляции в секции `[Service]` для минимизации привилегий и ограничения поверхности атаки.
* **Transient Unit (Временный юнит)** — динамически создаваемый объект (через API или `systemd-run`), существующий только до завершения задачи или перезагрузки. Подробнее: [systemd-run](./systemd_run.md).
* **Credentials (Секреты)** — механизм безопасной передачи конфиденциальных данных (паролей, ключей) в юнит без их жесткого прописывания в файлах конфигурации.

## Основные концепции

### Иерархия управления ресурсами

В практических сценариях важно учитывать, как юниты группируются для управления ресурсами:
1.  **Service**: Индивидуальный процесс.
2.  **Slice**: Логическая группа сервисов (например, `background.slice` для задач с низким приоритетом CPU).
3.  **Target**: Точка синхронизации состояния системы.

### Приоритет декларативности

Всегда отдавайте предпочтение нативным директивам systemd перед сложными shell-скриптами в `ExecStartPre`. Например, проверку наличия файла лучше делать через `ConditionPathExists=`, а не через `test -f`.

---

## Практические сценарии

### 1. Событийная активация (Event-Driven)

#### Паттерн: Socket Activation (Ленивый запуск)
Служба запускается только при поступлении первого сетевого пакета.

**Файл `api.socket`**:
```ini
[Socket]
ListenStream=8080
# Ограничение количества одновременных соединений
MaxConnections=64

[Install]
WantedBy=sockets.target
```

**Файл `api.service`**:
```ini
[Service]
ExecStart=/usr/local/bin/api-server
# Служба остановится, если к ней нет обращений
StopWhenUnneeded=yes
```

#### Паттерн: Path Activation (Мониторинг директории)
Автоматическая обработка файлов при их появлении.

**Файл `processor.path`**:
```ini
[Path]
# Активация только если директория не пуста
PathExistsGlob=/var/spool/incoming/*.csv
Unit=processor.service
```

### 2. Изоляция и безопасность (Sandboxing)

«Золотой стандарт» hardening-настроек для публичного веб-сервиса. Эти параметры создают изолированные пространства имен и ограничивают доступ к ядру.

```ini
[Service]
ExecStart=/usr/bin/webapp
# Ограничение прав
User=webapp
Group=webapp
NoNewPrivileges=yes

# Изоляция ФС
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadOnlyPaths=/etc/webapp/config.json
ReadWritePaths=/var/log/webapp/

# Изоляция ядра и оборудования
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryDenyWriteExecute=yes
```

### 3. Управление секретами (Credentials)

Безопасная передача токенов (v250+).

**Создание секрета**:
```bash
# Сохранение зашифрованного секрета в системе
systemd-creds encrypt --name=db-password - /etc/creds/db.key < password.txt
```

**Использование в юните**:
```ini
[Service]
LoadCredential=db-pass:/etc/creds/db.key
ExecStart=/usr/bin/app --db-pass-file=${CREDENTIALS_DIRECTORY}/db-pass
```

### 4. Обработка зависимостей и условий

#### Паттерн: Ожидание полной готовности сети
Используйте `network-online.target`, а не просто `network.target`.

```ini
[Unit]
Description=Data Sync Service
Wants=network-online.target
After=network-online.target

[Service]
# Проверка условия перед запуском
ConditionPathExists=/etc/sync/token.json
ConditionEnvironment=STAGING=production
ExecStart=/usr/bin/sync-tool
```

### 5. Управление дисками (Mount)

Для детальной настройки монтирования используйте специализированный гайд. В общем виде:
*   **`.mount`**: Заменяет `fstab` для сложных цепочек (например, монтирование тольк после запуска VPN).
*   **`.automount`**: Позволяет системе загружаться быстрее, монтируя диски только при обращении к ним.

Подробнее: [Юниты монтирования systemd](../../FileSystems/mounting/scenarios/systemd_mount.md)

### 6. Временные задачи (Ad-hoc)

#### systemd-run (v250+)
Запуск разового скрипта с жесткими лимитами ресурсов без создания файлов.

```bash
systemd-run --unit=one-time-job \
            --property=MemoryMax=512M \
            --property=CPUQuota=30% \
            --property=PrivateTmp=yes \
            /usr/local/bin/batch-process.sh
```

#### run0 (v256+)
Безопасное выполнение команды от имени другого пользователя через API systemd (замена `sudo`).

```bash
run0 --user=www-data ls /var/www/html
```

### 7. Управление перезапусками и устойчивостью (Failure Handling)

Для SRE-сценариев критически важно настраивать политику перезапуска и ограничения, чтобы служба восстанавливалась после сбоев, но не создавала бесконечных циклов при программных ошибках.

```ini
[Unit]
Description=Critical API Service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=exec
ExecStart=/usr/local/bin/api-server
Restart=on-failure
RestartSec=10
TimeoutStartSec=30
TimeoutStopSec=30
```

Политики `Restart=`:
- `on-failure` — при ненулевом коде завершения (рекомендуется по умолчанию).
- `always` — при любом завершении, включая `systemctl stop` (используйте для критических агентов мониторинга).
- `on-abnormal` — при сигналах или таймаутах.
- `on-watchdog` — при срабатывании watchdog.
- `on-success` — при успешном завершении (редко используется).

> **SRE-практика:** Комбинируйте `Restart=on-failure` с `StartLimitIntervalSec=`/`StartLimitBurst=`, чтобы при деградации кода служба не потребляла CPU в бесконечном цикле перезапусков.

### 8. Окружение и рабочие каталоги

```ini
[Service]
Type=simple
ExecStart=/usr/local/bin/app
WorkingDirectory=/opt/app/current
UMask=0027

EnvironmentFile=/etc/app/env
Environment="DEBUG=false"
Environment="LOG_LEVEL=info"

SupplementaryGroups=docker staff
```

- `WorkingDirectory=` — задает каталог для относительных путей.
- `UMask=` — маска создания файлов по умолчанию.
- `EnvironmentFile=` — файл формата `KEY=VALUE` (комментарии `#`, пустые строки).
- `SupplementaryGroups=` — дополнительные группы для доступа к ресурсам (разделы, сокеты).

### 9. Логирование и стандартные потоки

```ini
[Service]
Type=simple
ExecStart=/usr/local/bin/app
StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp
```

Варианты `StandardOutput=` / `StandardError=`:
- `journal` — направление в `journald` (по умолчанию).
- `journal+console` — дублирование в консоль (полезно для early-boot).
- `file:/var/log/app.log` — прямое перенаправление в файл (обходит journald).
- `null` — подавление вывода.

`SyslogIdentifier=` задает идентификатор в journald для фильтрации: `journalctl -u myapp`.

### 10. Graceful shutdown и обработка сигналов

```ini
[Service]
Type=simple
ExecStart=/usr/local/bin/web-app
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30
ExecStop=/usr/local/bin/drain-connections.sh
ExecStopPost=/usr/local/bin/cleanup.sh
```

Режимы `KillMode=`:
- `control-group` (по умолчанию) — убивает все процессы в cgroup.
- `main` — только главный процесс.
- `mixed` — главный процесс получает `SIGTERM`, остальные — `SIGKILL` (рекомендуется для приложений с пулом воркеров).
- `none` — systemd не убивает процессы.

`ExecStop=` выполняется перед сигналом. `ExecStopPost=` — после завершения всех процессов, независимо от успеха остановки.

### 11. Шаблонные экземпляры (Template Units)

Шаблонный юнит с `@` позволяет запускать несколько экземпляров одной конфигурации:

```ini
# /etc/systemd/system/vpn@.service
[Unit]
Description=VPN Tunnel for %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/wg-quick up wg%i
ExecStop=/usr/bin/wg-quick down wg%i
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now vpn@office.service
systemctl enable --now vpn@home.service
```

Параметр `%i` подставляется из имени экземпляра. Для именования используйте только латинские буквы, цифры, дефисы и подчеркивания.

### 12. Ограничение частоты запуска (Rate Limiting)

```ini
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Restart=on-failure
RestartSec=5
```

При превышении лимита юнит переходит в состояние `failed` и не запускается до `systemctl reset-failed` или истечения интервала.

### 13. Системный контрольный список песочницы (Sandboxing Checklist)

Для production-сервисов применяйте слои изоляции по принципу «минимальных привилегий»:

```ini
[Service]
User=app
Group=app
NoNewPrivileges=yes
SupplementaryGroups=app-data

ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=/var/lib/app /var/log/app

PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
SystemCallArchitectures=native

RestrictSUIDSGID=yes
MemoryDenyWriteExecute=yes
PrivateNetwork=no
```

### 14. Практические приемы мониторинга и устранения неисправностей

```bash
# Быстрая проверка состояния
systemctl status --full myapp.service
journalctl -u myapp.service -n 50 --no-pager

# Детальный статус через D-Bus
systemctl show myapp.service -p Result,ExecMainStatus,SubState,MainPID

# Анализ критической цепи
systemd-analyze critical-chain myapp.service

# Проверка синтаксиса и безопасности
systemd-analyze verify /etc/systemd/system/myapp.service
systemd-analyze security myapp.service

# Поиск локальных изменений
systemd-delta --type=modified
```

### 15. Очистка и обслуживание

```bash
# Сброс счетчика сбоев
systemctl reset-failed myapp.service

# Очистка journal
journalctl --vacuum-size=500M
journalctl --vacuum-time=7d

# Перезагрузка конфигурации
sudo systemctl daemon-reload
sudo systemctl restart myapp.service

# Список failed-юнитов
systemctl list-units --type=service --state=failed
```

---

## Дополнительная информация

### Диагностика сценариев

```bash
# Показать дерево зависимостей для визуализации связей
systemctl list-dependencies --all my-app.service

# Анализ безопасности юнита (рейтинг Exposure)
systemd-analyze security my-app.service

# Проверка корректности синтаксиса
systemd-analyze verify /etc/systemd/system/my-app.service
```

### См. также
* [Обзор юнитов systemd](./systemd_units_overview.md) — классификация и состояния.
* [Таймеры systemd](./timers.md) — планирование задач.
* [Пользовательские службы](./user_services.md) — сценарии в контексте `--user`.

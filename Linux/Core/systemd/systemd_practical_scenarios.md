# Практические сценарии и паттерны systemd

## Определения

* **Паттерны активации** — типовые архитектурные решения по управлению жизненным циклом служб в зависимости от внешних событий (сеть, файловая система, оборудование).
* **Sandboxing (Песочница)** — применение декларативных директив изоляции в секции `[Service]` для минимизации привилегий и ограничения поверхности атаки.
* **Transient Unit (Временный юнит)** — динамически создаваемый объект (через API или `systemd-run`), существующий только до завершения задачи или перезагрузки.
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
Description=Cloud Sync Service
Wants=network-online.target
After=network-online.target

[Service]
# Проверка условия перед запуском
ConditionPathExists=/etc/cloud-sync/token.json
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
* [Управление сессиями (logind)](./logind_session_management.md) — ингибиторы и лимиты.
* [Таймеры systemd](./timers.md) — планирование задач.
* [Пользовательские службы](./user_services.md) — сценарии в контексте `--user`.

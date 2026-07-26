# Практические сценарии systemd

## Определения

* **Практические сценарии systemd** — это типовые конфигурации для решения задач администрирования: от автоматизации монтирования до создания изолированных цепочек сервисов.
* **Связка юнитов (Unit coupling)** — использование нескольких типов юнитов (например, `.socket` + `.service` или `.path` + `.service`) для реализации сложной логики активации.
* **Песочница (Sandboxing)** — применение директив изоляции внутри сценариев для ограничения доступа сервисов к системным ресурсам.

## Основные концепции

### Правила именования юнитов монтирования

Для юнитов типов `.mount` и `.automount` имя файла **обязано** точно соответствовать пути к точке монтирования. Слэши (`/`) заменяются на дефисы (`-`), ведущий слэш игнорируется.

| Путь | Имя юнит-файла |
| :--- | :--- |
| `/backup` | `backup.mount` |
| `/mnt/data/share` | `mnt-data-share.mount` |

### Типовые паттерны активации

1. **Lazy Start (Ленивый запуск)** — сервис спит, пока не придет сетевой запрос (Socket) или не появится файл (Path).
2. **Event-driven (Событийный запуск)** — активация по таймеру или при наступлении системного события (например, подключение USB).
3. **Target Grouping (Группировка)** — объединение микросервисов под единый `.target` для массового управления.

## Практические сценарии

### 1. Управление дисками (Mount и Automount)

Используется для управления ФС декларативно, заменяя `/etc/fstab`.

**Юнит монтирования** (`mnt-storage.mount`):
```ini
[Unit]
Description=Mount External Storage
After=network.target

[Mount]
What=/dev/sdb1
Where=/mnt/storage
Type=ext4
Options=defaults,noatime
```

**Юнит автомонтирования** (`mnt-storage.automount`):
Активирует диск только при первом обращении к `/mnt/storage`.
```ini
[Automount]
Where=/mnt/storage
TimeoutIdleSec=300
```

### 2. Мониторинг файлов (Path)

Автоматический запуск скрипта обработки при появлении новых файлов в директории.

**Юнит пути** (`image-processor.path`):
```ini
[Path]
PathChanged=/var/spool/uploads/
Unit=image-processor.service
```

**Сервис** (`image-processor.service`):
```ini
[Service]
Type=oneshot
ExecStart=/usr/local/bin/process-images.sh
```

### 3. Активация по сети (Socket)

Экономия ресурсов: приложение запускается только при первом обращении к порту.

**Юнит сокета** (`myapp.socket`):
```ini
[Socket]
ListenStream=8080
```

**Сервис** (`myapp.service`):
```ini
[Service]
ExecStart=/usr/bin/myapp
# Остановка при отсутствии активности
StopWhenUnneeded=yes
```

### 4. Создание пользовательского стека (Target)

Позволяет управлять группой сервисов как единым целым.

**Юнит таргета** (`my-project.target`):
```ini
[Unit]
Description=My Project Stack
AllowIsolate=yes
```

**Привязка сервиса** (в файле `app.service`):
```ini
[Unit]
PartOf=my-project.target

[Install]
WantedBy=my-project.target
```

```bash
# Массовый запуск всего стека
sudo systemctl start my-project.target
```

### 5. Безопасный запуск временных задач (systemd-run)

Запуск тяжелого бэкапа с ограничением ресурсов без создания файлов.

```bash
systemd-run --unit=backup-task \
            --property=MemoryMax=1G \
            --property=CPUQuota=20% \
            --property=PrivateTmp=yes \
            /usr/local/bin/heavy-backup.sh
# → Running as unit: backup-task.service
```

## Дополнительная информация

### Диагностика сценариев

```bash
# Проверка дерева зависимостей для таргета
systemctl list-dependencies my-project.target
# → my-project.target
# → ├─app.service
# → └─db.service

# Поиск ошибок в связках (например, .path без .service)
systemd-analyze verify /etc/systemd/system/*.path
```

### См. также
* [Обзор юнитов systemd](./systemd_units_overview.md) — типы и назначение.
* [Управление зависимостями](./systemd_dependencies.md) — логика связей.
* [Таймеры systemd](./timers.md) — сценарии запуска по времени.

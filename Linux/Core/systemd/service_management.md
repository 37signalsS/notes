# Управление службами через systemctl

## Определения

* **Служба (Service)**: В экосистеме `systemd` это процесс или группа процессов, жизненным циклом которых управляет система инициализации. Каждая служба описывается в текстовом конфигурационном файле — **юнит-файле** (например, `nginx.service`).
* **`systemctl`**: Центральная утилита командной строки (CLI (Command Line Interface)) для взаимодействия с менеджером `systemd`. Она позволяет изменять состояние системы, управлять службами, анализировать их статус и настраивать параметры автозагрузки в ОС (Операционная Система).

## Основные концепции

### Управление состоянием юнита

Базовые команды для изменения текущего состояния службы в режиме реального времени.

```bash
# Запуск службы
sudo systemctl start nginx.service
# → запуск основного процесса и зависимостей

# Остановка службы
sudo systemctl stop nginx.service
# → отправка SIGTERM (Signal Terminate) процессам юнита

# Перезапуск службы
sudo systemctl restart nginx.service
# → полная остановка и новый запуск (приводит к кратковременному простою)

# Перечитывание конфигурации приложения
sudo systemctl reload nginx.service
# → запрос к приложению перечитать конфиг без остановки процесса
```

### Анализ статуса и метаданных

Команда `status` предоставляет детальную информацию о работе юнита.

```bash
systemctl status nginx.service
# → ● nginx.service - A high performance web server and a reverse proxy server
# →    Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Sat 2024-06-08 10:00:00 MSK; 1h ago
# →      Main PID: 1234 (nginx)
# →     Tasks: 2 (limit: 4915)
# →    Memory: 45.2M
# →    CPU: 1.2s
# →    CGroup: /system.slice/nginx.service
```

**Ключевые поля статуса:**

* **`Loaded`**: Путь к файлу на диске и статус автозагрузки.
* **`Active`**: Текущее состояние (например, `active (running)`, `failed`, `inactive (dead)`).
* **`Main PID`**: Идентификатор основного процесса (Process ID).
* **`CGroup`**: Контрольная группа (Control Group), через которую `systemd` изолирует процессы и ограничивает ресурсы (CPU (Central Processing Unit), RAM (Random Access Memory), I/O (Input/Output)).

### Управление автозагрузкой и блокировка

Настройка поведения службы при старте системы.

| Команда | Описание |
| :--- | :--- |
| `systemctl enable <unit>` | Включить автозапуск (создание симлинков в `.wants/`). |
| `systemctl disable <unit>` | Отключить автозапуск (удаление симлинков). |
| `systemctl enable --now <unit>` | Включить и запустить немедленно. |
| `systemctl mask <unit>` | Полная блокировка (привязка юнита к `/dev/null`). |
| `systemctl unmask <unit>` | Снятие блокировки. |

## Практические сценарии

### Анализ состава системы

```bash
# Показать все активные юниты
systemctl list-units
# → вывод списка запущенных служб, сокетов и таргетов

# Показать только упавшие юниты
systemctl --failed
# → UNIT            LOAD   ACTIVE SUB    DESCRIPTION
# → app.service     loaded failed failed My Custom Application

# Показать зависимости службы
systemctl list-dependencies nginx.service
# → nginx.service
# → ├─system.slice
# → └─network.target
```

### Редактирование и переопределение (Overrides)

Для изменения параметров службы без редактирования файлов в `/usr/lib/` (которые затираются при обновлении пакетов) используется механизм **drop-in** файлов через `systemctl edit`.

```bash
# Создание или редактирование переопределений
sudo systemctl edit nginx.service
```

Это создаст файл в `/etc/systemd/system/nginx.service.d/override.conf`.

**Пример изменения лимитов памяти:**

```ini
[Service]
MemoryMax=500M
```

**Важное правило для списков:** Если вы переопределяете директиву, которая может встречаться несколько раз (например, `ExecStart`), её нужно сначала очистить:

```ini
[Service]
ExecStart=
ExecStart=/usr/sbin/nginx -g 'daemon off;'
```

### Валидация и применение изменений

#### Что на самом деле делает `daemon-reload`

`systemctl daemon-reload` не просто "перечитывает конфиги" — systemd полностью пересобирает своё внутреннее представление о юнитах: перечитываются все unit-файлы и drop-in-конфигурации, пересчитываются зависимости, обновляется внутренний граф сервисов. Запущенные процессы при этом **не перезапускаются**.

#### Проверка применения изменений

После `daemon-reload` полезно убедиться, что systemd действительно увидел изменения:

```bash
# Просмотр итоговой конфигурации юнита с учётом всех override-файлов
systemctl cat nginx.service

# Просмотр зависимостей, построенных systemd после перезагрузки
systemctl list-dependencies nginx.service

# Сводка всех расхождений между текущими и штатными unit-файлами
systemd-delta
```

#### Частая ошибка

`daemon-reload` не перезапускает сервисы. Если изменить `ExecStart`, переменные окружения, лимиты (`LimitNOFILE`), `User` или другие параметры запуска — работающий процесс продолжит использовать старые настройки. Новые параметры начнут действовать только после:

```bash
sudo systemctl restart <service>
```

Именно поэтому после изменения unit-файла почти всегда выполняют две команды подряд:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx.service
```

#### Команды для проверки и отката

```bash
# Проверить синтаксис конкретного файла
systemd-analyze verify /etc/systemd/system/my-service.service
# → вывод ошибок, если конфигурация некорректна

# Откатить все ручные переопределения юнита
sudo systemctl revert nginx.service
```

## Дополнительная информация

### Мониторинг журналов

Все службы `systemd` автоматически направляют вывод в системный журнал. Управление логами осуществляется через `journalctl`.

* [Journald: централизованное логирование](../../SystemAdministration/Logging/journald.md)
* **Команда**: `journalctl -u nginx.service -f` (просмотр логов в реальном времени).

### См. также

* [Юниты, таргеты и зависимости systemd](./systemd_units_overview.md) — классификация и типы юнитов.
* [Структура unit-файла](./systemd_unit_file_structure.md) — синтаксис и секции файлов конфигурации.
* [Типы сервисов systemd](./systemd_service_types.md) — подробнее о директиве `Type=`.
* [Утилита witr](../../Diagnostics/Processes/witr.md) — комплексная диагностика причин запуска процессов.

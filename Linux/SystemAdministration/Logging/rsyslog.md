# rsyslog: Фильтрация и пересылка логов

## Определения

**`rsyslog`** (Rocket-fast System for Log Processing) — высокопроизводительная служба для сбора, обработки и пересылки системных журналов. В современных Linux основная роль — получать логи от `systemd-journald`, фильтровать и перенаправлять в места назначения (текстовые файлы в `/var/log`, удаленные серверы).

**Ключевое применение:** построение систем [централизованного логирования](../../../Concepts/Observability_and_Monitoring/observability_definitions.md). Взаимодействие с [journald](./journald.md) и [journalctl](../../Diagnostics/journalctl.md) описано в соответствующих файлах. Общий обзор — в [обзоре логирования](./logging_overview.md).

## Базовые концепции

### Архитектура и модули

| Тип модуля | Префикс | Назначение | Примеры |
| :--- | :--- | :--- | :--- |
| **Input** | `im` | Сбор логов | `imjournal`, `imudp`, `imtcp`, `imfile` |
| **Output** | `om` | Отправка логов | `omfile`, `omfwd`, `omelasticsearch` |
| **Filter** | `fm` | Фильтрация | `fmhash`, `fmlookup` |
| **Parser** | `pm` | Парсинг сообщений | `pmrfc5424`, `pmrfc3164` |

### Конфигурация и фильтрация

**Файлы конфигурации:**

- Главный: `/etc/rsyslog.conf`
- Дополнительные: `/etc/rsyslog.d/*.conf`

**Структура правила:** `источник.приоритет   действие`

| Компонент | Описание | Примеры |
| :--- | :--- | :--- |
| **Facility (источник)** | Категория сообщения | `auth`, `authpriv`, `cron`, `kern`, `mail`, `local0-7` |
| **Priority (уровень)** | Уровень важности | `info`, `warning`, `err`, `crit`, `*` (любой) |
| **Action (действие)** | Куда отправить | `/var/log/file`, `@server:514`, `@@server:514` |

**Специальные facility:**

- `local0` – `local7` — для кастомных приложений
- `auth`, `authpriv` — аутентификация (SSH, sudo)
- `kern` — сообщения ядра
- `cron` — задачи планировщика

**Примеры правил:**

```conf
# Все сообщения аутентификации → /var/log/auth.log
auth,authpriv.*         /var/log/auth.log

# Все, кроме почты → /var/log/syslog (асинхронно, с буферизацией)
mail.none;*.*           -/var/log/syslog

# Критические ошибки → всем пользователям
*.emerg                 :omusrmsg:*
```

**Модификаторы действия:**

- `-` перед путём — асинхронная запись (буферизация)
- `@` — отправка по UDP
- `@@` — отправка по TCP

### Уровни приоритета (syslog severities)

| Код | Уровень | Описание |
| :--- | :--- | :--- |
| 0 | `emerg` | Система неработоспособна |
| 1 | `alert` | Требуется немедленное действие |
| 2 | `crit` | Критические условия |
| 3 | `err` | Ошибки |
| 4 | `warning` | Предупреждения |
| 5 | `notice` | Нормальные, но значимые события |
| 6 | `info` | Информационные сообщения |
| 7 | `debug` | Отладочные сообщения |

## Практические сценарии

### Настройка удаленного логирования

#### Сервер (получатель логов)

1. **Включить прием логов** (`/etc/rsyslog.d/50-remote.conf`):

   ```conf
   # Прием по TCP (надежно, с подтверждением)
   module(load="imtcp")
   input(type="imtcp" port="514")
   
   # Прием по UDP (ненадежно, без подтверждения)
   # module(load="imudp")
   # input(type="imudp" port="514")
   ```

2. **Создать шаблон для разделения по хостам:**

   ```conf
   # Шаблон: /var/log/remote/HOSTNAME/PROGRAM.log
   template(name="RemoteHostLog" type="string"
            string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")
   
   # Применить шаблон ко всем входящим сообщениям
   *.* action(type="omfile" dynaFile="RemoteHostLog")
   ```

3. **Перезапустить и открыть порт:**

   ```bash
   sudo systemctl restart rsyslog
   sudo firewall-cmd --add-port=514/tcp --permanent && sudo firewall-cmd --reload
   ```

#### Клиент (отправитель логов)

`/etc/rsyslog.d/99-forward.conf`:

```conf
# Отправка по TCP (надежно)
*.* @@remote-log-server:514

# Отправка по UDP (быстрее, но без гарантий)
# *.* @remote-log-server:514

# Отправка только определенных facility
# local0.* @@remote-log-server:514
```

Перезапуск:

```bash
sudo systemctl restart rsyslog
```

### Интеграция с `systemd-journald`

**Модуль `imjournal`:** позволяет `rsyslog` забирать сообщения из `journald`.

1. **Загрузить модуль** (`/etc/rsyslog.conf`):

   ```conf
   module(load="imjournal")
   # Опционально: игнорировать уже прочитанные сообщения
   # imjournal.IgnorePreviousMessages="on"
   ```

2. **Перезапустить:**

   ```bash
   sudo systemctl restart rsyslog
   ```

### Тестирование конфигурации

```bash
# Проверка синтаксиса
sudo rsyslogd -N1

# Отправить тестовое сообщение
logger -t test_script "Тестовое сообщение"

# Проверить попадание в лог
tail -f /var/log/syslog | grep test_script
```

### Отладка проблем

```bash
# Включить отладочный режим (временная остановка службы)
sudo systemctl stop rsyslog
sudo rsyslogd -dn > /tmp/rsyslog_debug.log 2>&1

# Проверить открытые порты
ss -tlnp | grep rsyslog

# Проверить статус службы
systemctl status rsyslog
journalctl -u rsyslog -f
```

## Дополнительная информация

### Типичные проблемы

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Логи не записываются | Неправильные права на файлы | `chown syslog:adm /var/log/*.log` |
| Нет логов от systemd | Модуль `imjournal` не загружен | Проверить `module(load="imjournal")` |
| Дублирование сообщений | `journald` + `rsyslog` пишут в один файл | Настроить `ForwardToSyslog=no` в `journald.conf` |
| Высокое потребление CPU | Интенсивное логирование | Настроить фильтрацию, увеличить буферы |

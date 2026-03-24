# Использование journalctl — Практические сценарии

## 1. Просмотр логов

### Базовые команды

| Команда | Описание |
|---------|----------|
| `journalctl` | Все логи (в обратном хронологическом порядке) |
| `journalctl -f` | Логи в реальном времени (поток событий) |
| `journalctl -k` | Логи ядра (аналог `dmesg`) |
| `journalctl -kf` | Логи ядра в реальном времени |
| `journalctl -b` | Логи с последней загрузки |
| `journalctl -b -1` | Логи с предыдущей загрузки |
| `journalctl --list-boots` | Список всех зарегистрированных загрузок |
| `journalctl -r` | Логи от новых к старым (обратный порядок) |

### Примеры

```bash
# Все логи
journalctl

# Логи в реальном времени
journalctl -f

# Логи ядра
journalctl -k

# Логи с последней загрузки
journalctl -b

# Логи с предыдущей загрузки
journalctl -b -1

# Список всех загрузок
journalctl --list-boots
```

---

## 2. Фильтрация логов

### По службе (unit)

```bash
# Логи сервиса Nginx
journalctl -u nginx.service

# И с отслеживанием в реальном времени
journalctl -u nginx.service -f

# Логи нескольких сервисов
journalctl -u sshd.service -u httpd.service
```

### По процессам и пользователям

```bash
# По идентификатору процесса (PID)
journalctl _PID=1234

# По идентификатору пользователя (UID)
journalctl _UID=1000
```

### По времени

```bash
# За последний час
journalctl --since "1 hour ago"

# С определенной даты и времени
journalctl --since "2023-10-26 18:00:00"

# Между двумя датами
journalctl --since "2023-10-26 18:00:00" --until "2023-10-26 18:10:00"
```

### По уровню приоритета

```bash
# Только ошибки и более критичные сообщения
journalctl -p err

# Только предупреждения и ошибки
journalctl -p warning..err
```

### По пути к исполняемому файлу

```bash
journalctl /usr/lib/systemd/systemd
```

---

## 3. Экспорт и форматирование вывода

`journalctl` поддерживает различные форматы вывода, что полезно для интеграции с системами мониторинга или дальнейшей обработки скриптами:

### JSON-формат

```bash
# Вывод в JSON (одна строка на запись)
journalctl -u nginx.service --output=json

# Вывод в JSON (красивый, многострочный)
journalctl -u nginx.service --output=json-pretty

# Вывод в JSON с экранированием (для парсинга)
journalctl -u nginx.service --output=json-sse
```

### Другие форматы

| Формат | Опция | Описание |
|--------|-------|----------|
| Короткий | `--output=cat` | Только сообщение |
| Syslog | `--output=syslog` | Традиционный формат syslog |
| Journal | `--output=short-journal` | С дополнительными метаданными |

---

## 4. Расширенные сценарии использования

### Поиск по содержимому логов

```bash
# Поиск по тексту в логах (регистронезависимый)
journalctl -u nginx.service | grep -i "error"

# Встроенный поиск journalctl (быстрее, т.к. использует индексы)
journalctl -u nginx.service -g "error"
```

### Подсчет событий

```bash
# Подсчитать количество ошибок сервиса
journalctl -u nginx.service -p err --no-pager | wc -l

# Статистика по уровням логирования
journalctl -u nginx.service --no-pager | awk '{print $5}' | sort | uniq -c
```

### Сравнение логов между загрузками

```bash
# Логи сервиса за текущую и предыдущую загрузку
journalctl -u nginx.service -b 0
journalctl -u nginx.service -b -1
```

### Мониторинг конкретных полей (метаданных)

```bash
# Показать только PID процессов
journalctl -u nginx.service -o verbose | grep _PID

# Показать только сообщения от определенного исполняемого файла
journalctl EXE=/usr/sbin/nginx
```

## Связанные документы

- **[journalctl — Обзор](./journalctl_overview.md)** — определения, концепции, хранение
- **[Управление хранением](./journalctl_management.md)** — очистка, лимиты, интеграция
- **[journald.md](../SystemAdministration/Logging/journald.md)** — конфигурация демона

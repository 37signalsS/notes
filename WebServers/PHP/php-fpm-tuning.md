# PHP-FPM: тюнинг, мониторинг и эксплуатация

## Определения

**PHP-FPM (FastCGI Process Manager)** — менеджер процессов PHP, реализующий протокол FastCGI для обработки PHP-запросов от веб-серверов (Nginx, Apache, Lighttpd).

**Process Manager (pm)** — стратегия управления процессами PHP-FPM: `static`, `dynamic`, `ondemand`.

**Max children** — максимальное число дочерних процессов PHP-FPM.

**Start servers** — число процессов, создаваемых при старте PHP-FPM.

**Min/Max spare servers** — минимальное/максимальное число простаивающих процессов.

**Request terminate timeout** — время ожидания завершения запроса перед принудительным завершением процесса.

**Slowlog** — лог для медленных запросов.

**Status page** — страница с детальной информацией о состоянии пула процессов.

**Opcache** — кэш скомпилированного PHP-кода в оперативной памяти.

**Realpath cache** — кэш реальных путей к файлам.

**Memory limit** — максимальный объем памяти, доступный одному PHP-процессу.

---

## Основные концепции

### Процесс-менеджеры PHP-FPM

| pm | Описание | Сценарий |
| :--- | :--- | :--- |
| **static** | Фиксированное число процессов. | Низкая латентность, стабильная нагрузка. |
| **dynamic** | Гибкое число процессов от `pm.min_spare_servers` до `pm.max_children`. | Переменная нагрузка, большинство production-сценариев. |
| **ondemand** | Процессы создаются по требованию и завершаются после `pm.process_idle_timeout`. | Низкая нагрузка, экономное потребление памяти. |

### Ограничения `dynamic`

`pm.max_children` вычисляется по формуле:

```
pm.max_children = (Доступная RAM - RAM для ОС - RAM для кэшей) / RAM на один PHP-процесс
```

Пример:
- Доступная RAM: 4 GB.
- RAM для ОС: 1 GB.
- RAM для кэшей (Opcache, Redis): 1 GB.
- RAM на один PHP-процесс: 50 MB.
- `pm.max_children` = (4096 - 1024 - 1024) / 50 = 41.

---

## Практические сценарии

### Сценарий 1: Базовая конфигурация `dynamic`

```ini
[www]
user = www-data
group = www-data
listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
pm = dynamic
pm.max_children = 41
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 10
pm.max_requests = 500
request_terminate_timeout = 30
request_slowlog_timeout = 5s
slowlog = /var/log/php8.4-fpm/slowlog
```

**Ключевые моменты:**
- `pm = dynamic` — гибкое число процессов.
- `pm.max_children = 41` — рассчитано по формуле.
- `pm.start_servers = 5` — 5 процессов при старте.
- `pm.min_spare_servers = 5` — минимум 5 простаивающих процессов.
- `pm.max_spare_servers = 10` — максимум 10 простаивающих процессов.
- `pm.max_requests = 500` — перезапуск процесса после 500 запросов (борьба с утечками памяти).
- `request_terminate_timeout = 30` — принудительное завершение запроса через 30 секунд.
- `request_slowlog_timeout = 5s` — запись в slowlog при превышении 5 секунд.

### Сценарий 2: Базовая конфигурация `static`

```ini
[www]
user = www-data
group = www-data
listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
pm = static
pm.max_children = 20
pm.max_requests = 1000
request_terminate_timeout = 30
request_slowlog_timeout = 5s
slowlog = /var/log/php8.4-fpm/slowlog
```

**Ключевые моменты:**
- `pm = static` — фиксированное число процессов.
- `pm.max_children = 20` — 20 процессов всегда.
- Низкая латентность, стабильная нагрузка.

### Сценарий 3: Мониторинг статуса PHP-FPM

```ini
[www]
user = www-data
group = www-data
listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
pm = dynamic
pm.max_children = 41
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 10
pm.max_requests = 500

pm.status_path = /fpm_status
```

**Nginx конфигурация:**
```nginx
server {
    listen 80;
    server_name php-fpm.local;

    location = /fpm_status {
        access_log off;
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;

        fastcgi_pass unix:/run/php/php8.4-fpm.sock;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $fastcgi_script_name;
    }
}
```

**Ключевые моменты:**
- `pm.status_path = /fpm_status` — включение страницы статуса.
- Доступ к `/fpm_status` должен быть ограничен внутренней сетью.

### Сценарий 4: Оптимизация Opcache

```ini
[opcache]
opcache.enable = 1
opcache.memory_consumption = 256
opcache.interned_strings_buffer = 16
opcache.max_accelerated_files = 10000
opcache.revalidate_freq = 2
opcache.validate_timestamps = 1
opcache.save_comments = 1
opcache.load_comments = 1
opcache.enable_file_override = 1
opcache.optimization_level = 0x7FFFBFFF
opcache.dups_fix = 1
opcache.blacklist_filename = /etc/php/8.4/fpm/opcache-blacklist
```

**Ключевые моменты:**
- `opcache.memory_consumption = 256` — 256 MB для кэша.
- `opcache.interned_strings_buffer = 16` — 16 MB для строк.
- `opcache.max_accelerated_files = 10000` — максимум 10000 файлов.
- `opcache.revalidate_freq = 2` — проверка изменений файлов каждые 2 секунды.
- `opcache.validate_timestamps = 1` — включение проверки изменений файлов.
- `opcache.save_comments = 1` — сохранение комментариев.
- `opcache.enable_file_override = 1` — кэширование проверки существования файлов.

### Сценарий 5: Тюнинг лимитов

```ini
[www]
user = www-data
group = www-data
listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
pm = dynamic
pm.max_children = 41
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 10
pm.max_requests = 500
request_terminate_timeout = 30
request_slowlog_timeout = 5s
slowlog = /var/log/php8.4-fpm/slowlog

; Лимиты
php_admin_value[max_execution_time] = 30
php_admin_value[max_input_time] = 30
php_admin_value[memory_limit] = 256M
php_admin_value[post_max_size] = 50M
php_admin_value[upload_max_filesize] = 50M
php_admin_value[max_file_uploads] = 20
```

**Ключевые моменты:**
- `max_execution_time = 30` — максимум 30 секунд на выполнение скрипта.
- `max_input_time = 30` — максимум 30 секунд на парсинг входных данных.
- `memory_limit = 256M` — максимум 256 MB на один скрипт.
- `post_max_size = 50M` — максимум 50 MB на POST-запрос.
- `upload_max_filesize = 50M` — максимум 50 MB на загружаемый файл.
- `max_file_uploads = 20` — максимум 20 файлов за один запрос.

### Сценарий 6: Алерты на основе метрик PHP-FPM

```yaml
groups:
  - name: php_fpm_alerts
    rules:
      - alert: PHPFPMHighActiveProcesses
        expr: php_fpm_processes_active / php_fpm_processes_max > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High active processes in {{ $labels.pool }}"
          description: "Active processes are {{ $value | humanizePercentage }} in {{ $labels.pool }}"

      - alert: PHPFPMSlowRequests
        expr: rate(php_fpm_slow_requests_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow requests detected in {{ $labels.pool }}"
          description: "Slow requests: {{ $value }} in {{ $labels.pool }}"

      - alert: PHPFPMHighMemoryUsage
        expr: php_fpm_processes_memory_bytes / php_fpm_processes_memory_max > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage in {{ $labels.pool }}"
          description: "Memory usage is {{ $value | humanizePercentage }} in {{ $labels.pool }}"
```

### Сценарий 7: Диагностика проблем

```bash
# Просмотр статуса PHP-FPM
curl http://localhost/fpm_status
# → активные процессы, простаивающие процессы, общее число запросов

# Просмотр логов PHP-FPM
tail -f /var/log/php8.4-fpm/error.log
# → ошибки, предупреждения

# Просмотр медленных запросов
tail -f /var/log/php8.4-fpm/slowlog
# → медленные запросы, стек вызовов

# Проверка конфигурации PHP-FPM
php-fpm8.4 -t
# → синтаксическая проверка конфигурации

# Перезагрузка PHP-FPM
systemctl reload php8.4-fpm
# → перезагрузка без разрыва соединений
```

**Ключевые моменты:**
- `/fpm_status` — страница статуса.
- `error.log` — ошибки.
- `slowlog` — медленные запросы.
- `php-fpm8.4 -t` — проверка конфигурации.
- `systemctl reload php8.4-fpm` — перезагрузка без разрыва соединений.

---

## Дополнительная информация

### Чек-лист тюнинга PHP-FPM

- [ ] **pm:** `dynamic` для переменной нагрузки, `static` для стабильной.
- [ ] **pm.max_children:** рассчитано по формуле на основе доступной RAM.
- [ ] **pm.start_servers:** 20% от `pm.max_children`.
- [ ] **pm.min_spare_servers:** 10% от `pm.max_children`.
- [ ] **pm.max_spare_servers:** 30% от `pm.max_children`.
- [ ] **pm.max_requests:** 500-1000 для борьбы с утечками памяти.
- [ ] **Opcache:** включен, 256 MB.
- [ ] **slowlog:** включен, `request_slowlog_timeout = 5s`.
- [ ] **Статусная страница:** `/fpm_status`, доступ ограничен внутренней сетью.
- [ ] **Мониторинг:** алерты на активные процессы, медленные запросы, использование памяти.

### Рекомендации по тюнингу

1. **Начинайте с `dynamic`:** большинство production-сценариев.
2. **Рассчитывайте `pm.max_children`:** по формуле на основе доступной RAM.
3. **Используйте `pm.max_requests`:** 500-1000 для борьбы с утечками памяти.
4. **Включайте slowlog:** для диагностики медленных запросов.
5. **Оптимизируйте Opcache:** 256 MB, `opcache.max_accelerated_files = 10000`.
6. **Мониторьте статусную страницу:** алерты на активные процессы, медленные запросы.
7. **Используйте `php-fpm8.4 -t`:** проверка конфигурации перед применением.

### См. также

- **[PHP-FPM Monitoring](../PHP/php-fpm-monitoring.md) — мониторинг PHP-FPM.
- **[FastCGI и PHP-FPM в Angie](../Angie/angie-fastcgi-php-fpm.md) — практические сценарии.
- **[Nginx Performance Tuning](../Nginx/Performance/nginx_performance_tuning.md) — тюнинг производительности.
- **[PHP Documentation](https://www.php.net/manual/en/install.fpm.configuration.php) — документация PHP-FPM.
- **[PHP-FPM Status](https://www.php.net/manual/en/fpm.status.php) — документация статусной страницы.

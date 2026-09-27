# Debug-логи в production

## Определения

**Debug-логи в production** — временное или постоянное включение расширенного логирования (уровень `debug` или `trace`) на рабочих серверах для диагностики инцидентов, отладки производительности и анализа поведения приложения. Критически важно для SRE/DevOps, так как позволяет собрать детали без перезапуска сервиса.

**Проблема:** debug-логи генерируют объём данных в 10-100 раз больше, чем info/error. Без контроля они могут заполнить диск за минуты и деградировать производительность.

## Базовые концепции

### Уровни логирования и их стоимость

| Уровень | Объём (отн.) | Использование | Риск в production |
|:---|:---|:---|:---|
| **emerg/alert** | 1 | Критические сбои системы | Нет |
| **critical/error** | 1-5 | Ошибки бизнес-логики | Нет |
| **warning** | 5-10 | Потенциальные проблемы | Нет |
| **info** | 10-20 | Нормальная работа | Низкий |
| **debug** | 100-500 | Детали выполнения | Высокий (disk fill) |
| **trace** | 500-10000 | Каждый вызов/шаг | Критический |

### Методы включения debug-логирования

| Метод | Сервис/система | Временность | Описание |
|:---|:---|:---|:---|
| **systemd override** | Любые systemd-сервисы | Временный | `systemctl edit <service>` |
| **Флаг запуска** | nginx, postgresql, etc. | До перезапуска | Параметр командной строки |
| **HTTP API** | Grafana, Prometheus, Vault | Мгновенный | `/api/v1/config/log-level` |
| **Файл конфигурации** | Любые | Постоянный | `log_level = debug` |
| **Signal** | Некоторые демоны | Мгновенный | `SIGUSR1` переключает уровень |

## Практические сценарии

### Сценарий 1: Включение debug через systemd override

```bash
# Включение debug для конкретного сервиса
sudo systemctl edit nginx.service

# Добавить в [Service]:
[Service]
LogLevelMax=debug

# Применить
sudo systemctl daemon-reload
sudo systemctl restart nginx

# Проверка
journalctl -u nginx -f --since "5 min ago" | head -20

# Отключение (вернуть info)
sudo systemctl edit nginx.service
# Удалить строку LogLevelMax=debug
sudo systemctl daemon-reload
sudo systemctl restart nginx
```

### Сценарий 2: Временное debug-логирование nginx

```bash
# Через error_log (без перезапуска через reload)
sudo nginx -t  # Проверка конфигурации

# Временное добавление debug
sudo sed -i 's/error_log \/var\/log\/nginx\/error.log;/error_log \/var\/log\/nginx\/error.log debug;/' /etc/nginx/nginx.conf

# Применение без downtime
sudo nginx -s reload

# Сбор логов (30 секунд)
timeout 30 journalctl -u nginx -f | tee /tmp/nginx-debug-$(date +%s).log

# Отключение
sudo sed -i 's/error_log \/var\/log\/nginx\/error.log debug;/error_log \/var\/log\/nginx\/error.log;/' /etc/nginx/nginx.conf
sudo nginx -s reload
```

### Сценарий 3: Debug-логирование PostgreSQL

```bash
# Включение через ALTER SYSTEM (без перезапуска в PG 9.4+)
sudo -u postgres psql -c "ALTER SYSTEM SET log_min_duration_statement = 0;"
sudo -u postgres psql -c "ALTER SYSTEM SET log_statement = 'all';"
sudo -u postgres psql -c "SELECT pg_reload_conf();"

# Проверка
sudo -u postgres psql -c "SHOW log_min_duration_statement;"
# → 0

# Сбор логов
timeout 60 tail -f /var/log/postgresql/postgresql-*.log | grep -i "statement"

# Отключение
sudo -u postgres psql -c "ALTER SYSTEM RESET log_min_duration_statement;"
sudo -u postgres psql -c "ALTER SYSTEM RESET log_statement;"
sudo -u postgres psql -c "SELECT pg_reload_conf();"
```

### Сценарий 4: Dynamic log level через HTTP API (Grafana)

```bash
# Включение debug
curl -s -X POST http://admin:admin@localhost:3000/api/admin/settings \
  -H "Content-Type: application/json" \
  -d '{"log":{"level":"debug"}}'

# Проверка текущего уровня
curl -s http://admin:admin@localhost:3000/api/admin/settings | jq '.log.level'

# Возврат на info
curl -s -X POST http://admin:admin@localhost:3000/api/admin/settings \
  -H "Content-Type: application/json" \
  -d '{"log":{"level":"info"}}'
```

### Сценарий 5: Безопасный debug через буфер

```bash
#!/bin/bash
# Безопасное включение debug с ограничением по времени и размеру

SERVICE="$1"
DURATION="${2:-60}"  # По умолчанию 60 секунд
MAX_LOG_SIZE="${3:-100M}"  # Максимальный размер логов

echo "Включение debug для $SERVICE на $DURATION секунд..."

# Включение
sudo systemctl set-property "$SERVICE.service" LogLevelMax=debug

# Мониторинг размера логов
START_SIZE=$(sudo journalctl -u "$SERVICE" --disk-usage | grep -oP '[\d.]+[MG]' | head -1)

# Ожидание
sleep "$DURATION"

# Отключение
sudo systemctl set-property "$SERVICE.service" LogLevelMax=info

END_SIZE=$(sudo journalctl -u "$SERVICE" --disk-usage | grep -oP '[\d.]+[MG]' | head -1)
echo "Debug завершён. Размер логов: $START_SIZE → $END_SIZE"
```

### Сценарий 6: journald — ограничение debug-логов

```ini
# /etc/systemd/journald.conf
[Journal]
# Сохранять только info и выше (отсечь debug из постоянного хранилища)
MaxLevelStore=info

# Пересылать в syslog только warning и выше
MaxLevelSyslog=warning

# Ограничение размера
SystemMaxUse=1G
MaxRetentionSec=7day
```

```bash
# Очистка debug-логов после инцидента
sudo journalctl --vacuum-size=500M
sudo journalctl --vacuum-time=1d
```

### Сценарий 7: Алерт на рост debug-логов

```yaml
# Prometheus alert rule
groups:
  - name: debug_log_alerts
    rules:
      - alert: DebugLogVolumeHigh
        expr: |
          rate(journald_messages_total{priority="debug"}[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий объем debug-логов на {{ $labels.instance }}"
          description: "Debug-логи превышают 100 сообщений/сек"
```

## Диагностика

### Проверка текущего уровня логирования

```bash
# Для systemd-сервиса
systemctl show nginx.service -p LogLevelMax
# → LogLevelMax=info

# Для journald
grep -E "^LogLevelMax|^MaxLevelStore" /etc/systemd/journald.conf

# Просмотр debug-сообщений
journalctl -u nginx -p debug --since "5 min ago" | wc -l
```

### Очистка после debug-сессии

```bash
# 1. Убедитесь, что debug отключен
systemctl show <service> -p LogLevelMax

# 2. Очистите debug-логи
sudo journalctl --vacuum-size=500M

# 3. Проверьте размер
journalctl --disk-usage
```

## Дополнительная информация

### Лучшие практики

1. **Никогда не оставляйте debug в production постоянно** — включайте только на время инцидента.
2. **Используйте таймаут** — автоматическое отключение через N секунд.
3. **Мониторьте размер логов** — алерт на рост > 2x от нормы.
4. **Настройте `MaxLevelStore=info`** — debug-логи не должны сохраняться постоянно.
5. **Используйте `LogLevelMax` в systemd** — проще, чем менять конфигурацию сервиса.
6. **Документируйте инцидент** — зафиксируйте, какой debug был включен и зачем.
7. **Тестируйте на staging** — включите debug в test-среде перед production.
8. **Ограничивайте scope** — debug только для нужного модуля/компонента, не глобально.
9. **Используйте structured logging** — debug-логи в JSON проще парсить.
10. **Очищайте после** — удалите debug-логи после анализа инцидента.

### См. также

- [Обзор системы логирования](./logging_overview.md)
- [systemd-journald: Rate Limiting](./journald.md)
- [Маскирование PII в debug-логах](./pii_masking.md)

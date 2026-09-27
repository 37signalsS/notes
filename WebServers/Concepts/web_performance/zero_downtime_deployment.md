# Zero-Downtime Deployment и Graceful Reload для веб-производительности

## Определения

**Graceful Reload** — перезагрузка конфигурации веб-сервера без разрыва обработки запросов: старые worker-процессы дообслуживают активные соединения и завершаются, новые стартуют с новой конфигурацией.

**Graceful Shutdown** — корректная остановка worker-процесса: он не закрывает соединение, пока не завершит обслуживание клиента; управляется директивой `worker_shutdown_timeout`.

**Binary Upgrade** — замена исполняемого файла веб-сервера на лету без остановки сервиса и потерь соединений. В Angie/Nginx реализуется через сигналы `USR2` и `WINCH`.

**Zero-Downtime Deployment** — процесс обновления кода или конфигурации без прерывания обслуживания клиентов. В контексте веб-производительности означает отсутствие роста 5xx ошибок, TTFB и потерь соединений во время деплоя.

**Downtime Window** — период, в течение которого сервис недоступен или обрабатывает запросы с деградацией производительности. Для Core Web Vitals критично: любое превышение TTFB >500 мс или 5xx ошибка в течение деплоя может затронуть 75-й перцентиль CrUX.

**Worker Shutdown Timeout** — директивa, ограничивающая время graceful shutdown. По умолчанию `0` (ожидать завершения без ограничений). Для production рекомендуется `10s`-`30s`.

## Основные концепции

### Как работает reload на уровне процессов

```
Master Process (PID 1)
├── Worker #1 (старая конфигурация) ──── serving active connections
├── Worker #2 (старая конфигурация) ──── serving active connections
└── Worker #3 (новая конфигурация) ──── accepting new connections
```

1. Master проверяет синтаксис новой конфигурации (`nginx -t` или `angie -t`).
2. При успехе master запускает новых воркеров с новой конфигурацией.
3. Старым воркерам отправляется сигнал graceful shutdown.
4. Старые воркеры закрывают listen-сокеты, но продолжают обслуживать активные соединения.
5. По завершении соединений или по истечении `worker_shutdown_timeout` старые воркеры завершаются.

### Влияние на производительность во время деплоя

| Фаза деплоя | Влияние на Web Vitals | Mitigation |
| :--- | :--- | :--- |
| **Reload** | Рост TTFB на 5-20 мс (новые воркеры стартуют) | Старые воркеры продолжают обслуживать; клиенты не замечают. |
| **Graceful Shutdown** | Если `worker_shutdown_timeout` слишком короткий — разрыв долгих соединений (WebSocket, SSE, gRPC) | Установить `worker_shutdown_timeout 10s;` для high-load. |
| **Binary Upgrade** | Временный рост RPS на старые воркеры (пока новые стартуют) | Последовательный upgrade на каждом узле; `USR2` + `WINCH` + `QUIT`. |
| **Cache Warming** | После restart кэш пустой — рост Origin Load и TTFB | `proxy_cache_path file=` в Angie 1.9+ для мгновенной загрузки индекса. |

### Директивы влияющие на zero-downtime

| Директива | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `worker_shutdown_timeout` | Максимальное время graceful shutdown | `10s` для обычного API, `30s` для WebSocket/gRPC |
| `keepalive_timeout` | Время ожидания idle keepalive-соединения | Согласовать с `worker_shutdown_timeout` |
| `proxy_connect_timeout` | Таймаут установки соединения с бэкендом | `5s` для предотвращения зависаний при деплое |
| `proxy_read_timeout` | Таймаут чтения ответа от бэкенда | Согласовать с SLA бэкенда |

### Особенности HTTP/3 и QUIC при reload

HTTP/3 (QUIC) сохраняет активные сессии при reload только если:
1. Ядро Linux 5.7+ с поддержкой eBPF.
2. Включена директива `quic_bpf on;`.

Без `quic_bpf` все HTTP/3 соединения разрываются при reload, что вызывает падение LCP и INP для клиентов на QUIC.

## Практические сценарии

### Сценарий 1: Graceful reload конфигурации

```bash
# Проверка синтаксиса перед reload
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf test is successful

# Reload без потерь соединений
sudo systemctl reload nginx
# ИЛИ: sudo kill -HUP $(cat /run/nginx.pid)

# Проверка поколения конфигурации (Angie)
curl -s http://localhost:8888/api/status/angie/ | jq .generation
# → 2 (увеличился на 1)
```

**Важно:** При ошибке в конфигурации reload не применяется, но сервис продолжает работать со старой конфигурацией. Никакого downtime.

### Сценарий 2: Binary upgrade без простоя

Процедура замены бинарника Nginx/Angie на лету:

```bash
# 1. Установка новой версии (dpkg/rpm)
sudo apt install nginx=1.26.1

# 2. Проверка нового бинарника
sudo nginx -t
# → syntax is ok

# 3. Запуск нового мастера (USR2)
sudo kill -USR2 $(cat /run/nginx.pid)
sleep 1

# 4. Проверка PID старый/новый
sudo cat /run/nginx.pid.oldbin   # PID старого мастера
sudo cat /run/nginx.pid          # PID нового мастера

# 5. Graceful shutdown старых воркеров (WINCH)
sudo kill -WINCH $(cat /run/nginx.pid.oldbin)

# 6. Валидация
curl -s https://example.com/ -o /dev/null -w "%{http_code}\n"
# → 200

# 7. Завершение старого мастера (QUIT)
sudo kill -QUIT $(cat /run/nginx.pid.oldbin)
```

**Откат при проблеме:**
```bash
# Если новое бинарник не работает
sudo kill -HUP $(cat /run/nginx.pid.oldbin)  # поднять воркеры старого мастера
sudo kill -TERM $(cat /run/nginx.pid)         # погасить новый мастер
```

### Сценарий 3: Настройка worker_shutdown_timeout для WebSocket/gRPC

```nginx
http {
    # Для high-load с долгими соединениями
    worker_shutdown_timeout 10s;

    server {
        listen 443 ssl http2;

        # WebSocket endpoint
        location /ws/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";

            # Увеличить таймауты для долгих соединений
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }

        # Обычный API
        location /api/ {
            proxy_pass http://backend;
            proxy_connect_timeout 5s;
            proxy_read_timeout 30s;
        }
    }
}
```

### Сценарий 4: Деployment pipeline с канареечным проветом

```yaml
# GitHub Actions workflow
name: Canary Deploy
on: push

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to canary
        run: |
          ssh deploy@canary "nginx -t && systemctl reload nginx"

      - name: Smoke test
        run: |
          curl -f https://canary.example.com/health
          curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s\n" https://canary.example.com/

      - name: Validate Web Vitals
        run: |
          lhci collect --url=https://canary.example.com/ --numberOfRuns=3
          lhci assert

      - name: Promote to production
        if: success()
        run: |
          ssh deploy@prod "nginx -t && systemctl reload nginx"
```

### Сценарий 5: Blue-Green deployment с Nginx/Angie

Переключение трафика между двумя инстансами без downtime:

```bash
# 1. Деплой новой версии на port 8081
systemctl start nginx-green

# 2. Валидация
curl -f http://localhost:8081/health

# 3. Переключение балансировщика
upstream=`cat /etc/nginx/upstream.conf`
sed -i 's/8080/8081/' /etc/nginx/upstream.conf
nginx -t && systemctl reload nginx

# 4. Мониторинг 5xx
tail -f /var/log/nginx/access.log | grep ' 5[0-9][0-9] '

# 5. Если OK — остановить старую версию
systemctl stop nginx-blue
```

## Операции и команды

### Проверка поколения конфигурации

```bash
# Angie
curl -s http://localhost:8888/api/status/angie/ | jq .generation
# → 2

# Nginx (через PID)
ps -eo pid,cmd | grep "nginx: master"
# → 1234 nginx: master process /usr/sbin/nginx
```

### Проверка открытых соединений после reload

```bash
# Количество established соединений не должно падать
ss -tan | grep -c ESTAB
# → 4521

# Количество TIME_WAIT
ss -s | grep time-wait
# → 891 (нормально, если не растёт)
```

### Мониторинг worker-процессов

```bash
# Проверка, что старые воркеры завершились
ps -eo pid,cmd | grep "nginx: worker process"
# → 1235 nginx: worker process
# → 1236 nginx: worker process
# (только новые воркеры)
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Соединения рвутся при reload** | Клиенты получают 499/502 при деплое | `worker_shutdown_timeout` = 0 или слишком маленький | Установить `worker_shutdown_timeout 10s;` |
| **Старые воркеры не умирают** | После reload worker-ы "висят" часами | Долгие соединения (WebSocket, SSE) | Увеличить `worker_shutdown_timeout` или закрыть проблемные соединения |
| **HTTP/3 разрывается при reload** | Рост 5xx для клиентов на QUIC | Отсутствует `quic_bpf on;` или ядро <5.7 | Включить `quic_bpf on;`, обновить ядро |
| **Reload не применяется** | `systemctl reload` возвращает ошибку | Ошибка в конфигурации | `nginx -t` перед reload; исправить и повторить |
| **Рост TTFB после reload** | LCP упал на 200-500 мс | Новые воркеры ещё "горячие" (JIT) | Cache warm-up, pre-warm keepalive пул |
| **DNS failover не работает** | После сбоя бэкенда прокси продолжает слать запросы на мёртвый IP | `resolver` не настроен или TTL кэша DNS слишком большой | Настроить `resolver` с `valid=300s` |

## Рекомендации

### Базовые правила

1. **Всегда проверяйте синтаксис перед reload:** `nginx -t` или `angie -t`. Это предотвращает применение сломанной конфигурации.
2. **Настройте `worker_shutdown_timeout` для high-load:** `10s` для обычного API, `30s` для WebSocket/gRPC/SSE.
3. **Используйте `quic_bpf on;` для HTTP/3:** Без этого все QUIC соединения рвутся при reload.
4. **Проводите sequential upgrade по узлам:** При multi-node deployments reload/upgrade на каждом узле последовательно, а не одновременно.
5. **Мониторьте поколение конфигурации:** Алерт при неожиданном скачке generation — признак неавторизованного reload.

### Для DevOps/SRE/SysAdmin

- **Deploy pipeline:** Валидация → Canary → Smoke Test → Full Rollout. На каждом этапе проверяйте TTFB, 5xx и Web Vitals.
- **Cache warming:** После reload/CDN purge наполняйте кэш популярными ресурсами через `curl` или CDN API.
- **Runbook:** Для каждого деплоя должен быть runbook с шагами отката (`git checkout` + `systemctl reload`).
- **Monitoring during deploy:** Real-time дашборд с TTFB, 5xx rate, Cache Hit Ratio. Алерт при росте 5xx >1% в течение 5 минут.

## Дополнительная информация

### См. также

- [Оптимизация веб-серверов Nginx](../../WebServers/Nginx/Performance/nginx_performance_tuning.md) — детальный тюнинг worker-ов и keepalive.
- [Graceful Reload и Binary Upgrade в Angie](../../WebServers/Angie/angie-graceful-reload.md) — полное руководство по сигналам Angie.
- [Мониторинг Angie через API](../../WebServers/Angie/angie_monitoring/angie_monitoring_api.md) — отслеживание поколения конфигурации.
- [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — QUIC connection migration при reload.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — как keepalive влияет на TTFB.

### RFC и спецификации

- **RFC 7230** — HTTP/1.1: Connection Management, keepalive.
- **RFC 7540** — HTTP/2: graceful shutdown потоков.
- **RFC 9000** — QUIC: connection migration и graceful shutdown.

# Деплой SSR/SSG/ISR приложений (Next.js/Nuxt)

## Определения

- **SSR (Server-Side Rendering)** — рендеринг HTML на сервере при каждом запросе. Требует запущенного процесса (Node.js) и обратного прокси.
- **SSG (Static Site Generation)** — рендеринг всех страниц в статические HTML-файлы на этапе сборки. Деплоится как статика (см. [Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)).
- **ISR (Incremental Static Regeneration)** — гибрид: статические страницы пересобираются на сервере по расписанию/по запросу (revalidate).
- **Hydration** — «оживление» серверного HTML клиентским JS на стороне браузера.
- **Runtime-конфигурация** — параметры приложения, читаемые в момент запуска процесса (не запечённые в билд).
- **Cold start** — задержка первого запроса к непрогретому процессу/воркеру.

---

## Основные концепции

### Чем деплой SSR отличается от статики
Для чистой статики достаточно раздать файлы (nginx + CDN). Для SSR нужен **живой процесс**, который:
- слушает порт и отдаёт HTML («динамический origin»);
- управляется процесс-менеджером (systemd / pm2 / supervisor);
- спрятан за reverse proxy (nginx) для TLS, keepalive, балансировки и отдачи статики.

### Инъекция конфигурации: build-time vs runtime
Классический собес-вопрос: «Можно ли хранить секреты в фронтенд-бандле?» — **нет**. Всё, что попадает в бандл, видно клиенту. Поэтому:
- API-ключи, используемые браузером, — публичные по определению (ограничиваются на стороне API по origin/rate-limit).
- Секреты серверной части (БД, приватные API) читаются SSR-процессом **в рантайме** из env/файла, а не из `process.env` на этапе `build`. Иначе секрет окажется в образе/артефакте. Подробнее: **[Управление секретами](../DevSecOps/secrets_management.md)**.

### Независимость сборки и деплоя
Артефакт SSR должен содержать и server-, и client-бандлы (`next build` → `.next/`). Процесс запускается независимо, что позволяет делать rolling/blue-green обновления без пересборки.

### Zero-downtime и health checks
Обновление SSR = замена процесса. Чтобы не было простоя: старый процесс дожидается завершения активных запросов (`graceful shutdown`), новый стартует и проходит health check до переключения трафика.

### Требования к окружению

Для production-деплоя SSR/SSG/ISR необходимы:
- **Node.js runtime:** фиксированная LTS-версия (`.nvmrc` / `engines`), совпадающая в CI и на сервере. Для SSR/ISR обязательна совместимость версий `next`/`nuxt` между билдом и рантаймом.
- **Process manager:** systemd (предпочтительно на bare-metal/VPS) или PM2/supervisor. Отвечает за автозапуск, `Restart=on-failure`, draining при SIGTERM.
- **Reverse proxy:** nginx/Angie перед процессом — TLS-терминация, keepalive, отдача статики, балансировка при нескольких инстансах.
- **Runtime-конфигурация:** источник параметров, читаемых при старте процесса (файл `.env`, Consul/Vault, `EnvironmentFile` systemd). Никаких секретов в билде.
- **Health check эндпоинт:** `/healthz` или аналогичный, проверяющий БД, кэш, внешние зависимости. Используется оркестратором/балансировщиком для принятия решения о маршрутизации.
- **Мониторинг:** доступ к логам процесса (`journalctl` / stdout), метрики Node.js (event loop lag, heap, active handles) и ресурсы хоста (RSS, CPU).

---

## Практические сценарии

### Сценарий 1: Сборка и упаковка артефакта
```bash
npm ci && npm run build     # next build / nuxt build -> .next / .output
# Артефакт: только prod-зависимости
npm prune --omit=dev
tar -czf dist/ssr-app.tar.gz .next node_modules package.json
# → архив готов к переносу на сервер
```

### Сценарий 2: systemd unit для Node-процесса
```ini
# /etc/systemd/system/ssr-app.service
[Unit]
Description=SSR App
After=network.target

[Service]
User=app
WorkingDirectory=/var/www/ssr-app/current
Environment=NODE_ENV=production
EnvironmentFile=/var/www/ssr-app/current/.env   # runtime-конфиг, не в билде
ExecStart=/usr/bin/node node_modules/.bin/next start -p 3000
Restart=on-failure
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```
```bash
# Атомарная смена релиза + перезапуск (rolling)
ln -sfn /var/www/ssr-app/releases/$VER /var/www/ssr-app/current
systemctl restart ssr-app
systemctl is-active --quiet ssr-app && echo "SSR process is running"
# → SSR process is running
```

### Сценарий 3: nginx reverse proxy + отдача статики
```nginx
upstream ssr {
    server 127.0.0.1:3000;
    keepalive 32;
}
server {
    location /_next/static/ {
        alias /var/www/ssr-app/current/.next/static/;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
    location / {
        proxy_pass http://ssr;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Сценарий 4: Health check и rolling-обновление
```bash
# Эндпоинт /healthz проверяет готовность (БД, кэш)
curl -fsS http://127.0.0.1:3000/healthz || { echo "health failed"; exit 1; }
# → HTTP 200, тело {"status":"ok"} (при корректной настройке)
# Blue-green: поднимаем второй инстанс на :3001, проверяем, меняем upstream, гасим старый
```

### Сценарий 5: ISR/ответное кэширование
```nginx
# Кэшируем отрендеренные SSR-страницы на уровне прокси (stale-while-revalidate)
proxy_cache_path /var/cache/ssr levels=1:2 keys_zone=ssr_cache:10m;
location / {
    proxy_cache ssr_cache;
    proxy_cache_valid 200 10s;
    add_header X-Cache-Status $upstream_cache_status;
}
# → X-Cache-Status: MISS (первый запрос), HIT (повторный в течение 10с), STALE (после 10с, фоновая перегенерация)
```

---

## Дополнительная информация

### Лучшие практики
1. Секреты — только в runtime (`EnvironmentFile`), никогда в `build`.
2. Используйте `graceful shutdown` (ловить `SIGTERM`), чтобы не обрывать запросы при деплое.
3. Отдавайте `.next/static` и хэшированные ассеты напрямую из nginx (`immutable`), не пускайте через Node.
4. Обязателен `/healthz`, по которому оркестратор/балансировщик принимает решение о маршрутизации.
5. Ограничивайте память процесса (Node может утечь) — `max-old-space-size` + мониторинг RSS.
6. Ведение retention: храните минимум 3–5 последних релизов для мгновенного отката; удаляйте старые каталоги по cron или post-deploy хуком.
7. Наблюдаемость процесса: экспортируйте `nodejs_eventloop_lag_seconds`, `nodejs_heap_used_bytes`, `nodejs_active_handles_total` и RSS хоста. Детали метрик и порогов — в **[Метрики рантаймов приложений](../../Concepts/Observability_and_Monitoring/application_runtime_metrics.md)**.
8. Для ISR контролируйте `revalidate` и `fallback`: убедитесь, что фоновые перегенерации не бьют по SLO latency при всплеске трафика.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Утечка секретов | Секрет в `build` | Перенести в runtime env (EnvironmentFile) |
| 502 после деплоя | Процесс не успел подняться | Health check + задержка перед снятием старого |
| Высокий cold start | Прогрев JIT / тяжёлый модуль | Warm-up запрос, PM2 cluster, preload |
| OOM-килл | Утечка памяти в SSR | Лимиты RSS + рестарт по порогу, профилирование |
| Mixed content | Инлайн-ресурсы по http | Единый `https`, CSP, HSTS |

### Диагностика production SSR

```bash
# Проверка, что процесс SSR отвечает и отдаёт HTML
curl -sS http://127.0.0.1:3000/ | head -1
# → <!DOCTYPE html> (при корректном рендеринге)

# Проверка graceful shutdown: SIGTERM должен дождаться завершения активных запросов
kill -TERM $(pgrep -f "next start") && sleep 1 && systemctl is-active ssr-app
# → inactive (процесс корректно остановлен)

# Проверка метрик Node.js (prom-client / metrics endpoint)
curl -s http://127.0.0.1:3000/metrics | grep -E "nodejs_eventloop_lag_seconds|nodejs_active_handles_total"
# → nodejs_eventloop_lag_seconds 0.0021
# → nodejs_active_handles_total 42

# Проверка утечки памяти: RSS процесса не растёт линейно
ps -p $(pgrep -f "next start") -o rss,vsz,etime
# → RSS     VSZ      ELAPSED
# → 512340  892100   2h 15m  (стабильный RSS при нормальной работе)

# Проверка, что статические ассеты отдаются напрямую из nginx, а не через Node
curl -I https://example.com/_next/static/chunk.js
# → X-Cache-Status: HIT (из nginx, без proxy_pass к Node)
```

### Особые случаи

- **Утечка памяти в SSR:** Node.js может не возвращать память ОС даже после `--max-old-space-size`. При стабильном росте RSS без прироста heap — ищите утечки в `nodejs_external_memory_bytes` (Buffer, WASM, нативные модули). Решение: лимиты cgroup + `OOMScoreAdjust=-500` для systemd-юнита, чтобы ядро убило именно процесс SSR, а не соседний критичный сервис.
- **Cold start после деплоя:** первый запрос к прогретому процессу может быть медленнее на 20–40% из-за JIT-кешей и прогрева подключений к БД. Используйте warm-up запросы (`curl /healthz` в цикле после `systemctl restart`) или PM2 cluster mode с `instances=1` и `exec_mode=cluster`.
- **Stateful ISR:** `revalidate` по расписанию может «поднять» устаревшие данные, если БД ещё не пополнилась новыми записями. Добавьте `unstable_revalidate` с проверкой актуальности данных или используйте `on-demand` ISR через webhook только после полной миграции.
- **Graceful shutdown с долгими соединениями:** WebSocket или SSE не обрываются по `SIGTERM` автоматически. В systemd увеличьте `TimeoutStopSec` до 60–120с и в приложении ловите `SIGTERM` для закрытия WS-сессий.
- **SSR в контейнере:** контейнер не должен быть PID 1 для Node — используйте `tini` или `--init`, иначе `SIGTERM` не доходит до процесса. Устанавливайте `--init` в Dockerfile или `initProcess: true` в systemd-nspawn.
- **Низкий трафик и прогрев JIT:** при <10 RPS процессы часто попадают в `idle` и теряют JIT-кеш. Для таких SSR-сервисов настройте `systemd` `WatchdogSec=0` (отключить) и используйте keepalive к БД/кэшу, чтобы соединения не разрывались.

### См. также
- **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)** — keepalive, websockets, CORS, отдача статики.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — runbook при падении SSR/утечке памяти.
- **[Security-заголовки и CSP](./frontend_security_headers.md)** — nonce для SSR и защита статики.
- **[Secrets Management в CI/CD](../DevSecOps/secrets_management.md)** — Vault, dynamic secrets, rotation для runtime-конфигурации.
- **[Vault: интеграция с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)** — Vault Agent, CSI Driver, интеграция с подами.
- **[Деплой фронтенда в Kubernetes](./frontend_kubernetes_deployment.md)** — практика Kubernetes для SSR/SSG.

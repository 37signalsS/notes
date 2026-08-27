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

---

## Практические сценарии

### Сценарий 1: Сборка и упаковка артефакта
```bash
npm ci && npm run build     # next build / nuxt build -> .next / .output
# Артефакт: только prod-зависимости
npm prune --omit=dev
tar -czf dist/ssr-app.tar.gz .next node_modules package.json
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
```

---

## Дополнительная информация

### Лучшие практики
1. Секреты — только в runtime (`EnvironmentFile`), никогда в `build`.
2. Используйте `graceful shutdown` (ловить `SIGTERM`), чтобы не обрывать запросы при деплое.
3. Отдавайте `.next/static` и хэшированные ассеты напрямую из nginx (`immutable`), не пускайте через Node.
4. Обязателен `/healthz`, по которому оркестратор/балансировщик принимает решение о маршрутизации.
5. Ограничивайте память процесса (Node может утечь) — `max-old-space-size` + мониторинг RSS.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Утечка секретов | Секрет в `build` | Перенести в runtime env (EnvironmentFile) |
| 502 после деплоя | Процесс не успел подняться | Health check + задержка перед снятием старого |
| Высокий cold start | Прогрев JIT / тяжёлый модуль | Warm-up запрос, PM2 cluster, preload |
| OOM-килл | Утечка памяти в SSR | Лимиты RSS + рестарт по阈値, профилирование |
| Mixed content | Инлайн-ресурсы по http | Единый `https`, CSP, HSTS |

### См. также
- **[Docker: лучшие практики для фронтенда](../../Docker/Dockerfile/Docker_best_practices/frontend.md)** — контейнеризация SSR-сборки.
- **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)** — keepalive, websockets, CORS, сжатие.
- **[Стратегии деплоя](../Core_Concepts/deployment_strategies.md)** — blue-green / rolling для процессов.
- **[Управление секретами](../DevSecOps/secrets_management.md)** — runtime-инъекция конфигурации.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — runbook при падении SSR.

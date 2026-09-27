# Инцидент-респонс и постмортем для фронтенда

## Определения

- **Инцидент (Incident)** — событие, нарушающее доступность или качество фронтенд-сервиса (битый деплой, всплеск JS-ошибок, сломанный SW, неверные заголовки).
- **SEV (Severity)** — уровень критичности (SEV1 — полная недоступность, SEV3 — локальная деградация).
- **MTTR (Mean Time To Recovery)** — среднее время восстановления.
- **Blameless Postmortem** — разбор без поиска виноватых, фокус на системных причинах и действиях.
- **Runbook** — пошаговая инструкция реакции на типовой инцидент.
- **Kill Switch** — аварийное отключение функционала/флага без пересборки (см. [Feature flags в доставке фронтенда](./feature_flags_frontend.md)).

---

## Требования к окружению

Для оперативного реагирования на фронтенд-инциденты в production необходимы:

- **Доступ к origin/deploy-хосту:** SSH-ключ или bastion для атомарного отката symlink (см. [Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)). Хранится в защищённом vault, доступ только для on-call.
- **CDN/edge API credentials:** Токены для принудительной инвалидации (`/assets`, `/sw.js`, `index.html`). Должны быть в CI/CD secrets или vault, не в репозитории.
- **Feature flag платформа:** Unleash/Flipt/LD с админским доступом для kill switch. Подробнее — в **[Feature flags в доставке фронтенда](./feature_flags_frontend.md)**.
- **Мониторинг и алертинг:** Prometheus + Alertmanager для RUM/JS Error Rate алертов, доступ к дашбордам Grafana.
- **Браузерная диагностика:** Playwright/Puppeteer или devtools-доступ к preview-среде для проверки SW, CSP, mixed content.
- **Логи:** Доступ к логам origin (nginx/Angie error/access), CDN edge-логи, CI-логи последних деплоев.
- **Артефакты:** Хранилище последних N релизов (обычно 5–10) для быстрого отката без пересборки.

---

## Основные концепции

### Типичные фронтенд-инциденты
1. **Broken deploy** — новый бандл не грузится (404 на чанк, синтаксическая ошибка, несовместимость с API).
2. **Stale Service Worker** — пользователи получают старый UI/SW (см. [Service Worker и PWA](./service_worker_pwa_cicd.md)).
3. **Cache poisoning / неполная инвалидация CDN** — Edge отдаёт старые ассеты.
4. **CORS / Mixed Content / CSP break** — ресурсы перестают грузиться после смены домена/заголовков.
5. **Всплеск JS-ошибок** — упавший релиз или несовместимость с браузером.
6. **Деградация CWV** — LCP/INP выросли, SLO нарушен (см. [SLO/SLI и RUM](./frontend_slo_rum.md)).
7. **Canary/Blue-Green деградация** — новый релиз показывает регрессию по метрикам, требуется автоматический или ручной откат канарейки.
8. **Feature flag баг** — включённый флаг ломает CUJ (Critical User Journey) для сегмента пользователей.

### Роль on-call и коммуникация
У фронтенда свой on-call: алерты по RUM/JS Error Rate и по синтетике. Коммуникация — через статус-страницу и чат инцидента. Важно различать «сломался деплой» (нужен откат/флаг) и «сломался бэкенд» (фронт — лишь симптом).

### Эскалация и уровни реагирования
- **L1 (on-call):** Подтверждение симптома, запуск runbook, быстрый откат/флаг.
- **L2 (Senior Frontend/SRE):** Runbook не помог, требуется глубокая диагностика (SW, CDN, edge).
- **L3 (команда разработки + DevOps):** Баг в коде, требуется hotfix/rollforward.
- **L4 (архитектура/вендор):** Проблема в инфраструктуре или стороннем сервисе (CDN, FFaaS).

### Runbook-структура
Каждый типовой инцидент должен иметь:
1. **Симптом:** как обнаружили (алерт, жалоба, мониторинг).
2. **Диагностика:** команды для определения scope и root cause.
3. **Действие:** конкретные шаги восстановления.
4. **Валидация:** как подтвердить, что проблема решена.
5. **Коммуникация:** кому сообщить, обновлять статус-страницу.

### Postmortem-культура
После SEV2+ проводится бламлесс-разбор: таймлайн, impact, root cause, action items (с владельцами и сроками). Цель — предотвратить повторение, а не наказать.

---

## Практические сценарии

### Сценарий 1: Runbook «Broken deploy» (быстрый откат)
```bash
# 1. Подтверждаем симптом (404 на чанк / ошибки в RUM)
# 2. Атомарный откат symlink (статика) — см. frontend_pipeline_specifics.md
PREV=$(ssh deploy@origin "ls -1dt /var/www/app/releases/* | sed -n 2p")
ssh deploy@origin "ln -sfn $PREV /var/www/app/current"
# 3. Инвалидация CDN/edge
curl -X POST "$CDN/purge" -H "Auth: $TOKEN" -d '{"prefix":"/assets"}'
# 4. Проверка smoke-теста
curl -fsS https://example.com/ && echo "recovered"
```

### Сценарий 2: Всплеск JS-ошибок → Kill Switch
```bash
# Через FFaaS (Unleash) мгновенно гасим проблемный флаг
curl -X POST "$UNLEASH/features/new-checkout/environments/production/off" \
  -H "Authorization: $TOKEN"
# → kill switch без пересборки и деплоя
```

### Сценарий 3: Диагностика «застрявшего» SW
```bash
# Проверяем, какую версию sw.js отдаёт edge и origin
curl -sI https://cdn.example.com/sw.js | grep -i -E "cache-control|etag"
curl -sI https://origin.example.com/sw.js | grep -i -E "cache-control|etag"
# Если расходятся — инвалидируем sw.js в CDN принудительно
```

### Сценарий 4: CDN poisoning / stale assets (Edge отдаёт старое)
```bash
# 1. Проверяем, что origin отдаёт актуальный артефакт
curl -sI https://origin.example.com/assets/app.a3f92bc1.js | grep -i etag
# 2. Проверяем edge — сравниваем ETag/Content-Length
curl -sI https://cdn.example.com/assets/app.a3f92bc1.js | grep -i -E "etag|content-length|age"
# 3. Если расхождение — принудительная инвалидация по префиксу/тегу
curl -X POST "$CDN/purge" -H "Auth: $TOKEN" -d '{"prefix":"/assets"}'
# 4. После инвалидации — повторная проверка через edge
curl -sI https://cdn.example.com/assets/app.a3f92bc1.js | grep -i "x-cache"
# → X-Cache: Miss (ожидаемо после purge)
```

### Сценарий 5: CORS / Mixed Content / CSP break
```bash
# 1. Проверяем CORS для шрифтов/API
curl -sI https://example.com/assets/font.woff2 | grep -i "access-control-allow-origin"

# 2. Проверяем mixed content
curl -s https://example.com/ | grep -iE "src=['\"]http://|href=['\"]http://"
# → (пусто) — mixed content отсутствует

# 3. Проверяем CSP enforce/report-only
curl -sI https://example.com/ | grep -i "content-security-policy"
# → Content-Security-Policy: default-src 'self'; ...

# 4. Для диагностики CSP violations — проверяем эндпоинт /csp-report
curl -s -X POST https://example.com/csp-report \
  -H "Content-Type: application/json" \
  -d '{"csp-report":{"blocked-uri":"https://example.com","violated-directive":"script-src"}}'
# → 200 (лог должен появиться в SIEM/файле)
```

### Сценарий 6: Деградация CWV после деплоя (LCP/INP)
```bash
# 1. Проверяем текущий SLO по RUM
curl -s "$PROMETHEUS/api/v1/query?query=job:frontend_lcp_good_ratio" | jq '.data.result[0].value'
# → 0.97 (ниже порога 0.99 — бюджет исчерпан)

# 2. Определяем, какой деплой вызвал регрессию
curl -s "$PROMETHEUS/api/v1/query?query=increase(js_errors_total[10m])" | jq '.data.result'
# → рост с 14:02 (совпадает с временем деплоя)

# 3. Откат или kill switch
ssh deploy@origin "ln -sfn $(ls -1dt /var/www/app/releases/* | sed -n 2p) /var/www/app/current"
# ИЛИ через FFaaS, если проблема в новом флаге
```

### Сценарий 7: Canary/Blue-Green деградация → автооткат
```bash
# Если используются канарейки/blue-green, откат = переключение трафика
# Nginx upstream switch (пример для blue-green)
ssh deploy@origin "sed -i 's/server blue:80/server green:80/' /etc/nginx/conf.d/upstream.conf"
nginx -s reload

# Или через CDN: изменить origin group с canary на stable
curl -X PUT "$CDN/origin/groups/canary" -H "Auth: $TOKEN" -d '{"origin":"stable"}'
```

### Сценарий 8: Шаблон бламлесс-постмортема
```markdown
**Postmortem: SEV2 Broken Checkout (2026-08-27)**
**Impact:** 12% пользователей не могли оформить заказ ~25 мин.
**Root cause:** Деплой чанка без инвалидации CDN → 404 на new-checkout.js.
**Timeline:** 14:02 деплой → 14:05 алерт JS errors → 14:27 откат.
**Action items:**
- [ ] Автоматическая инвалидация `/assets` после деплоя (owner: devops, till 09-01)
- [ ] Pre-deploy проверка доступности чанков на origin (owner: ci, till 09-03)
- [ ] Добавить RUM-алерт на 404 ассетов (owner: sre, till 09-05)
```

---

## Валидация

### После отката/восстановления
- **Smoke test:** `curl -fsS https://example.com/ && echo "recovered"` — должен вернуть 200.
- **Chunk availability:** Проверьте, что ключевые ассеты загружаются: `curl -s -o /dev/null -w "%{http_code}\n" https://example.com/assets/app.[hash].js` → 200.
- **SW версия:** `curl -sS https://example.com/sw.js | grep -i cacheId` — должен совпадать с предыдущей/ожидаемой версией.
- **JS Error Rate:** В RUM/Prometheus алерты должны затухнуть в течение 2–5 минут после отката.
- **CWV:** LCP/INP должны вернуться в SLO-пороговые значения (проверка через Grafana/CrUX).
- **CDN invalidation:** `curl -sI https://cdn.example.com/assets/app.[hash].js | grep -i x-cache` → `Miss`/`Refresh` на первый запрос, затем `Hit`.

### В пайплайне (pre-deploy prevention)
- **Asset pre-check:** До инвалидации проверяем доступность всех чанков на origin: `for f in $(cat dist/manifest.json | jq -r '.[]'); do curl -fsS "https://origin.example.com/$f" || exit 1; done`.
- **Smoke test после деплоя:** Блокирующий шаг в CI; если smoke test не прошёл — автоматический откат.
- **LHCI/A11y gates:** Блокируют деплой при регрессии CWV или a11y.
- **SLO check:** Перед деплоем проверяем, что error budget не исчерпан (см. [SLO/SLI и RUM](./frontend_slo_rum.md)).

---

## Наблюдаемость

- **RUM-метрики:** JS Error Rate, Crash-Free Sessions, доля 4xx/5xx на ассетах — первичные сигналы инцидента. Детали — в **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)**.
- **Синтетика:** LHCI в CI + внешние синтетики (Pingdom, UptimeRobot) — ловят проблемы до пользователей.
- **Логи origin:** access/error логи nginx/Angie для 4xx/5xx на ассетах, `tail -F /var/log/nginx/access.log | grep '\.js" 404'`.
- **CDN edge-логи:** Анализ `X-Cache: Miss`/`Hit`, `Age` заголовка, чтобы понять, откуда отдаётся контент.
- **SW-метрики:** `service_worker.registered`, `service_worker.updated`, adoption rate (доля пользователей на новом SW).
- **Алерты:** Настройте алерты на JS Error Rate >1%, LCP >2.5s, asset 404 rate >0.1%, SW update failure rate.
- **SIEM:** CSP violations, CORS errors, mixed content — должны логироваться в централизованный сборщик.

---

## Операции и команды

### Быстрые проверки
```bash
# Доступность ключевых ассетов
curl -s -o /dev/null -w "%{http_code}\n" https://example.com/assets/app.[hash].js
# → 200

# Проверка SW
curl -sI https://example.com/sw.js | grep -i -E "cache-control|etag"
# → Cache-Control: no-cache
# → ETag: "a3f92bc1"

# Проверка CDN edge
curl -sI https://cdn.example.com/assets/app.[hash].js | grep -i -E "x-cache|age|etag"
# → X-Cache: Hit
# → Age: 120

# JS-ошибки в production (через RUM/Prometheus)
curl -s "$PROMETHEUS/api/v1/query?query=increase(js_errors_total[5m])" | jq '.data.result[0].value[1]'
# → 0.0 (ожидается 0 при нормальной работе)
```

### Откат symlink
```bash
# Список релизов
ssh deploy@origin "ls -1dt /var/www/app/releases/* | head -5"

# Откат на предыдущий
PREV=$(ssh deploy@origin "ls -1dt /var/www/app/releases/* | sed -n 2p")
ssh deploy@origin "ln -sfn ${PREV} /var/www/app/current"

# Инвалидация HTML после отката
curl -X POST "$CDN/purge" -H "Auth: $TOKEN" -d '{"paths":["/index.html"]}'
```

### Инвалидация CDN
```bash
# По префиксу (ассеты)
curl -X POST "$CDN/purge" -H "Auth: $TOKEN" -d '{"prefix":"/assets"}'

# По конкретному файлу (sw.js)
curl -X POST "$CDN/purge" -H "Auth: $TOKEN" -d '{"paths":["/sw.js"]}'

# Проверка результата
curl -sI https://cdn.example.com/assets/app.[hash].js | grep -i "x-cache"
# → X-Cache: Miss
```

### Kill Switch
```bash
# FFaaS (Unleash) — выключение проблемного флага
curl -X POST "$UNLEASH/features/new-checkout/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"

# Проверка, что флаг выключен
curl -s "$UNLEASH/api/features/new-checkout" | jq '.enabled'
# → false
```

### Логирование и диагностика
```bash
# Tail ошибок nginx
ssh deploy@origin "tail -F /var/log/nginx/error.log | grep -E '\.js|\.css|sw\.js'"

# Статистика 404 за последний час
ssh deploy@origin "awk '\$9 ~ /404/ {print \$7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20"

# CSP violations из лога
ssh deploy@origin "grep -oP '\"blocked-uri\":\"[^\"]+\"' /var/log/nginx/csp_violations.log | sort | uniq -c | sort -rn | head -20"
```

---

## Особые случаи

- **Stale SW на long-lived tabs:** Пользователь с открытой вкладкой «зависнет» на старом SW. Решения: `skipWaiting` + `clients.claim`, баннер обновления. Adoption rate может не доходить до 100% — это нормально.
- **CDN не инвалидирует по тегу:** Surrogate-Key не пробрасывается или CDN в режиме pass-through. Проверьте `curl -I` к Origin напрямую — заголовок `Surrogate-Key`/`Cache-Tag` должен присутствовать. Убедитесь, что CDN настроена на его интерпретацию.
- **Race condition при деплое:** CDN инвалидировала HTML раньше, чем ассеты долетели до origin. Порядок: `rsync` ассетов → `ln -sfn` → проверка доступности → инвалидация.
- **Partial deploy:** Если деплой involves несколько хостов/DC, откат должен быть синхронным на всех. Проверяйте `readlink` на каждом хосте.
- **Feature flag с default=True:** При сбое FFaaS функция остаётся активной (kill switch не сработает). Для критичных переключений используйте `default=False`.
- **SSR-процесс в inconsistent state:** Если SSR упал во время деплоя, health check должен детектировать это и не направлять трафик. Проверьте `/healthz` перед объявлением деплоя успешным.
- **Legacy IE11:** `X-XSS-Protection` и `X-Content-Type-Options: nosniff` нужны для старых движков. SW не поддерживается в IE11 — нужен fallback.
- **Safari ITP:** Intelligent Tracking Prevention может ограничивать SW в фоновом режиме. Тестируйте офлайн-режим в Safari отдельно.

---

## Лучшие практики

1. У каждого типового инцидента должен быть **runbook** с готовыми командами отката.
2. Откат — это flip symlink / feature flag, а не пересборка (быстрее и безопаснее).
3. Инвалидируйте CDN после каждого деплоя статики; проверяйте доступность чанков на origin ДО инвалидации.
4. JS Error Rate и RUM-ассеты — обязательные алерты (ранний сигнал битого релиза).
5. Постмортемы пишутся бламлесс и порождают action items с владельцами.
6. Настройте эскалацию L1→L2→L3 с таймаутами (например, 15/30/60 мин) — не заставляйте on-call висеть на проблеме часами.
7. Храните runbook'ы рядом с кодом (в репозитории фронтенда), чтобы они актуализировались вместе с деплоем.
8. Для kill switch критичных функций используйте `default=False` (fail-closed) — при сбое FFaaS функция остаётся выключенной.
9. Валидируйте откат smoke-тестом перед объявлением восстановления — `curl` + проверка JS Error Rate.
10. Документируйте все инциденты в едином системе (Jira/Incident.io/Грейлог) с корреляцией по deploy_version.
11. Проводитеgame days: регулярно тренируйте команду на инцидент-респонсе (Chaos Engineering для фронтенда).
12. После каждого инцидента проверяйте, не сломал ли откат/флаг другие CUJ — регрессия может быть скрытой.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Откат не помог | Старый SW кэширует битый HTML | Инвалидировать `sw.js` + принудительный reload |
| Алертов нет | Нет RUM-метрик | Добавить JS Error Rate / asset 404 алерты |
| Долго локализуем | Нет версии в метриках | Тегировать RUM события `deploy_version` |
| Повтор инцидента | Нет action items | Постмортем с проверяемыми действиями |
| CDN не инвалидирует | Surrogate-Key не настроен | Проверить заголовок на Origin, конфиг CDN |
| SW adoption rate низкий | Long-lived tabs, нет skipWaiting | `skipWaiting` + `clients.claim`, баннер обновления |
| Kill switch не сработал | FFaaS упал, default=True | Использовать `default=False` для критичных флагов |
| Partial deploy | Откат только на part хостов | Синхронизировать symlink на всех DC, проверять `readlink` |
| CSP break после деплоя | Новый инлайн-скрипт не в allowlist | Добавить hash/nonce, или Report-Only для сбора нарушений |
| Mixed content ломает страницу | HTTP-ресурсы на HTTPS-странице | Заменить на относительные URL или HTTPS |

---

## Дополнительная информация

### См. также

- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — атомарный откат symlink, инвалидация CDN, smoke-тест.
- **[Service Worker и PWA](./service_worker_pwa_cicd.md)** — диагностика застрявшего SW, skipWaiting, adoption rate.
- **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)** — источник алертов, error budget, burn rate.
- **[Chaos Engineering: обзор](../../Chaos_Engineering/)** — методология, инструменты и практические сценарии.
- **[Disaster Recovery и Backup для Traefik](../../WebServers/Traefik/traefik-disaster-recovery.md)** — RTO/RPO, failover, backup стратегии.
- **[Ведение журнала Vault](../../Vault/guides/audit_log_analysis.md)** — аудит доступа к секретам и трассировка инцидентов.

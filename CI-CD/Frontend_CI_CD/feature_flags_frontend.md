# Feature flags в доставке фронтенда

## Определения

- **Feature Flag (Feature Toggle)** — механизм включения/выключения функционала в runtime без пересборки и деплоя (см. **[Обзор Feature Toggles](../../CI-CD/Testing/feature_toggles/overview.md)**).
- **Progressive Delivery** — постепенная поставка (canary/A-B) через флаги, отделяющая Deployment от Release.
- **Kill Switch** — аварийное выключение функции за миллисекунды (без пайплайна).
- **OpenFeature** — открытый стандарт SDK для работы с флагами (CNCF Graduated), абстрагирующий вендора.
- **FFaaS (Feature Flag as a Service)** — платформа управления флагами (Unleash self-hosted, Flipt, LaunchDarkly).
- **Client-side vs Server-side evaluation** — оценка флага в браузере (client) или на сервере/edge (server); для безопасности и SEO предпочтителен server-side.
- **Bootstrap/JSON flags** — флаги, подгружаемые в рантайме из FFaaS (fetch при старте) + закешированный bootstrap-файл для офлайна.
- **Stickiness** — свойство системы возвращать одно и то же значение флага для одного контекста (`user_id`, `session_id`) на протяжении всего эксперимента, исключая «мерцание» UI.

---

## Основные концепции

### Отделение Deploy от Release для фронтенда

Фронтенд-код выкатывается в прод «тёмным» (функция скрыта флагом), а открывается пользователям позже. Это снижает риск и даёт мгновенный откат (kill switch).

С точки зрения SRE, это форма **Shift-right Testing**: проверка в среде, максимально приближённой к продакшену (та же сборка артефакта, те же конфиги, только изоляция данных), но без риска для пользователей.

### Архитектура и принципы работы

Для фронтенда различают три сценария оценки флагов, каждый со своими ограничениями и област применения:

#### 1. Client-side evaluation (в браузере)

Флаг вычисляется на клиенте после загрузки бандла. Самый простой, но и самый ограниченный вариант:

```javascript
// Клиент запрашивает флаг у FFaaS или читает из bootstrap
const showNew = ffClient.getBooleanValue('new-checkout', false, { user_id: user.id })
if (showNew) renderNewCheckout()
```

**Ограничения:**
- Флаг в бандле клиента легко подменить (изменить контекст).
- Изменение флага требует пересборки, если значение зашито в бандл.
- CDN/браузер кэш может отдать устаревшее состояние флага.
- SEO: поисковые роботы видят только дефолтное состояние.

#### 2. Server-side evaluation (SSR/SSG встраивает флаг)

Сервер/edge вычисляет флаг и встраивает результат в HTML или отдаёт через API. Браузер лишь читает готовое значение:

```javascript
// На сервере читаем флаг из FFaaS и передаём в HTML
const showNew = await ffClient.getBooleanValue('new-checkout', false, { user_id })
res.render('page', { showNewCheckout: showNew })
```

```html
<!-- Клиент лишь читает готовое значение -->
<script>window.__FLAGS__ = { newCheckout: <%= showNewCheckout %> }</script>
```

**Преимущества:**
- Безопасность: флаг не попадёт в клиентский бандл.
- SEO: поисковые роботы видят актуальное состояние.
- Нет пересборки при смене флага.
- Можно комбинировать с CDN: HTML не кэшируется агрессивно, а статические ассеты — да.

#### 3. Bootstrap/JSON (флаги в рантайме)

Флаги подгружаются при старте приложения из FFaaS (fetch) + кешируются в IndexedDB/localStorage для офлайна:

```javascript
// При старте приложения
const flags = await fetch('/api/flags?context=' + encodeURIComponent(JSON.stringify({ user_id })))
  .then(r => r.json())
// Клиент кеширует flags для последующих сессий
localStorage.setItem('flags', JSON.stringify(flags))
```

**Применение:** SPA (Single Page Applications), Progressive Web Apps, мобильный веб.

### Проблема «флага в статике»

Если фронтенд собирается в статический бандл (SPA, SSG), флаг, зашитый в JS, становится частью immutable-артефакта. Решения:

- **Server-side evaluation:** сервер/edge вычисляет флаг и встраивает результат в HTML. Не требует пересборки при смене флага.
- **Bootstrap/JSON:** флаги подгружаются в рантайме из FFaaS + закешированный bootstrap-файл для офлайна.
- **Синхронизация с кэшем:** страницы с активными флагами не кэшируются агрессивно (`Cache-Control: no-cache`), иначе пользователь увидит устаревшее состояние.

### Безопасность флагов

Флаг в бандле клиента легко подменить (изменить контекст). Флаги НЕ заменяют авторизацию. Критичные переключения должны оцениваться на сервере.

Правила:
- Release/Permission флаги: `default=False` — при сбое FFaaS функция остаётся выключенной.
- Ops (Kill Switch): `default=True` — при сбое FFaaS функция остаётся активной.
- Флаги не заменяют RBAC/авторизацию. Targeting rules управляют доступом к функции, но авторизация объектов и действий остаётся в зоне ответственности IAM.

### Наблюдаемость

Каждый флаг должен быть виден в телеметрии:

- **RUM (Real User Monitoring):** внедряйте `feature_flag.variant` и `feature_flag.enabled` в клиентские события (JS errors, performance entries).
- **OpenTelemetry:** состояние флага инжектируется в атрибуты спанов, что позволяет при анализе трейсов видеть, какая ветка кода сработала.
- **Метрики:** сравнение Error Rate и Latency между группами пользователей с активным и неактивным флагом.
- **Алерты:** при росте 5xx или деградации latency для конкретного флага — автоматический Kill Switch через Alertmanager webhook.

### Стоимость и очистка

С точки зрения FinOps, неконтролируемое количество флагов — источник техдолга и нецелевых трат на FFaaS:

- **Квоты:** лимит одновременно активных release-флагов на сервис (типично 5–10).
- **TTL:** явно заданный срок жизни флага; по истечении — алерт на удаление.
- **Cleanup:** cleanup-PR обязателен в Definition of Done; завершённые флаги удаляются из кода и FFaaS.

### Изоляция и именование

- **Per-preview флаги:** на превью-окружении (см. **[Превью-окружения](./preview_environments.md)**) включаем экспериментальные флаги через отдельный namespace платформы, не затрагивая прод.
- **Именование:** `[domain].[subdomain].[action].[identifier]` (например, `checkout.payment.applepay.enabled`). Запрещены: `test-flag`, `fix-123`, `new-logic-flag`.
- **Владельцы:** у каждого флага — owner (команда) и привязка к тикету.

---

## Практические сценарии

### Сценарий 1: Server-side evaluation (SSR встраивает флаг)

```javascript
// На сервере читаем флаг из FFaaS и передаём в HTML
const showNew = await ffClient.getBooleanValue('new-checkout', false, { user_id })
res.render('page', { showNewCheckout: showNew })
```
```html
<!-- Клиент лишь читает готовое значение -->
<script>window.__FLAGS__ = { newCheckout: <%= showNewCheckout %> }</script>
```

### Сценарий 2: Kill Switch через FFaaS (Unleash)

```bash
# Мгновенное выключение проблемного флага без деплоя
curl -X POST "$UNLEASH/features/new-checkout/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false}; клиенты получат обновление при следующем poll
```
Подробнее — в **[Сценариях Feature Toggles](../../CI-CD/Testing/feature_toggles/scenarios.md)**.

### Сценарий 3: Canary по проценту пользователей

```javascript
// Клиент запрашивает флаг с контекстом — платформа распределяет по buckets
const ctx = { user_id: user.id, version: APP_VERSION }
if (ffClient.getBooleanValue('new-search', false, ctx)) renderNewSearch()
```
Сегментация богаче сетевого canary: можно по роли, региону, версии клиента.

Для фронтенда особенно важна **stickiness** (`stickiness: user_id`), иначе пользователь будет видеть «мерцание» UI при перезагрузке страницы.

### Сценарий 4: Bootstrap/JSON для SPA

```javascript
// При старте SPA подгружаем флаги из API
async function loadFlags() {
  const ctx = { user_id: user.id, session_id: getSessionId() }
  const res = await fetch('/api/flags?' + new URLSearchParams(ctx))
  const flags = await res.json()
  window.__FLAGS__ = flags
  // Применяем флаги к UI
  applyFlags(flags)
}
loadFlags()
```

**Кэширование:** флаги кешируются в IndexedDB/localStorage с TTL (например, 5 минут). При недоступности FFaaS используется последнее известное состояние (bootstrap file).

### Сценарий 5: CDN-aware доставка флагов

Если страница кэшируется CDN, флаг в HTML может устареть. Решения:

```nginx
# HTML с флагами — не кэшировать агрессивно
location = / {
    add_header Cache-Control "public, max-age=60, stale-while-revalidate=300";
}
# Хэшированные ассеты — кэшировать бесконечно
location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

Или выносить флаги в отдельный эндпоинт `/api/flags`, который кэшируется с коротким TTL и не инвалидируется при каждом деплое.

### Сценарий 6: Per-preview флаги

На превью-окружении (см. **[Превью-окружения](./preview_environments.md)**) включаем экспериментальные флаги через отдельный namespace платформы, не затрагивая прод.

```yaml
# CI устанавливает окружение для флагов
variables:
  FF_ENVIRONMENT: "review/mr-${CI_MERGE_REQUEST_IID}"
script:
  - curl -X POST "$UNLEASH_URL/api/admin/projects/default/environments" \
      -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
      -d '{"name": "review/mr-${CI_MERGE_REQUEST_IID}", "type": "development"}'
```

### Сценарий 7: Cleanup процесс

```yaml
# CI напоминает удалить завершённые флаги (Definition of Done)
flag_hygiene:
  script:
    - |
      # Ищем флаги старше 60 дней без изменений и открываем TODO-issue
      node scripts/flag-audit.js --max-age 60
```

### Сценарий 8: Автоматический Kill Switch через Alertmanager

```yaml
# alertmanager.yml — webhook в FFaaS при росте 5xx
route:
  receiver: unleash-webhook
  match:
    alertname: HighFrontendErrorRate

receivers:
  - name: unleash-webhook
    webhook_configs:
      - url: 'http://unleash-webhook.internal:8080/api/admin/projects/default/features/new-checkout/environments/production/off'
        send_resolved: true
```

## Проверка корректности

После внедрения флага необходимо убедиться, что он работает корректно и не ломает существующий функционал:

1. **Валидация server-side evaluation (SSR):**
   ```bash
   # Проверяем, что флаг встраивается в HTML
   curl -s https://example.com/ | grep -o '__FLAGS__.*'
   # → window.__FLAGS__ = { newCheckout: true }
   ```

2. **Валидация bootstrap/JSON:**
   ```bash
   # Проверяем, что API флагов отвечает и возвращает корректный JSON
   curl -s https://example.com/api/flags?user_id=123 | jq .
   # → {"newCheckout": true, "newSearch": false}
   ```

3. **Валидация кэширования:**
   ```bash
   # HTML с флагами должен иметь короткий TTL
   curl -I https://example.com/ | grep -i cache-control
   # → Cache-Control: public, max-age=60, stale-while-revalidate=300
   ```

4. **Валидация stickiness (A/B):**
   ```bash
   # Два запроса с одним user_id должны дать одинаковый результат
   for i in 1 2; do curl -s -H "X-User-ID: user-123" https://example.com/ | grep -o 'variant-[a-z]'; done
   # → variant-a
   # → variant-a (одинаковый вариант для одного user_id)
   ```

5. **Smoke test после включения флага:**
   ```bash
   # Проверяем, что при включении флага страница не падает
   curl -sS https://example.com/ -o /dev/null -w "%{http_code}\n"
   # → 200
   ```

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Флаг не применился | Страница закэширована CDN | `Cache-Control: no-cache` для путей с флагами |
| Пользователь видит старое | Клиентский poll редкий | Уменьшить `maxAge`/включить SSE в SDK |
| Мерцание UI при A/B | Отсутствие stickiness | Настроить `stickiness: user_id` в FFaaS |
| Утечка функционала | Флаг оценивается на клиенте | Перенести оценку на сервер |
| Техдолг | Флаги не удаляются | Cleanup-PR в DoD, лимит активных флагов |
| 5xx после включения флага | Баг в новой ветке | Kill Switch через Alertmanager webhook |
| Офлайн-режим: флаг не работает | Отсутствие bootstrap-файла | Развернуть bootstrap в CI/CD; mounted volume |
| Секреты в конфиге флага | Флаговый конфиг используют как конфиг приложения | Запретить политикой; секреты — только через Vault |

## Лучшие практики

1. Критичные флаги оценивайте server-side (безопасность, SEO, мгновенный откат).
2. У каждого флага — владелец и срок жизни (expiration); завершённые удаляйте (иначе техдолг).
3. Флаги не заменяют RBAC/авторизацию.
4. Страницы с активными флагами — `no-cache`, чтобы не раздавать устаревшее состояние из CDN.
5. Всегда передавайте состояние флага в телеметрию (RUM/SLO) для анализа влияния.
6. Используйте stickiness (`user_id` или `session_id`) для A/B-тестов, чтобы исключить мерцание UI.
7. Для SPA/PWA — bootstrap-файл с последними известными состояниями флагов для офлайна.
8. Ограничивайте число одновременно активных release-флагов (5–10 на сервис).
9. Kill Switch для критичных зависимостей: `default=True`, four-eyes approval, интеграция с Alertmanager.
10. Валидируйте флаги в CI/CD: naming convention, TTL, safe defaults, environment parity (staging vs production).

---

## Дополнительная информация

### См. также

- **[Обзор Feature Toggles](../../CI-CD/Testing/feature_toggles/overview.md)** — базовые принципы, Deploy vs Release, SRE-контекст.
- **[Лучшие практики](../../CI-CD/Testing/feature_toggles/best_practices.md)** — naming conventions, TTL, cleanup, Four-Eyes Principle.
- **[Сценарии Feature Toggles](../../CI-CD/Testing/feature_toggles/scenarios.md)** — детальные сценарии: canary, kill switch, circuit breaker, dark launch.
- **[Превью-окружения](./preview_environments.md)** — per-preview namespaces флагов.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — kill switch как средство респонса.
- **[Стратегии деплоя](../Core_Concepts/deployment_strategies.md)** — canary/blue-green в комбинации с флагами.
- **[Деплой SSR/SSG/ISR](./ssr_ssg_deployment.md)** — как поднять SSR-процесс для превью.

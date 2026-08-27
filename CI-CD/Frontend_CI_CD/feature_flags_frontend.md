# Feature flags в доставке фронтенда

## Определения

- **Feature Flag (Feature Toggle)** — механизм включения/выключения функционала в runtime без пересборки и деплоя (см. **[Обзор Feature Toggles](../Testing/feature_toggles/overview.md)**).
- **Progressive Delivery** — постепенная поставка (canary/A-B) через флаги, отделяющая Deployment от Release.
- **Kill Switch** — аварийное выключение функции за миллисекунды (без пайплайна).
- **OpenFeature** — открытый стандарт SDK для работы с флагами (CNCF Graduated), абстрагирующий вендора.
- **FFaaS (Feature Flag as a Service)** — платформа управления флагами (Unleash self-hosted, Flipt, LaunchDarkly).
- **Client-side vs Server-side evaluation** — оценка флага в браузере (client) или на сервере/edge (server); для безопасности и SEO предпочтителен server-side.

---

## Основные концепции

### Отделение Deploy от Release для фронтенда
Фронтенд-код выкатывается в прод «тёмным» (функция скрыта флагом), а открывается пользователям позже. Это снижает риск и даёт мгновенный откат (kill switch).

### Проблема «флага в статике»
Если флаг вычисляется на клиенте и бандл уже собран, изменение флага требует пересборки. Решения:
- **Server-side evaluation:** сервер/edge вычисляет флаг и встраивает результат в HTML (или отдаёт через API), браузер лишь читает готовое значение. Не требует пересборки при смене флага.
- **Bootstrap/JSON:** флаги подгружаются в рантайме из FFaaS (fetch при старте) + закешированный bootstrap-файл для офлайна.
- **Синхронизация с кэшем:** страницы с активными флагами не кэшируются агрессивно (`Cache-Control: no-cache`), иначе пользователь увидит устаревшее состояние.

### Безопасность флагов
Флаг в бандле клиента легко подменить (изменить контекст). Флаги НЕ заменяют авторизацию. Критичные переключения должны оцениваться на сервере.

---

## Практические сценарии

### Сценарий 1: Server-side evaluation (SSR встраивает флаг)
```javascript
// На сервере читаем флаг из FFaaS и передаём в HTML
const showNew = await ffClient.getBooleanValue('new-checkout', false, { user_id })
res.render('page', { showNewCheckout: showNewCheckout })
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
Подробнее — в **[Сценариях Feature Toggles](../Testing/feature_toggles/overview.md)**.

### Сценарий 3: Canary по проценту пользователей
```javascript
// Клиент запрашивает флаг с контекстом — платформа распределяет по buckets
const ctx = { user_id: user.id, version: APP_VERSION }
if (ffClient.getBooleanValue('new-search', false, ctx)) renderNewSearch()
```
Сегментация богаче сетевого canary: можно по роли, региону, версии клиента.

### Сценарий 4: Per-preview флаги
На превью-окружении (см. **[Превью-окружения](./preview_environments.md)**) включаем экспериментальные флаги через отдельный namespace платформы, не затрагивая прод.

### Сценарий 5: Cleanup процесс
```yaml
# CI напоминает удалить завершённые флаги (Definition of Done)
flag_hygiene:
  script:
    - |
      # Ищем флаги старше 60 дней без изменений и открываем TODO-issue
      node scripts/flag-audit.js --max-age 60
```

---

## Дополнительная информация

### Лучшие практики
1. Критичные флаги оценивайте server-side (безопасность, SEO, мгновенный откат).
2. У каждого флага — владелец и срок жизни (expiration); завершённые удаляйте (иначе техдолг).
3. Флаги не заменяют RBAC/авторизацию.
4. Страницы с активными флагами — `no-cache`, чтобы не раздавать устаревшее состояние из CDN.
5. Всегда передавайте состояние флага в телеметрию (RUM/SLO) для анализа влияния.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Флаг не применился | Страница закэширована CDN | `Cache-Control: no-cache` для путей с флагами |
| Пользователь видит старое | Клиентский poll редкий | Уменьшить `maxAge`/включить SSE в SDK |
| Утечка функционала | Флаг оценивается на клиенте | Перенести оценку на сервер |
| Техдолг | Флаги не удаляются | Cleanup-PR в DoD, лимит активных флагов |

### См. также
- **[Обзор Feature Toggles](../Testing/feature_toggles/overview.md)** и **[Лучшие практики](../Testing/feature_toggles/best_practices.md)** — классификация, архитектура, сценарии.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — kill switch как средство респонса.
- **[Превью-окружения](./preview_environments.md)** — per-preview namespaces флагов.
- **[Стратегии деплоя](../Core_Concepts/deployment_strategies.md)** — canary/blue-green в комбинации с флагами.

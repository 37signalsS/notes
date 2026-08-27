# Инцидент-респонс и постмортем для фронтенда

## Определения

- **Инцидент (Incident)** — событие, нарушающее доступность или качество фронтенд-сервиса (битый деплой, всплеск JS-ошибок, сломанный SW, неверные заголовки).
- **SEV (Severity)** — уровень критичности (SEV1 — полная недоступность, SEV3 — локальная деградация).
- **MTTR (Mean Time To Recovery)** — среднее время восстановления.
- **Blameless Postmortem** — разбор без поиска виноватых, фокус на системных причинах и действиях.
- **Runbook** — пошаговая инструкция реакции на типовой инцидент.
- **Kill Switch** — аварийное отключение функционала/флага без пересборки (см. [Feature flags в доставке фронтенда](./feature_flags_frontend.md)).

---

## Основные концепции

### Типичные фронтенд-инциденты
1. **Broken deploy** — новый бандл не грузится (404 на чанк, синтаксическая ошибка, несовместимость с API).
2. **Stale Service Worker** — пользователи получают старый UI/SW (см. [Service Worker и PWA](./service_worker_pwa_cicd.md)).
3. **Cache poisoning / неполная инвалидация CDN** — Edge отдаёт старые ассеты.
4. **CORS / Mixed Content / CSP break** — ресурсы перестают грузиться после смены домена/заголовков.
5. **Всплеск JS-ошибок** — упавший релиз или несовместимость с браузером.
6. **Деградация CWV** — LCP/INP выросли, SLO нарушен (см. [SLO/SLI и RUM](./frontend_slo_rum.md)).

### Роль on-call и коммуникация
У фронтенда свой on-call: алерты по RUM/JS Error Rate и по синтетике. Коммуникация — через статус-страницу и чат инцидента. Важно различать «сломался деплой» (нужен откат/флаг) и «сломался бэкенд» (фронт — лишь симптом).

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

### Сценарий 4: Шаблон бламлесс-постмортема
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

## Дополнительная информация

### Лучшие практики
1. У каждого типового инцидента должен быть **runbook** с готовыми командами отката.
2. Откат — это flip symlink / feature flag, а не пересборка (быстрее и безопаснее).
3. Инвалидируйте CDN после каждого деплоя статики; проверяйте доступность чанков на origin ДО инвалидации.
4. JS Error Rate и RUM-ассеты — обязательные алерты (ранний сигнал битого релиза).
5. Постмортемы пишутся бламлесс и порождают action items с владельцами.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Откат не помог | Старый SW кэширует битый HTML | Инвалидировать `sw.js` + принудительный reload |
| Алертов нет | Нет RUM-метрик | Добавить JS Error Rate / asset 404 алерты |
| Долго локализуем | Нет версии в метриках | Тегировать RUM события `deploy_version` |
| Повтор инцидента | Нет action items | Постмортем с проверяемыми действиями |

### См. также
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — откат symlink, диагностика кэша, smoke-тест.
- **[Feature flags в доставке фронтенда](./feature_flags_frontend.md)** — kill switch как средство респонса.
- **[Service Worker и PWA](./service_worker_pwa_cicd.md)** — диагностика застрявшего SW.
- **[Стратегии здоровья и отката](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — общие принципы rollback.
- **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)** — источник алертов.

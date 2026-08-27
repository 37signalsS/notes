# Лучшие практики Feature Toggles

## Определения

**Лучшие практики (Best Practices)** — это набор апробированных архитектурных, эксплуатационных и процессных стандартов, направленных на минимизацию технического долга, обеспечение предсказуемости системы в рантайме и эффективное управление «радиусом поражения» (Blast Radius) при внедрении изменений.

**Жизненный цикл флага (Flag Lifecycle)** — процесс, охватывающий этапы от создания идеи и написания кода до полной раскатки и автоматизированного удаления (Cleanup) логики из кодовой базы.

---

## Предварительные требования

### Инструментарий

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **FFaaS платформа** | Хранение и управление флагами (Unleash, Flipt, Flagsmith) | Unleash v5+ / Flipt v1.35+ |
| **OpenFeature SDK** | Унифицированный API для проверки флагов в коде | v0.4+ (Python/Go/Java/Node) |
| **pre-commit** | Автоматизация проверок перед коммитом | v3.4+ |
| **Uber Piranha** | Автоматическое обнаружение и удаление мертвых флагов | v0.5+ |
| **OpenTelemetry Collector** | Сбор и передача телеметрии по флагам | v0.95+ |
| **Prometheus + Grafana** | Мониторинг использования и влияния флагов | Prometheus v2.50+, Grafana v10+ |

### Локальное окружение для тестирования

```bash
# Развертывание FFaaS + Redis для проверки best practices
git clone https://github.com/Unleash/unleash-docker.git
cd unleash-docker
docker compose up -d
# → Unleash: http://localhost:4242 (admin/unleash4all)

# Проверка доступности API
curl -s http://localhost:4242/api/admin/user | jq '.user.permissions'
# → ["admin"]
```

### Базовые знания

Перед изучением рекомендуется ознакомиться с:
- Общими принципами Feature Toggles ([Обзор](./overview.md))
- Классификацией флагов по типам ([Типы](./types.md))
- Архитектурой систем ([Архитектура](./architecture.md))

---

## Основные концепции

### Фундаментальные правила и стандарты

Для поддержания чистоты системы в 2026 году необходимо придерживаться строгой гигиены управления флагами.

1.  **Семантическое именование (Naming Conventions)**:
    - Имя должно отражать **суть** (бизнес-ценность), а не технический путь.
    - **Шаблон:** `[domain].[subdomain].[action].[identifier]`
    - *Примеры:* `checkout.payment.applepay.enabled`, `search.rank.algorithm.v2.active`.
    - *Запрещено:* `test-flag`, `fix-123`, `new-logic-flag`.
2.  **Безопасные значения по умолчанию (Safe Defaults / Fail-safe)**:
    - При сбое FFaaS (система управления флагами) приложение ОБЯЗАНО переходить в наиболее стабильное и безопасное состояние.
    - Для новых фич по умолчанию всегда `False`.
    - Для Kill Switch — по умолчанию `True` (фича включена, пока мониторинг не скажет обратное).
3.  **Принцип «Четырех глаз» (Four-eyes principle)**:
    - Изменение критических операционных флагов в Production требует подтверждения (Approval) от второго инженера или SRE через панель управления.
4.  **Владение и метаданные**:
    - У каждого флага должен быть **Owner** (команда).
    - Обязательная привязка к тикету (Jira/Linear).
    - **TTL (Time to Live)**: Явно заданный срок жизни флага.

---

## Практические реализации

### Именование: автоматическое enforcement через CI

Ручное соблюдение naming conventions ненадежно. Используйте CI-пайплайн для автоматической проверки.

**Проверка именования флагов в CI:**
```bash
#!/bin/bash
# scripts/check-flag-naming.sh — проверка naming conventions
set -euo pipefail

REQUIRED_PATTERN="^[a-z]+\.[a-z]+\.[a-z]+\.[a-z]+(\.[a-z]+)*$"
UNLEASH_URL="${UNLEASH_URL:-http://localhost:4242}"
UNLEASH_TOKEN="${UNLEASH_TOKEN:-*:*.admin}"

# Получение списка всех флагов
FLAGS=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_TOKEN" | \
  jq -r '.features[].name')

ERRORS=0
while IFS= read -r flag; do
  if [[ ! "$flag" =~ $REQUIRED_PATTERN ]]; then
    echo "FAIL: Flag '$flag' does not match pattern [domain].[subdomain].[action].[identifier]"
    ERRORS=$((ERRORS + 1))
  fi
done <<< "$FLAGS"

if [ "$ERRORS" -gt 0 ]; then
  echo "ERROR: $ERRORS flags with invalid naming convention"
  exit 1
fi

echo "PASS: All $ERRORS flags follow naming conventions"
```

**GitLab CI integration:**
```yaml
# .gitlab-ci.yml
flag-naming-check:
  stage: validate
  script:
    - bash scripts/check-flag-naming.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_api"
```

### TTL: автоматическое управление временем жизни

**Настройка TTL через API Unleash:**
```python
import requests
from datetime import datetime, timedelta

UNLEASH_URL = "http://unleash.internal:4242"
UNLEASH_TOKEN = "*:*.project-1.api-token"

def set_flag_ttl(flag_name: str, days: int, environment: str = "production"):
    """Установка TTL для флага — автоматическое напоминание об удалении."""
    expiry_date = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
    
    # Обновление метаданных флага с датой истечения
    response = requests.put(
        f"{UNLEASH_URL}/api/admin/projects/default/features/{flag_name}",
        headers={
            "Authorization": UNLEASH_TOKEN,
            "Content-Type": "application/json"
        },
        json={
            "staleData": {
                "stale": False,
                "potentiallyStale": False,
                "staleComment": f"Flag expires on {expiry_date}. Auto-cleanup scheduled."
            }
        }
    )
    return response.status_code == 200

# Пример: установка TTL 14 дней для экспериментального флага
set_flag_ttl("search.algorithm.v2.active", days=14)
```

**Автоматическое уведомление об истечении TTL:**
```yaml
# Prometheus: алерт на флаги с истекающим TTL
groups:
  - name: flag-ttl
    rules:
      - alert: FlagTTLExpiringSoon
        expr: |
          (flag_ttl_expiry_timestamp - time()) < (3 * 24 * 3600)
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Флаг {{ $labels.flag_name }} истекает через {{ $value | humanizeDuration }}"
          description: "Owner: {{ $labels.owner }}. Требуется решение: продлить или удалить."
          runbook_url: "https://wiki.internal/runbooks/flag-ttl-expiry"
      
      - alert: FlagTTLExpired
        expr: |
          (time() - flag_ttl_expiry_timestamp) > 0
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "Флаг {{ $labels.flag_name }} просрочен"
          description: "Флаг истек {{ $value | humanizeDuration }} назад. Требуется удаление."
          runbook_url: "https://wiki.internal/runbooks/flag-expired"
```

### Four-eyes principle: реализация approval workflow

**Настройка Change Request в Unleash:**
```bash
# Включение approval для production-окружения
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/settings" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "open",
    "changeRequestEnvironmentConfigs": [
      {
        "environment": "production",
        "requiredApprovals": 2,
        "requiresApproval": true,
        "approvers": [
          {"userId": 1, "approvalsRequired": 1},
          {"userId": 2, "approvalsRequired": 1}
        ]
      }
    ]
  }'
# → Каждое изменение флага в production требует 2 аппрува
```

**Проверка approval status:**
```bash
# Проверка pending change requests
curl -s "$UNLEASH_URL/api/admin/projects/default/change-requests?environment=production" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.changeRequests[] | select(.state == "pending")] | length'
# → Количество ожидающих аппрува изменений
```

### Safe Defaults: fail-safe implementation

**Каждая проверка флага ОБЯЗАНА содержать fallback:**
```python
from openfeature import api

def get_checkout_config():
    """Получение конфигурации checkout с fail-safe значением."""
    client = api.get_client()
    context = {"user_id": current_user.id}
    
    # Правильно: fallback-значение всегда указано
    is_new_checkout = client.get_boolean_value(
        "checkout.payment.applepay.enabled",
        False,  # ← Safe default: новая фича выключена
        context
    )
    
    # НЕПРАВИЛЬНО: fallback не указан
    # is_new_checkout = client.get_boolean_value("checkout.payment.applepay.enabled")
    # → При сбое FFaaS SDK вернет None, что может вызвать TypeError
    
    return is_new_checkout

def get_kill_switch_state():
    """Kill Switch: значение по умолчанию — фича ВКЛЮЧЕНА."""
    client = api.get_client()
    # Kill Switch: default=True (фича работает, пока не отключат)
    return client.get_boolean_value("killswitch.payment-timeout", True)
```

---

### Pre-commit hooks: гигиена флагов перед коммитом

**Установка pre-commit hook:**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-feature-flags
        name: Check Feature Flags naming and hygiene
        entry: bash scripts/check-flag-naming.sh
        language: system
        always_run: true
        stages: [commit]
      
      - id: check-flag-expiry
        name: Check flag TTL warnings
        entry: bash scripts/check-flag-expiry.sh
        language: system
        always_run: true
        stages: [commit]
```

**Скрипт проверки TTL перед коммитом:**
```bash
#!/bin/bash
# scripts/check-flag-expiry.sh
set -euo pipefail

UNLEASH_URL="${UNLEASH_URL:-http://localhost:4242}"
UNLEASH_TOKEN="${UNLEASH_TOKEN:-*:*.admin}"
WARNING_DAYS=3

EXPIRING=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_TOKEN" | \
  jq -r --argjson cutoff $(date -d "+${WARNING_DAYS} days" +%s) \
  '.features[] | select(.staleData.potentiallyStale == true) | .name')

if [ -n "$EXPIRING" ]; then
  echo "WARNING: The following flags are expiring soon or are stale:"
  echo "$EXPIRING"
  echo ""
  echo "Decide: extend TTL or plan removal. See: https://wiki.internal/runbooks/flag-lifecycle"
fi
```

### CI/CD pipeline: автоматический аудит флагов

**GitLab CI pipeline для проверки флагов:**
```yaml
# .gitlab-ci.yml
stages:
  - validate
  - test
  - deploy

flag-audit:
  stage: validate
  script:
    - echo "=== Flag Naming Check ==="
    - bash scripts/check-flag-naming.sh
    - echo "=== Flag TTL Check ==="
    - bash scripts/check-flag-expiry.sh
    - echo "=== Flag Count Check ==="
    - |
      FLAG_COUNT=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
        -H "Authorization: $UNLEASH_TOKEN" | jq '.features | length')
      echo "Active flags: $FLAG_COUNT"
      if [ "$FLAG_COUNT" -gt 50 ]; then
        echo "WARNING: Too many active flags ($FLAG_COUNT). Review and clean up."
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_api"

flag-coverage:
  stage: test
  script:
    - echo "=== Checking flag usage in code ==="
    - |
      # Подсчет использований флагов в коде
      for flag in $(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
        -H "Authorization: $UNLEASH_TOKEN" | jq -r '.features[].name'); do
        USAGE_COUNT=$(rg -c "$flag" --type py --type go --type java --type js 2>/dev/null || echo "0")
        if [ "$USAGE_COUNT" = "0" ]; then
          echo "WARNING: Flag '$flag' has no code references - candidate for cleanup"
        fi
      done
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_api"
```

### Автоматический cleanup: обнаружение и удаление мертвых флагов

**Обнаружение zombie-флагов через Prometheus:**
```yaml
# prometheus/rules/flag-hygiene.yml
groups:
  - name: flag-hygiene
    rules:
      # Флаги без изменений >30 дней
      - alert: ZombieFlagDetected
        expr: |
          (time() - flag_last_change_timestamp) > (30 * 24 * 3600)
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Флаг {{ $labels.flag_name }} не менялся более 30 дней"
          description: "Owner: {{ $labels.owner }}. Требуется проверка и возможное удаление."
          runbook_url: "https://wiki.internal/runbooks/zombie-flag-cleanup"
      
      # Флаг включен на 100% >14 дней (кандидат на удаление)
      - alert: StableFlagRemovalCandidate
        expr: |
          (flag_enabled_duration_seconds > (14 * 24 * 3600)) and
          (flag_rollout_percentage == 100)
        for: 1h
        labels:
          severity: info
        annotations:
          summary: "Флаг {{ $labels.flag_name }} стабилен на 100% более 14 дней"
          description: "Кандидат на автоматическое удаление через Uber Piranha."
          runbook_url: "https://wiki.internal/runbooks/flag-cleanup"
```

**Автоматический cleanup через Uber Piranha:**
```bash
# Сканирование кодовой базы на мертвые флаги
piranha \
  --project-dir ./src \
  --language java \
  --flag dead-feature-flag \
  --url "" \
  --statesFile ""
# → Генерирует diff с предложениями удаления if/else блоков
```

**Процесс удаления zombie-флагов:**
1. Обнаружение через алерт Prometheus или Piranha.
2. Проверка метрик: если флаг включен на 100% >14 дней без инцидентов — кандидат на удаление.
3. Создание cleanup-PR с удалением кода флага и самого флага из FFaaS.
4. Ревью и мерж — cleanup-PR обязателен в Definition of Done.

---

### Мониторинг и обсервабилити (OpenTelemetry)

Недостаточно просто включить флаг — необходимо видеть его влияние в реальном времени.

*   **Exposure Tracking**: SDK отправляет событие (Event) в аналитику в момент ПЕРВОЙ проверки флага для конкретного пользователя. Это критично для корректного расчета A/B метрик.
*   **OTel Attributes**: Состояние флагов должно инжектироваться в атрибуты спанов **OpenTelemetry**.
    ```python
    # Пример инъекции в OTel Span
    span.set_attribute("feature_flags.checkout_v2", "variant-a")
    ```
*   **Health-checks по флагам**: Сравнение Error Rate и Latency между группами пользователей с активным и неактивным флагом.

**Настройка Health Check дашборда в Grafana:**
```json
{
  "panels": [
    {
      "title": "Feature Flag Error Rate by Flag",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) by (feature_flag) / sum(rate(http_requests_total[5m])) by (feature_flag)",
          "legendFormat": "{{ feature_flag }}"
        }
      ],
      "thresholds": {
        "steps": [
          { "value": 0.01, "color": "yellow" },
          { "value": 0.05, "color": "red" }
        ]
      }
    }
  ]
}
```

### Validation Checklist

| Проверка | Метод | Ожидаемый результат |
| :--- | :--- | :--- |
| Naming convention | `bash scripts/check-flag-naming.sh` | Все флаги в формате `[domain].[subdomain].[action].[identifier]` |
| TTL установлен | `curl $UNLEASH_URL/api/admin/features \| jq '.features[].staleData'` | У каждого non-permanent флага есть TTL |
| Safe defaults | Грейпкод проверки флагов: `rg "get_boolean_value" \| wc -l` = `rg "get_boolean_value.*False" \| wc -l` | Каждая проверка содержит fallback-значение |
| Four-eyes approval | `curl $UNLEASH_URL/api/admin/projects/default/settings` | Production требует ≥2 аппрува |
| Cleanup candidates | `curl $UNLEASH_URL/api/admin/features \| jq '.features[] \| select(.staleData.potentiallyStale)'` | Список кандидатов на удаление пуст или обработан |
| Количество активных флагов | `curl $UNLEASH_URL/api/admin/features \| jq '.features \| length'` | ≤50 на сервис |

---

### FinOps и контроль затрат

Управление дорогостоящими ресурсами через динамические флаги.

*   **Quota Toggling**: Автоматическое переключение на менее ресурсоемкий алгоритм при достижении лимита бюджета для конкретного клиента или организации.
*   **Feature Tiering**: Отключение ресурсоемких функций для пользователей с низким уровнем подписки при росте общей нагрузки.

**Реализация Quota Toggling:**
```python
from openfeature import api
import redis

r = redis.Redis(host='redis.internal', port=6379, db=0)

def get_processing_mode(user_id: str) -> str:
    """Выбор режима обработки в зависимости от квоты."""
    client = api.get_client()
    context = {"user_id": user_id}
    
    # Проверка квоты в Redis
    quota_used = int(r.get(f"quota:{user_id}:processed") or 0)
    quota_limit = int(r.get(f"quota:{user_id}:limit") or 1000)
    
    if quota_used >= quota_limit:
        # Квота исчерпана → дешевый алгоритм
        return "basic"
    
    # Квота не исчерпана → проверка флага для полного функционала
    if client.get_boolean_value("processing.advanced.enabled", False, context):
        return "advanced"
    return "standard"
```

### Окружение-паритет: валидация консистентности флагов

**Diff-проверка флагов между staging и production:**
```bash
#!/bin/bash
# scripts/check-env-parity.sh — проверка консистентности флагов между средами
set -euo pipefail

STAGING_FLAGS=$(curl -s "$UNLEASH_URL_STAGING/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_TOKEN_STAGING" | \
  jq -r '.features[] | "\(.name) \(.stages[]? | select(.name == "production") | .enabled)"' | sort)

PROD_FLAGS=$(curl -s "$UNLEASH_URL_PROD/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_TOKEN_PROD" | \
  jq -r '.features[] | "\(.name) \(.stages[]? | select(.name == "production") | .enabled)"' | sort)

DIFF=$(diff <(echo "$STAGING_FLAGS") <(echo "$PROD_FLAGS") || true)

if [ -n "$DIFF" ]; then
  echo "ERROR: Flag mismatch between staging and production:"
  echo "$DIFF"
  echo ""
  echo "This may cause unexpected behavior in production."
  echo "Ensure all flag changes are deployed to both environments."
  exit 1
fi

echo "PASS: Staging and production flags are consistent"
```

**Запуск в CI/CD:**
```yaml
# .gitlab-ci.yml
env-parity-check:
  stage: validate
  script:
    - bash scripts/check-env-parity.sh
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

---

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Вероятная причина | Диагностические действия | Решение |
| :--- | :--- | :--- | :--- |
| Нейминг флагов нарушается в CI | Разработчик обходит pre-commit hook | `git log --oneline -5` → проверить коммиты; `bash scripts/check-flag-naming.sh` → воспроизвести ошибку | Настроить pre-commit hook + CI gate (merge blocked при нарушении); образование команды |
| TTL не работает | FFaaS не поддерживает TTL нативно | `curl $UNLEASH_URL/api/admin/features \| jq '.features[].staleData'` → проверить метаданные | Использовать кастомный Prometheus alert вместо native TTL; напоминание через Slack webhook |
| Cleanup PR не создается | Uber Piranha не настроен или нет доступа к API | `piranha --help` → проверить установку; проверить токен доступа к Git | Настроить GitHub/GitLab API токен для автоматических PR; добавить в cron |
| Approval workflow обходится | Admin-роль позволяет менять флаги без аппрува | `curl $UNLEASH_URL/api/admin/roles` → проверить роли | Ограничить admin-роль; для production-окружения — только через Change Request |
| Отличия флагов между staging и production | Ручное управление без GitOps | `bash scripts/check-env-parity.sh` → найти расхождения | Декларативное управление через GitOps (см. [Feature Flags в GitOps](../../GitOps/Concepts/feature_flags_gitops.md)) |
| Много僵尸 флагов (>50 активных) | Нет процесса удаления | `curl $UNLEASH_URL/api/admin/features \| jq '.features \| length'` → подсчитать | Автоматический cleanup через Piranha + Prometheus alert; лимит 50 флагов на сервис |
| Флаги конфликтуют друг с другом | Два флага влияют на один ресурс | `rg "is_enabled" --type py` → найти пересечения; проверить логику ветвления | Группировка флагов по доменам; конфликт-тестирование перед включением |
| Секреты в конфиге флага | Флаговый конфиг используют как конфиг приложения | `rg "password\|secret\|token" --type yaml` в конфигах флагов | Запретить политикой (conftest/Kyverno); секреты — только через Vault/ESO |
| Клиентские флаги отличаются от серверных | SDK кеширует старое значение | `tcpdump -i any port 8013` → проверить SSE/gRPC; проверить `cache_ttl` | Увеличить частоту polling; переключиться на SSE; проверить flagd sidecar |

---

## Ограничения и особые случаи (Edge Cases)

### Комбинаторный взрыв

10 независимых бинарных флагов дают 1024 состояния системы. Ограничивайте количество одновременно активных релизных флагов на сервис (типично: 5-10). Каждое新增ление флага требует проверки пересечений с существующими.

### Глобальные побочные эффекты

Если два флага влияют на один глобальный ресурс (переменную окружения, запись в БД) в несовместимых режимах — возникает коллизия. Требуется группировка флагов по доменам и конфликт-тестирование.

### Миграции БД

Флаги не должны управлять структурой таблиц. Попытка изменять схему БД внутри логических условий флага приводит к разрыву между состоянием кода и схемы.

### Кэширование на CDN/Браузере

Если флаг определяет видимость элемента UI, а страница кэшируется CDN или браузером, пользователь может видеть устаревшее состояние. Решение: не кэшировать страницы с активными флагами или добавлять `Cache-Control: no-cache` для путей с флагами.

### Offline-режим (Mobile)

При отсутствии сети SDK не может получить обновленное значение флага. Используйте bootstrap-файл (последнее известное состояние) или hardcoded fallback. См. [Архитектура](./architecture.md) — Bootstrap File implementation.

### Одновременные A/B-тесты

Если два эксперимента затрагивают один и тот же UI-компонент, результаты могут быть искажены. Необходимо выявлять пересечения и запускать их последовательно или исключать пересекающуюся аудиторию.

### FinOps: LLM/внешние API

При управлении дорогостоящими ресурсами через флаги необходимо учитывать задержку переключения. Если флаг отключает LLM-запрос, пользователь может заметить degraded体验 до полного переключения. Решение: кеширование результатов LLM + graceful degradation.

---

## Дополнительная информация

### Техническая гигиена (OpenFeature)

Использование стандарта **OpenFeature** позволяет абстрагироваться от конкретного вендора (Unleash, LaunchDarkly, ConfigCat) и применять общие хуки (Hooks) для логирования и валидации данных во всех микросервисах.

### См. также
- **[Обзор Feature Toggles](./overview.md)** — парадигма Deploy vs Release.
- **[Типы Feature Toggles](./types.md)** — классификация по назначению и сроку жизни.
- **[Архитектура систем](./architecture.md)** — Relay, Proxy и Edge-вычисления, Bootstrap File, flagd.
- **[Антипаттерны](./antipatterns.md)** — типичные ошибки, которых следует избегать.
- **[Сценарии использования](./scenarios.md)** — подробный разбор практических кейсов.
- **[Реализация в коде](./implementation.md)** — паттерны программирования и использование OpenFeature.
- **[Feature Flags в GitOps](../../GitOps/Concepts/feature_flags_gitops.md)** — декларативное управление через Git.

### Внешние ресурсы
- [Feature Toggles (Martin Fowler)](https://martinfowler.com/articles/feature-toggles.html) — классика.
- [OpenFeature Standard](https://openfeature.dev/) — унифицированный API.
- [Uber Piranha Documentation](https://github.com/uber/piranha) — автоматизация удаления кода.

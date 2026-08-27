# Антипаттерны Feature Toggles

## Определения

**Антипаттерн Feature Toggle** — это распространенный, но неэффективный, опасный или трудноподдерживаемый способ использования механизмов динамического управления функциональностью. Антипаттерны приводят к накоплению технического долга, усложнению кодовой базы («спагетти-логика»), деградации производительности и возникновению критических инцидентов в Production, которые трудно диагностировать из-за вариативности состояний системы.

**Зомби-флаг (Zombie Flag)** — «мертвый» или забытый флаг, код которого остается в системе после завершения его жизненного цикла, создавая риск случайного включения устаревшей и непротестированной логики.

---

## Предварительные требования

Для освоения и применения практик обнаружения и устранения антипаттернов необходимы следующие инструменты и окружение.

### Инструментарий

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **FFaaS платформа** | Хранение и управление флагами (Unleash, Flipt, Flagsmith) | Unleash v5+ / Flipt v1.35+ |
| **OpenFeature SDK** | Унифицированный API для проверки флагов в коде | v0.4+ (Python/Go/Java) |
| **Linter / Static Analyzer** | Обнаружение неиспользуемых и дублирующих флагов в коде | RuboCop (Ruby), ESLint (JS), Ruff (Python) |
| **Uber Piranha** | Автоматическое обнаружение и удаление «мёртвых» флагов | v0.25+ |
| **Prometheus + Grafana** | Мониторинг использования флагов и их влияния на метрики | Prometheus v2.50+, Grafana v10+ |
| **OpenTelemetry Collector** | Сбор и передача телеметрии по состоянию флагов | v0.95+ |
| **CI/CD пайплайн** | Автоматический прогон тестов при изменении флагов | GitHub Actions / GitLab CI / Jenkins |

### Окружение для тестирования антипаттернов

Для безопасной проверки антипаттернов и их влияния рекомендуется выделить тестовое окружение, изолированное от Production:

```bash
# Локальный Unleash через Docker (для тестирования)
docker compose -f docker-compose.unleash.yml up -d
# → Unleash доступен на http://localhost:4242

# Проверка доступности
curl -s http://localhost:4242/api/admin/user | jq
# → {"user":{"permissions":["admin"]},...}
```

### Базовые знания

Перед изучением антипаттернов рекомендуется ознакомиться с:
- Общими принципами Feature Toggles ([Обзор](./overview.md))
- Классификацией флагов по типам ([Типы](./types.md))
- Архитектурой систем управления флагами ([Архитектура](./architecture.md))

---

## Основные концепции

### Категории антипаттернов

В 2026 году классификация антипаттернов расширена за счет FinOps и SecOps аспектов.

| Категория | Описание | Основной риск |
| :--- | :--- | :--- |
| **Кодовые** | Нарушение чистоты кода и абстракций. | Рост сложности поддержки, ошибки при рефакторинге. |
| **Эксплуатационные** | Ошибки мониторинга и управления рантаймом. | Непредсказуемое поведение при отказе FFaaS, "мертвые" флаги. |
| **Архитектурные** | Ошибки проектирования системных взаимодействий. | Нарушение безопасности, деградация БД, коллизии логики. |
| **Процессные** | Отсутствие владения и регламентов удаления. | Бесконечный рост технического долга. |

### Метрики для обнаружения антипаттернов

Для систематического выявления проблем с флагами используются следующие показатели:

| Метрика | Формула / Метод | Пороговое значение (типичное) |
| :--- | :--- | :--- |
| **Flag Count** | `count(flags WHERE state='enabled')` на сервис | >10 release-флагов на сервис |
| **Flag Age** | `now() - created_at` для каждого флага | >30 дней без изменения состояния |
| **Evaluation Latency** | `p99(feature_flag_evaluation_duration_seconds)` | >10ms на одну оценку |
| **Dead Flag Ratio** | `flags_stuck_at_100% / total_flags` | >20% флагов в одном состоянии >90 дней |
| **Collision Potential** | Количество флагов, влияющих на один ресурс | >2 флага на один ресурс |

---

## Практические сценарии

### 1. Избыточная сложность и вложенность (Combinatorial Explosion)

**Проблема:** Создание условий, зависящих от комбинации нескольких независимых флагов или использование глубокой вложенности (`if inside if`). Это приводит к экспоненциальному росту количества состояний системы, которые невозможно полностью протестировать.

**Почему это антипаттерн:** 10 независимых бинарных флагов дают 1024 состояния системы. Полное тестирование всех комбинаций невозможно, что приводит к необнаруженным ошибкам в Production.

**Пример (Bad Practice):**
```python
# Попытка охватить все варианты ведет к ошибкам
if ff.is_enabled('new-ui') and not ff.is_enabled('legacy-backend'):
    if ff.is_enabled('experiment-alpha'):
        render_complex_view()
```

**Пример с конфигурацией (Bad Practice):**
```yaml
# Unleash: неправильная настройка — зависимые флаги без контроля
flags:
  new-ui:
    enabled: true
  legacy-backend:
    enabled: true  # Конфликтует с new-ui, но нет guard-условия
  experiment-alpha:
    enabled: true  # Зависит от new-ui, но не имеет.dependencies
```

**Решение:**
- Стремитесь к плоской структуре.
- Используйте **Dependency Toggling**: настраивайте зависимости флагов на уровне панели управления (например, в Unleash флаг B активен только если флаг A включен).
- Выносите сложную логику принятия решений в стратегии (Strategy Pattern).

**Реализация Dependency Toggling в Unleash:**
```bash
# Создание зависимого флага через Unleash API
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "experiment-alpha",
    "type": "experiment",
    "description": "A/B-тест нового алгоритма, зависит от new-ui"
  }'

# Настройка constraints: флаг активен ТОЛЬКО если new-ui включен
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/experiment-alpha/environments/production/variants" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "constraints": [
      {
        "contextName": "environment",
        "operator": "IN",
        "values": ["production"],
        "invert": false
      }
    ]
  }'
```

**Код с правильной архитектурой:**
```python
# Плоская структура: одна точка принятия решения
def render_view(ff_client, user_context):
    """Единая точка выбора стратегии рендеринга."""
    strategies = {
        "new-ui": render_modern_view,
        "legacy-ui": render_legacy_view,
    }
    
    strategy_name = ff_client.get_string_value(
        "ui-strategy", 
        default="legacy-ui",
        context=user_context
    )
    return strategies[strategy_name](user_context)
```

**Валидация:** Количество одновременно активных release-флагов на сервис не должно превышать 5-10. Проверка:
```bash
# Подсчет активных флагов через Unleash API
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production" and .enabled == true)] | length'
# → Ожидаемое значение: ≤10
```

---

### 2. Утечка бизнес-логики (Logic Leakage)

**Проблема:** Проверка флага разбросана по всему коду приложения вместо того, чтобы быть инкапсулированной в абстракцию. В коде появляются десятки `if/else` с проверкой одного и того же флага, что усложняет рефакторинг и тестирование.

**Почему это антипаттерн:** При изменении логики флага (например, при его удалении) необходимо найти и изменить десятки файлов, что приводит к ошибкам и неполным удалениям.

**Пример (Bad Practice):**
```python
# Флаг проверяется в 10+ местах — невозможно гарантировать согласованность
def render_header():
    if ff.is_enabled('new-nav'):
        return new_nav_html()
    return legacy_nav_html()

def render_sidebar():
    if ff.is_enabled('new-nav'):
        return new_sidebar_html()
    return legacy_sidebar_html()

def render_footer():
    if ff.is_enabled('new-nav'):
        return new_footer_html()
    return legacy_footer_html()

# ... и ещё 7 мест с проверкой того же флага
```

**Решение:** Используйте паттерн «Обертка» или внедрение зависимостей (DI). Код не должен спрашивать «Включена ли фича X?», он должен вызывать метод интерфейса, реализация которого определяется состоянием флага. См. **[Реализация в коде](./implementation.md)**.

**Реализация через Strategy Pattern:**
```python
from abc import ABC, abstractmethod

class NavigationRenderer(ABC):
    @abstractmethod
    def render_header(self) -> str: pass
    
    @abstractmethod
    def render_sidebar(self) -> str: pass
    
    @abstractmethod
    def render_footer(self) -> str: pass

class LegacyNavigation(NavigationRenderer):
    def render_header(self) -> str:
        return render_legacy_header()
    def render_sidebar(self) -> str:
        return render_legacy_sidebar()
    def render_footer(self) -> str:
        return render_legacy_footer()

class ModernNavigation(NavigationRenderer):
    def render_header(self) -> str:
        return render_new_header()
    def render_sidebar(self) -> str:
        return render_new_sidebar()
    def render_footer(self) -> str:
        return render_new_footer()

# Одна точка переключения — вся навигация меняется атомарно
def get_navigation(ff_client, user_context) -> NavigationRenderer:
    if ff_client.get_boolean_value("new-nav", False, context=user_context):
        return ModernNavigation()
    return LegacyNavigation()
```

**Валидация:** Проверка, что флаг проверяется не более чем в 2-3 местах кода:
```bash
# Поиск всех проверок конкретного флага в кодовой базе
rg "is_enabled\(['\"]new-nav['\"]\)" --type py | wc -l
# → Ожидаемое значение: ≤3 (в сервисе и в DI-контейнере)
```

---

### 3. "Зомби-флаги" и отсутствие владения

**Проблема:** Флаги без назначенного владельца (Owner) и даты удаления. Код превращается в кладбище условий, которые никто не решается удалить.

**Почему это антипаттерн:** Зомби-флаги создают иллюзию «на случай, если понадобится», но на практике их устаревшая логика тестируется и поддерживается, увеличивая стоимость изменений.

**Пример (Bad Practice):**
```python
# Флаг создан 2 года назад, owner уволился, код не менялся
if ff.is_enabled('old-recommendation-engine'):
    # Логика, которая больше не нужна — но её никто не удаляет
    return old_recommender.get_recommendations(user_id)
return new_recommender.get_recommendations(user_id)
```

**Решение:**
- Каждому флагу — **Owner** (команда или конкретный инженер).
- **TTL (Time to Live)**: Автоматические алерты, если флаг не менял состояние более 30 дней.
- **Cleanup-спринты**: Регулярное удаление кода завершенных релизов.
- Использование инструментов типа **Uber Piranha** для автоматизации удаления кода.

**Настройка мониторинга зомби-флагов:**

```yaml
# Prometheus: алерт на флаги без изменений >30 дней
groups:
  - name: flag-hygiene
    rules:
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
```

**Автоматический cleanup через Uber Piranha:**
```bash
# Сканирование кодовой базы на «мёртвые» флаги
# Piranha ищет флаги, которые включены на 100% времени
piranha \
  --project-dir ./src \
  --language java \
  --flag dead-feature-flag \
  --url "" \
  --statesFile ""
# → Генерирует diff с предложениями удаления if/else блоков
```

**Процесс удаления зомби-флагов:**
1. Обнаружение через алерт Prometheus или Piranha.
2. Проверка метрик: если флаг включен на 100% >14 дней без инцидентов — кандидат на удаление.
3. Создание cleanup-PR с удалением кода флага и самого флага из FFaaS.
4. Ревью и мерж — cleanup-PR обязателен в Definition of Done.

**Валидация:** Количество флагов с TTL >30 дней без изменений:
```bash
# Проверка через API Unleash (все флаги с lastSeen >30 дней)
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(
    (.stages[]? | select(.name == "production" and .enabled == true)) and
    ((now - (.createdAt | fromdateiso8601)) > (30 * 86400))
  )] | length'
# → Ожидаемое значение: 0 (все старые флаги удалены)
```

---

### 4. Флаги как замена авторизации (Security Auth Anti-pattern)

**Проблема:** Использование Feature Toggles для ограничения доступа к функционалу на основе прав пользователей (RBAC) без интеграции с IAM-системой.

**Риск:** Флаги функций не предназначены для обеспечения безопасности. Злоумышленник может подменить контекст на клиенте и получить доступ к скрытой функции.

**Пример (Bad Practice):**
```python
# Опасно: флаг проверяется ТОЛЬКО на клиенте
# Злоумышленник может отправить запрос с user_id администратора
def get_admin_panel(user_id, is_admin):
    if ff.is_enabled('admin-panel', context={"is_admin": is_admin}):
        return render_admin_panel()
    return render_user_panel()
```

**Решение:** Флаги управляют *наличием* функции, а IAM/RBAC — *правом* на её использование. Секреты и доступы должны проверяться через **[Vault](../../Vault/overview.md)**.

**Правильная реализация:**
```python
# Безопасно: RBAC проверяется через IAM, флаг управляет только наличием функции
def get_admin_panel(user_id):
    # 1. Проверка авторизации через IAM (обязательно)
    if not iam_client.verify_permission(user_id, "admin:access"):
        raise ForbiddenError("Access denied")
    
    # 2. Проверка наличия функции через флаг (опционально)
    if not ff_client.is_enabled('admin-panel'):
        return render_user_panel()  # Функция не deployed
    
    return render_admin_panel()
```

**Валидация:** Проверка, что флаги разрешений не используются как единственный механизм доступа:
```bash
# Поиск кода с проверкой флагов разрешений без IAM
rg "is_enabled\(['\"]admin" --type py -A5 | grep -v "iam_client\|rbac\|verify_permission"
# → Не должно быть результатов (все проверки флагов разрешений должны сопровождаться IAM)
```

---

### 5. Бесшумный отказ и опасные фолбеки (Silent Failure)

**Проблема:** Использование `false` как значения по умолчанию для критически важных операционных флагов (например, Kill Switch) без учета их семантики.

**Пример:** Если FFaaS недоступна, флаг `enable-firewall` возвращает `false`, отключая защиту.

**Пример (Bad Practice):**
```python
# Критическая ошибка: fail-safe значение отключает защиту
def check_request(request):
    # Если FFaaS упала — флаг вернет False → файервол ОТКЛЮЧЕН
    if ff.is_enabled("enable-waf-protection"):
        validate_request(request)
    return process(request)  # Без валидации!
```

**Решение:** Тщательно выбирайте **Default Value**. Для Kill Switch значение по умолчанию должно соответствовать самому безопасному состоянию системы.

**Правильная реализация с Fail-safe:**
```python
def check_request(request):
    # Fail-safe: по умолчанию защита ВКЛЮЧЕНА (True)
    # Только явное отключение флага отключает проверку
    protection_enabled = ff_client.get_boolean_value(
        "enable-waf-protection", 
        default=True  # ← Критически важно: True = защита активна при сбое FFaaS
    )
    
    if protection_enabled:
        validate_request(request)
    return process(request)
```

**Конфигурация флага в Unleash с правильным дефолтом:**
```bash
# Kill Switch флаг: defaultVariant должен быть "enabled" (защита активна)
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/features/enable-waf-protection" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "ops",
    "description": "Kill Switch для WAF-защиты. По умолчанию: ВКЛЮЧЕНА",
    "variants": [
      {"name": "enabled", "weight": 100},
      {"name": "disabled", "weight": 0}
    ],
    "defaultVariant": "enabled"
  }'
```

**Валидация:** Проверка fail-safe значений для критических флагов:
```bash
# Проверка значений по умолчанию для Kill Switch флагов
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.type == "ops") | {
    name: .name,
    defaultVariant: .variants[0].name,
    enabled: .stages[]?.enabled
  }]'
# → Kill Switch флаги должны иметь defaultVariant = "enabled" (защита активна)
```

---

### 6. Коллизии флагов (Toggle Collision)

**Проблема:** Два независимых флага влияют на один и тот же глобальный ресурс (например, переменную окружения или запись в БД) в несовместимых режимах.

**Пример (Bad Practice):**
```python
# Два флага модифицируют одну переменную — результат непредсказуем
def process_payment(amount):
    if ff.is_enabled("apply-discount"):
        amount = amount * 0.9  # -10%
    
    if ff.is_enabled("apply-surchage"):
        amount = amount * 1.05  # +5%
    
    # Если оба флага активны: amount = amount * 0.9 * 1.05 = amount * 0.945
    # Разработчик预期 только одну модификацию, но получает комбинированную
    return charge(amount)
```

**Решение:**
- Группировка флагов по доменам.
- Конфликт-тестирование: проверка работы системы при всех комбинациях активных флагов в данном домене.

**Реализация контроля коллизий:**
```python
# Группировка флагов по доменам с явным приоритетом
class PricingFlags:
    """Централизованный контроль всех флагов, влияющих на цену."""
    
    def __init__(self, ff_client):
        self.ff = ff_client
    
    def get_price_modifier(self, user_context) -> float:
        """Возвращает итоговый множитель цены (только один флаг за раз)."""
        modifiers = []
        
        if self.ff.get_boolean_value("discount-10-percent", False, user_context):
            modifiers.append(("discount", 0.9))
        
        if self.ff.get_boolean_value("surcharge-5-percent", False, user_context):
            modifiers.append(("surcharge", 1.05))
        
        # Контроль: только одна модификация за раз
        if len(modifiers) > 1:
            logger.warning(
                f"Price collision detected: {modifiers}. "
                f"Using first applicable modifier only."
            )
            modifiers = [modifiers[0]]
        
        if modifiers:
            return modifiers[0][1]
        return 1.0  # Без модификаций
```

**Валидация:** Тестирование всех комбинаций активных флагов в домене:
```bash
# Конфликт-тест: проверка что два флага цены не активны одновременно
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production" and .enabled == true) | .name] | 
    map(select(test("discount|surcharge|pricing"))) | 
    if length > 1 then "COLLISION RISK: \(length) pricing flags active" else "OK: \(length) pricing flags" end'
# → Ожидаемое: "OK: 0-1 pricing flags"
```

---

### 7. Неконсистентность окружений (Environment Drift)

**Проблема:** Ручное управление флагами приводит к тому, что в `Dev`, `Staging` и `Prod` включены разные наборы экспериментальных флагов, что делает невозможным воспроизведение багов.

**Пример (Bad Practice):**
```bash
# В Dev: флаг A включен, флаг B выключен
# В Staging: флаг A выключен, флаг B включен
# В Prod: оба флага выключены
# → Баг, который возникает только при комбинации A+B, невозможно воспроизвести в staging
```

**Решение:**
- Декларативное управление через GitOps.
- Синхронизация состояний флагов между окружениями для отладки конкретных инцидентов.

**Реализация через GitOps (ConfigMap в Kubernetes):**
```yaml
# production-flags.yaml — единый источник для Production
apiVersion: v1
kind: ConfigMap
metadata:
  name: feature-flags-production
  namespace: billing
data:
  flags.json: |
    {
      "flags": {
        "new-checkout": {
          "enabled": true,
          "defaultVariant": "on"
        },
        "legacy-recommendations": {
          "enabled": false,
          "defaultVariant": "off"
        }
      }
    }
```

```yaml
# staging-flags.yaml — staging ДОЛЖЕН повторять production для отладки
apiVersion: v1
kind: ConfigMap
metadata:
  name: feature-flags-staging
  namespace: billing
data:
  flags.json: |
    {
      "flags": {
        "new-checkout": {
          "enabled": true,         # ← Идентично production
          "defaultVariant": "on"
        },
        "legacy-recommendations": {
          "enabled": false,        # ← Идентично production
          "defaultVariant": "off"
        }
      }
    }
```

**Автоматическая синхронизация через CI:**
```bash
# Сравнение флагов между средами ( часть CI-пайплайна)
#!/bin/bash
PROD_FLAGS=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | jq -r '.features[].name | sort')
STAGING_FLAGS=$(curl -s "$UNLEASH_STAGING_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_STAGING_TOKEN" | jq -r '.features[].name | sort')

DIFF=$(diff <(echo "$PROD_FLAGS") <(echo "$STAGING_FLAGS"))
if [ -n "$DIFF" ]; then
    echo "WARNING: Environment drift detected!"
    echo "$DIFF"
    exit 1
fi
```

**Валидация:** Ежедневная проверка соответствия флагов между средами:
```bash
# Prometheus: алерт на расхождение флагов между средами
groups:
  - name: environment-sync
    rules:
      - alert: EnvironmentDriftDetected
        expr: |
          count by (flag_name) (
            feature_flag_state{environment="production"} != feature_flag_state{environment="staging"}
          ) > 0
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Флаг {{ $labels.flag_name }} различается между Prod и Staging"
```

---

### 8. Управление схемой БД через флаги

**Проблема:** Попытка изменять структуру БД (миграции) внутри логических условий флага.

**Риск:** Разрыв между состоянием кода и схемы БД, невозможность отката.

**Пример (Bad Practice):**
```python
# Опасно: миграция схемы внутри if/else
def migrate_data():
    if ff.is_enabled("new-schema"):
        # Эта миграция выполняется ТОЛЬКО при включенном флаге
        db.execute("ALTER TABLE users ADD COLUMN preferences_v2 JSONB")
        db.execute("UPDATE users SET preferences_v2 = preferences::jsonb")
    else:
        # Старая логика
        pass
```

**Решение:** Применяйте паттерн **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**. Флаг управляет только логикой *чтения/записи* данных, но не самой структурой таблиц.

**Правильная реализация:**
```python
# Миграция вынесена в отдельный процесс (flyway/liquibase)
# Флаг управляет ТОЛЬКО логикой чтения/записи
def get_user_preferences(user_id):
    if ff_client.is_enabled("use-new-preferences-schema"):
        # Чтение из новой колонки (миграция уже выполнена)
        return db.query("SELECT preferences_v2 FROM users WHERE id = %s", user_id)
    else:
        # Чтение из старой колонки
        return db.query("SELECT preferences FROM users WHERE id = %s", user_id)
```

**Валидация:** Проверка, что флаги не содержат DDL-команд:
```bash
# Поиск DDL-команд в контексте флагов
rg "ALTER|CREATE TABLE|DROP COLUMN|ADD COLUMN" --type py -B5 -A5 | grep -i "is_enabled\|get_boolean"
# → Не должно быть результатов
```

---

### 9. Избыточная частота опроса (Polling Overload)

**Проблема:** SDK настроен на слишком частый опрос FFaaS сервера, создавая избыточную нагрузку на сеть и платформу флагов. При Thousands инстансов приложения каждый опрос генерирует десятки тысяч HTTP-запросов в минуту.

**Почему это антипаттерн:** Избыточный трафик деградирует FFaaS, увеличивает latency оценки флагов и может привести к rate-limiting.

**Пример (Bad Practice):**
```python
# SDK опрашивает сервер каждую секунду — катастрофа при 500 инстансах
api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service",
    polling_interval=1,  # ← 1 секунда = 500 * 60 = 30,000 запросов в минуту
    refresh_interval=1
))
```

**Решение:** Используйте SSE (Server-Sent Events) или gRPC streaming вместо polling. Если polling необходим — увеличьте интервал до 30-60 секунд и используйте локальный кеш.

**Правильная конфигурация:**
```python
# SSE: мгновенные обновления без опроса
api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service",
    # SSE streaming: обновления приходят по событию, без опроса
    enable_sse=True,
    # Fallback на polling если SSE недоступен
    polling_interval=60,  # 1 минута как запасной вариант
    # Локальный кеш: оценка без сетевого вызова
    enable_local_cache=True,
    cache_ttl=300  # 5 минут
))
```

**Валидация:** Мониторинг частоты запросов к FFaaS:
```bash
# Prometheus: количество запросов к FFaaS в минуту
sum(rate(http_requests_total{job="unleash-api"}[1m]))
# → Ожидаемое: <100 запросов/мин (при 500 инстансах с polling 60s = ~8 запросов/мин)
```

---

### 10. Отсутствие мониторинга влияния флагов (Monitoring Gap)

**Проблема:** Флаги включаются без настройки наблюдаемости. Нет возможности определить, влияет ли флаг на ошибки, латентность или бизнес-метрики.

**Почему это антипаттерн:** Без мониторинга невозможно определить, безопасен ли флаг, и принять решение о его удалении или раскатке.

**Пример (Bad Practice):**
```python
# Флаг включен, но никто не следит за его влиянием
def render_checkout(user):
    if ff.is_enabled("new-checkout-flow"):
        return render_new_checkout(user)
    return render_legacy_checkout(user)
# Нет телеметрии, нет дашборда, нет алертов
```

**Решение:** Каждое включение флага должно сопровождаться настройкой дашборда и алертов. Используйте **[OpenTelemetry](./implementation.md)** для инъекции состояния флагов в спаны.

**Реализация наблюдаемости:**
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def render_checkout(user):
    with tracer.start_as_current_span("checkout_render") as span:
        is_new_flow = ff_client.get_boolean_value(
            "new-checkout-flow", False, 
            context={"user_id": user.id}
        )
        
        # Инъекция состояния флага в спан
        span.set_attribute("feature_flag.new_checkout_flow", is_new_flow)
        
        if is_new_flow:
            result = render_new_checkout(user)
            span.set_attribute("checkout.variant", "new")
        else:
            result = render_legacy_checkout(user)
            span.set_attribute("checkout.variant", "legacy")
        
        return result
```

**Настройка дашборда Grafana:**
```json
{
  "panels": [
    {
      "title": "Checkout Error Rate by Flag State",
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{service=\"checkout\",status=~\"5..\"}[5m])) by (feature_flag) / sum(rate(http_requests_total{service=\"checkout\"}[5m])) by (feature_flag)",
          "legendFormat": "{{feature_flag}}"
        }
      ]
    }
  ]
}
```

**Валидация:** Проверка наличия телеметрии по каждому флагу:
```bash
# Проверка наличия атрибутов флагов в спанах (через Tempo/Jaeger)
curl -s "http://localhost:3200/api/traces?query=feature_flag.new_checkout_flow&limit=1" | \
  jq '.traces[0].spans[] | select(.attributes | map(select(.key == "feature_flag.new_checkout_flow")) | length > 0) | .traceID'
# → Должен вернуть traceID (означает что атрибут присутствует)
```

---

## Валидация и проверка решений

### Чек-лист обнаружения антипаттернов

| Проверка | Метод | Ожидаемый результат |
| :--- | :--- | :--- |
| Количество активных флагов на сервис | API-запрос к FFaaS + jq | ≤10 release-флагов |
| Флаги с TTL >30 дней без изменений | Prometheus: `time() - flag_last_change_timestamp > 30d` | 0 флагов |
| Количество проверок одного флага в коде | `rg "is_enabled('flag-name')" \| wc -l` | ≤3 проверки |
| Fail-safe значения для Kill Switch | Проверка `defaultVariant` в FFaaS | Kill Switch: `defaultVariant = "enabled"` |
| Конфликт-тест для доменных флагов | Автоматизированный тест комбинаций | Нет двух активных флагов на один ресурс |
| Наличие телеметрии по флагу | Проверка атрибутов спанов OTel | Атрибут `feature_flag.*` присутствует |
| Соответствие флагов между средами | CI-пайплайн сравнения FFaaS | Prod = Staging (для отладки) |
| DDL-команды в контексте флагов | `rg "ALTER\|CREATE TABLE" -B5 -A5 \| grep is_enabled` | 0 результатов |

### Автоматизация проверок (CI/CD)

```yaml
# .github/workflows/flag-hygiene.yml
name: Feature Flag Hygiene
on:
  schedule:
    - cron: '0 9 * * 1'  # Каждый понедельник в 9:00

jobs:
  flag-audit:
    runs-on: ubuntu-latest
    steps:
      - name: Check flag count
        run: |
          FLAGS=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
            -H "Authorization: $UNLEASH_ADMIN_TOKEN" | jq '.features | length')
          if [ "$FLAGS" -gt 10 ]; then
            echo "ERROR: Too many active flags ($FLAGS > 10)"
            exit 1
          fi

      - name: Check zombie flags
        run: |
          ZOMBIES=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
            -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
            jq '[.features[] | select(
              (.stages[]? | select(.enabled == true)) and
              ((now - (.createdAt | fromdateiso8601)) > (30 * 86400))
            )] | length')
          if [ "$ZOMBIES" -gt 0 ]; then
            echo "WARNING: $ZOMBIES zombie flags detected"
            exit 1
          fi

      - name: Check environment drift
        run: |
          # Сравнение флагов между prod и staging
          DIFF=$(diff <(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
            -H "Authorization: $UNLEASH_ADMIN_TOKEN" | jq -r '.features[].name | sort') \
            <(curl -s "$UNLEASH_STAGING_URL/api/admin/projects/default/features" \
            -H "Authorization: $UNLEASH_STAGING_TOKEN" | jq -r '.features[].name | sort'))
          if [ -n "$DIFF" ]; then
            echo "ERROR: Environment drift detected"
            echo "$DIFF"
            exit 1
          fi
```

---

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Вероятная причина | Диагностические действия | Решение |
| :--- | :--- | :--- | :--- |
| Флаг не переключается через UI | SDK кеширует старое значение | `curl $UNLEASH_URL/api/client/features` → проверить актуальность; `tcpdump -i any port 4242` → проверить соединение SDK | Убедиться, что SDK настроен на SSE/polling с корректным `maxAge`; проверить `refreshInterval` в конфигурации провайдера |
| Приложение падает при недоступности FFaaS | Отсутствие fail-safe значений по умолчанию | Остановить FFaaS сервер → попробовать запросить приложение; `grep "is_enabled" src/` → найти все проверки без default | Каждая проверка флага обязана содержать fallback-значение: `get_boolean_value("flag", False)` |
| Флаги живут годами, код оброс ветвлениями | Нет процесса удаления | `rg "is_enabled" --type py \| wc -l` → подсчет проверок; проверить возраст флагов через API | Expiration-даты, cleanup-PR обязательным пунктом Definition of Done, лимит активных флагов на сервис |
| Тесты взрываются от числа комбинаций | Все фLAGи тестируются во всех сочетаниях | `time pytest tests/` → проверить время тестирования; посмотреть CI-логи | CI гоняет дефолтную конфигурацию; комбинации — точечные e2e только для активных раскаток |
| Оценка флага добавляет latency | Ход в удаленную платформу на каждый вызов | `curl -w "@curl-format.txt" -o /dev/null -s $UNLEASH_URL/api/client/features` → замерить latency | Локальный flagd/sidecar, кеширование провайдера; платформа — источник истины, не hot path |
| Прод ведет себя не как staging | Разные значения флагов в средах | `diff <(prod-flags) <(staging-flags)` → найти расхождения; `curl` к обоим API | Декларативное управление через GitOps; diff флагов между средами — часть ревью PR |
| Утечка экспериментального функционала | Флаг доступен всем пользователям без сегментации | `curl $UNLEASH_URL/api/admin/projects/default/features/flag-name` → проверить targeting rules | Настроить targeting rules: флаг доступен только определенным сегментам (staff, beta, определенный регион) |
| Неконсистентность данных при Dual Write | Флаг переключил запись до завершения Backfill | Проверить метрики расхождений: `SELECT count(*) FROM old_table WHERE id NOT IN (SELECT id FROM new_table)` | Расширенный паттерн Expand-Contract: флаг управляет только логикой чтения/записи, но не структурой таблиц |
| Включили фLAG — а миграции БД нет | Функциональность завязана на схему | Проверить доступность колонки: `psql -c "\d users"` →是否存在 preferences_v2 | Expand-contract: схема совместима с обоими путями кода; контракт-фаза удаляется после стабилизации |
| Secret попал в конфиг флага | Флаговый конфиг используют как конфиг приложения | `rg "password\|secret\|token" $UNLEASH_URL/api/admin/projects/default/features/flag-name` | Запретить политикой (conftest/Kyverno); секреты — только через ESO/SOPS |

---

## Ограничения и особые случаи (Edge Cases)

### Когда Feature Toggles НЕ подходят

- **Простые CRUD-приложения** без альтернативных веток логики — Overhead от инфраструктуры флагов не окупается.
- **Критические пути с нулевой容忍 к latency** — каждая проверка флага добавляет вычисления (хотя и `O(1)` при локальном вычислении). В high-frequency trading или real-time bidding этот overhead может быть неприемлем.
- **Замена системы авторизации** — флаги не предназначены для обеспечения безопасности. Злоумышленник может подменить контекст на клиенте.

### Ограничения по архитектуре

- **Комбинаторный взрыв:** 10 независимых бинарных флагов дают 1024 состояния системы. Необходимо ограничивать количество одновременно активных релизных флагов на сервис (типично: 5-10).
- **Глобальные побочные эффекты:** Если два флага влияют на один глобальный ресурс (переменную окружения, запись в БД) в несовместимых режимах — возникает коллизия. Требуется группировка флагов по доменам и конфликт-тестирование.
- **Миграции БД:** Флаги не должны управлять структурой таблиц. Попытка изменять схему БД внутри логических условий флага приводит к разрыву между состоянием кода и схемы.

### Edge Cases в Production

- **Одновременное включение нескольких экспериментов:** Если два A/B-теста затрагивают один и тот же UI-компонент, результаты могут быть искажены. Необходимо выявлять пересечения и запускать их последовательно или исключать пересекающуюся аудиторию.
- **Кэширование на CDN/Браузере:** Если флаг определяет видимость элемента UI, а страница кэшируется CDN или браузером, пользователь может видеть устаревшее состояние. Решение: не кэшировать страницы с активными флагами или добавлять `Cache-Control: no-cache` для путей с флагами.
- **Offline-режим (Mobile):** При отсутствии сети SDK не может получить обновленное значение флага. Используйте bootstrap-файл (последнее известное состояние) или hardcoded fallback.

---

## Дополнительная информация

### Техническая гигиена

В 2026 году обязательным является использование **OpenFeature SDK**, что позволяет избежать привязки к вендору и снижает риск возникновения антипаттернов, специфичных для конкретных реализаций.

### Интеграция с Observability для обнаружения антипаттернов

Комбинация Prometheus + OpenTelemetry позволяет автоматически выявлять антипаттерны:

| Антипаттерн | Индикатор в мониторинге | Алерт |
| :--- | :--- | :--- |
| **Зомби-флаги** | `flag_last_change_timestamp` >30 дней | `ZombieFlagDetected` |
| **Коллизии флагов** | 2+ флага влияют на один ресурс | `FlagCollisionDetected` |
| **Polling Overload** | `rate(http_requests_total{job="unleash-api"}[1m])` >100 | `FFaaSOverloaded` |
| **Silent Failure** | `feature_flag_evaluations_total{value="false"}` для Kill Switch | `KillSwitchDefaultRisk` |
| **Monitoring Gap** | Отсутствие `feature_flag.*` атрибутов в спанах | `FlagTelemetryMissing` |

### См. также
- **[Обзор Feature Toggles](./overview.md)** — концептуальная база.
- **[Типы Feature Toggles](./types.md)** — классификация по времени жизни и динамичности.
- **[Лучшие практики](./best_practices.md)** — золотой стандарт управления флагами.
- **[Сценарии использования](./scenarios.md)** — правильные паттерны для подражания.
- **[Реализация в коде](./implementation.md)** — паттерны программирования и OpenFeature.
- **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** — смежные риски безопасности.
- **[Feature Flags в GitOps](../../GitOps/Concepts/feature_flags_gitops.md)** — декларативное управление и предотвращение Environment Drift.

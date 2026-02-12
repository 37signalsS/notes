# Feature Toggles (Feature Flags)

## Определение

**Feature Toggles (Feature Flags)** — это техника в разработке программного обеспечения, позволяющая включать или отключать функциональность приложения во время выполнения без изменения кода и повторного развертывания.

**Ключевая идея:** Отделение деплоя кода от релиза функциональности.

## Зачем нужны Feature Toggles

### Проблемы без Feature Toggles

```
ТРАДИЦИОННЫЙ ПОДХОД (Long-lived branches):

main:     ●────●────●────●────●────●────●────●
           │                   │
feature-A: ●────●────●────●────┘ (merge)
                               
feature-B:      ●────●────●────●────●────┘ (merge - конфликты!)
                                    
feature-C:           ●────●────●────●────●────●── (еще конфликты!)

Проблемы:
- Долгоживущие ветки (weeks/months)
- Сложные merge конфликты
- Интеграционные проблемы
- Отложенное тестирование
```

```
С Feature Toggles (Trunk-based development):

main:     ●────●────●────●────●────●────●────●────●────●
          │    │    │    │    │    │    │    │    │
          A    A    A    A    B    B    B    B    C
          
Все фичи в main, но скрыты:
- feature A: toggle=OFF (в разработке)
- feature A: toggle=ON (в проде)
- feature B: toggle=OFF (в разработке)
- feature B: toggle=ON (в проде)

Преимущества:
- Короткие ветки (hours/days)
- Минимальные конфликты
- Непрерывная интеграция
- Раннее тестирование
```

## Типы Feature Toggles

### 1. Release Toggles (Релизные)

**Назначение:** Скрытие незавершенной функциональности от пользователей

```python
# Пример: Новый payment processor
class PaymentService:
    def process_payment(self, amount, method):
        if feature_flags.is_enabled('new-payment-processor'):
            return self._process_with_new_system(amount, method)
        else:
            return self._process_with_legacy_system(amount, method)
```

**Характеристики:**
- Временные (days to weeks)
- Binary (on/off)
- Для команды разработки
- После стабилизации — удаляются

### 2. Experiment Toggles (Экспериментальные)

**Назначение:** A/B тестирование, канареечные релизы

```python
# Пример: A/B тест нового UI
variant = feature_flags.get_variant('new-checkout-ui', 
                                    user_id=current_user.id,
                                    default='control')

if variant == 'treatment':
    return render_new_checkout_ui()
elif variant == 'control':
    return render_old_checkout_ui()
```

**Характеристики:**
- Длительные (days to months)
- Multi-variant (A/B/C/D)
- На основе пользователя/сессии
- Статистика и аналитика

### 3. Ops Toggles (Операционные)

**Назначение:** Circuit breakers, отключение функций при проблемах

```python
# Пример: Circuit breaker для внешнего API
def fetch_recommendations(user_id):
    if not feature_flags.is_enabled('recommendation-api-enabled'):
        # Fallback на локальные рекомендации
        return get_cached_recommendations(user_id)
    
    try:
        return external_api.get_recommendations(user_id)
    except ExternalAPIError:
        feature_flags.disable('recommendation-api-enabled')
        return get_cached_recommendations(user_id)
```

**Характеристики:**
- Постоянные (средство безопасности)
- Быстрое отключение без деплоя
- Мониторинг и алерты
- Часть операционной практики

### 4. Permission Toggles (Правовые)

**Назначение:** Предоставление функций premium пользователям

```python
# Пример: Premium features
if feature_flags.is_enabled('advanced-analytics', 
                             user=current_user):
    return render_advanced_dashboard()
else:
    return render_basic_dashboard_with_upsell()
```

**Характеристики:**
- Постоянные (part of product)
- User-specific
- Связаны с billing/subscription
- Могут быть перманентными

## Архитектура Feature Toggles

### Компоненты системы

```
┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION                              │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Feature   │  │   Feature   │  │   Feature   │         │
│  │   Toggle    │  │   Toggle    │  │   Toggle    │         │
│  │   Check     │  │   Check     │  │   Check     │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                │
│         └────────────────┼────────────────┘                │
│                          │                                 │
│                   ┌──────▼──────┐                         │
│                   │   Feature   │                         │
│                   │   Toggle    │                         │
│                   │   Client    │                         │
│                   │   (SDK)     │                         │
│                   └──────┬──────┘                         │
└──────────────────────────┼─────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
┌────────▼────────┐ ┌──────▼──────┐ ┌───────▼────────┐
│   Config File   │ │   Database  │ │   External     │
│   (YAML/JSON)   │ │   (Postgres)│ │   Service      │
│                 │ │   MongoDB)  │ │   (LaunchDarkly│
│                 │ │             │ │   Unleash)     │
└─────────────────┘ └─────────────┘ └────────────────┘
```

### Хранение состояния toggles

**1. Файлы конфигурации (для простых случаев):**

```yaml
# features.yaml
features:
  new-checkout:
    enabled: true
    
  dark-mode:
    enabled: false
    users:
      - admin@example.com
      
  beta-feature:
    enabled: true
    percentage: 10  # 10% пользователей
```

**2. База данных (для динамических изменений):**

```sql
CREATE TABLE feature_flags (
    name VARCHAR(255) PRIMARY KEY,
    enabled BOOLEAN DEFAULT false,
    strategy VARCHAR(50), -- 'default', 'userId', 'percentage'
    parameters JSONB,     -- {'userIds': [], 'percentage': 10}
    updated_at TIMESTAMP
);
```

**3. Специализированные сервисы:**

- **LaunchDarkly** — SaaS-решение
- **Unleash** — Open-source self-hosted
- **Split.io** — Enterprise feature management
- **Flagsmith** — Open-source

## Реализация Feature Toggles

### Простая реализация на Python

```python
import yaml
from typing import Dict, Any, Optional

class FeatureFlagManager:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.flags = self.config.get('features', {})
    
    def is_enabled(self, flag_name: str, 
                   context: Optional[Dict[str, Any]] = None) -> bool:
        """Проверить, включен ли toggle"""
        flag = self.flags.get(flag_name, {})
        
        if not flag.get('enabled', False):
            return False
        
        strategy = flag.get('strategy', 'default')
        
        if strategy == 'userId':
            user_id = context.get('user_id') if context else None
            return user_id in flag.get('userIds', [])
        
        elif strategy == 'percentage':
            import hashlib
            user_id = context.get('user_id', 'anonymous')
            hash_val = int(hashlib.md5(
                f"{flag_name}:{user_id}".encode()
            ).hexdigest(), 16)
            return hash_val % 100 < flag.get('percentage', 0)
        
        return True
    
    def get_variant(self, flag_name: str, 
                    context: Optional[Dict[str, Any]] = None,
                    default: str = 'control') -> str:
        """Получить вариант для A/B тестирования"""
        flag = self.flags.get(flag_name, {})
        
        if not flag.get('enabled', False):
            return default
        
        variants = flag.get('variants', [default])
        
        # Консистентное распределение по user_id
        user_id = context.get('user_id', 'anonymous')
        import hashlib
        hash_val = int(hashlib.md5(
            f"{flag_name}:{user_id}".encode()
        ).hexdigest(), 16)
        
        return variants[hash_val % len(variants)]

# Использование
ff_manager = FeatureFlagManager('features.yaml')

# Простая проверка
if ff_manager.is_enabled('dark-mode'):
    enable_dark_mode()

# С контекстом
if ff_manager.is_enabled('beta-feature', 
                          context={'user_id': user.id}):
    show_beta_ui()

# A/B тест
variant = ff_manager.get_variant('new-pricing-page',
                                 context={'user_id': user.id})
render_pricing_page(variant)
```

### Интеграция с Unleash (Open-source)

```python
from UnleashClient import UnleashClient

client = UnleashClient(
    url="https://unleash.mycompany.com/api",
    app_name="my-app",
    custom_headers={'Authorization': 'API_TOKEN'}
)

client.initialize_client()

# Проверка toggle
if client.is_enabled("new-payment-flow", 
                     context={'userId': user.id}):
    process_new_payment()
else:
    process_legacy_payment()

# A/B тест
variant = client.get_variant("checkout-redesign",
                             context={'userId': user.id})
```

## Best Practices

### 1. Naming Convention

```
❌ Плохо:
- flag1
- new_feature
- fix_bug_123

✅ Хорошо:
- checkout-redesign-v2
- payment-stripe-integration
- user-profile-enhancements-2024
```

### 2. Default Values

```python
# ❌ Плохо: неявный default
if feature_flags.is_enabled('critical-fix'):
    apply_fix()

# ✅ Хорошо: явный default
if feature_flags.is_enabled('critical-fix', default=True):
    apply_fix()
```

### 3. Удаление устаревших toggles

```python
# План удаления:
# 1. Feature toggle включен для всех (100%)
# 2. Ждем 1-2 недели (мониторинг)
# 3. Удаляем if/else, оставляем только новый код
# 4. Удаляем toggle из системы

# ❌ Плохо: мертвый код
if feature_flags.is_enabled('old-feature'):
    # Этот код никогда не выполняется
    pass
else:
    do_something()

# ✅ Хорошо: очищенный код
do_something()
```

### 4. Мониторинг

```python
import logging
from datadog import statsd

class MonitoredFeatureFlags:
    def is_enabled(self, flag_name: str, context=None):
        result = self._check_flag(flag_name, context)
        
        # Метрики
        statsd.increment('feature_flag.check', 
                        tags=[f'flag:{flag_name}', 
                              f'result:{result}'])
        
        # Логирование для audit
        logging.info(f"Feature flag check: {flag_name}={result}",
                    extra={'flag_name': flag_name,
                           'result': result,
                           'user_id': context.get('user_id')})
        
        return result
```

### 5. Тестирование

```python
# Тесты должны покрывать оба состояния toggle

def test_checkout_with_new_flow():
    with override_feature_flag('new-checkout-flow', True):
        response = process_checkout()
        assert response.new_ui == True

def test_checkout_with_legacy_flow():
    with override_feature_flag('new-checkout-flow', False):
        response = process_checkout()
        assert response.new_ui == False
```

## Anti-patterns

### 1. Слишком много toggles

```python
# ❌ Плохо: сложная логика
if (ff.is_enabled('feature-a') and 
    ff.is_enabled('feature-b') and 
    not ff.is_enabled('feature-c')):
    do_something()
```

### 2. Вложенные toggles

```python
# ❌ Плохо: сложно понять
if ff.is_enabled('outer-feature'):
    if ff.is_enabled('inner-feature'):
        do_complex_thing()
    else:
        do_simple_thing()
else:
    do_legacy_thing()
```

### 3. Database schema changes внутри toggle

```sql
-- ❌ Плохо: опасно!
-- Миграция должна выполняться всегда
ALTER TABLE users ADD COLUMN new_field VARCHAR(255);
-- Toggle управляет только кодом, не схемой
```

## Практические сценарии

### Сценарий 1: Canary Deployment

```python
# Постепенный rollout новой версии
rollout_percentage = feature_flags.get_value(
    'payment-v2-rollout', 
    default=0
)

user_hash = hash(user.id) % 100
if user_hash < rollout_percentage:
    use_payment_v2()
else:
    use_payment_v1()

# Мониторинг метрик
# Если ошибок < 0.1%, увеличиваем rollout_percentage
```

### Сценарий 2: Kill Switch

```python
# Быстрое отключение проблемной функции
@app.route('/api/recommendations')
def get_recommendations():
    if not feature_flags.is_enabled('recommendations-api'):
        # Fallback: возвращаем популярные товары
        return get_popular_items()
    
    try:
        return ml_service.get_recommendations()
    except MLServiceError:
        # Автоматическое отключение
        feature_flags.emergency_disable('recommendations-api')
        return get_popular_items()
```

### Сценарий 3: Beta Testing

```python
# Доступ к бете для выбранных пользователей
@app.route('/beta/new-dashboard')
@login_required
def beta_dashboard():
    if not feature_flags.is_enabled('beta-dashboard',
                                    context={'user_id': current_user.id}):
        abort(403, "Beta access required")
    
    return render_template('beta/dashboard.html')
```

## Дополнительная информация

- [Feature Toggles by Martin Fowler](https://martinfowler.com/articles/feature-toggles.html)
- [LaunchDarkly Documentation](https://docs.launchdarkly.com/)
- [Unleash Documentation](https://docs.getunleash.io/)
- [Feature Flags on AWS](https://aws.amazon.com/blogs/mt/feature-flags-aws-appconfig/)

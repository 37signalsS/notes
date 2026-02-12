# Best Practices для Feature Toggles

## 1. Naming Convention

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

## 2. Default Values

```python
# ❌ Плохо: неявный default
if feature_flags.is_enabled('critical-fix'):
    apply_fix()

# ✅ Хорошо: явный default
if feature_flags.is_enabled('critical-fix', default=True):
    apply_fix()
```

## 3. Удаление устаревших toggles

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

## 4. Мониторинг

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

## 5. Тестирование

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

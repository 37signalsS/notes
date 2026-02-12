# Типы Feature Toggles

## 1. Release Toggles (Релизные)

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

## 2. Experiment Toggles (Экспериментальные)

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

## 3. Ops Toggles (Операционные)

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

## 4. Permission Toggles (Правовые)

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

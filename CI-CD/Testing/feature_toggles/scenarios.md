# Практические сценарии Feature Toggles

## Сценарий 1: Canary Deployment

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

## Сценарий 2: Kill Switch

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

## Сценарий 3: Beta Testing

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

# Сценарии использования Feature Toggles

### Определения

- **Сценарии использования** — это типовые задачи и проблемы, которые эффективно решаются с помощью техники Feature Toggles.

### Практические сценарии

#### Сценарий 1: Canary Deployment

Постепенный и контролируемый запуск новой функциональности на определенный процент пользователей.

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

#### Сценарий 2: Аварийный выключатель (Kill Switch)

Мгновенное отключение проблемной или нестабильной функции в production без отката всего релиза.

```python
@app.route('/api/recommendations')
def get_recommendations():
    if not feature_flags.is_enabled('recommendations-api', default=True):
        return get_popular_items() # Fallback-логика
    
    # ... основная логика ...
```

#### Сценарий 3: Бета-тестирование

Предоставление доступа к новым функциям ограниченному кругу пользователей (например, внутренним сотрудникам или участникам бета-программы).

```python
@app.route('/beta/new-dashboard')
@login_required
def beta_dashboard():
    # Контекст передает ID пользователя для проверки
    context = {'user_id': current_user.id}
    if not feature_flags.is_enabled('beta-dashboard', context=context):
        abort(403, "Beta access required")
    
    return render_template('beta/dashboard.html')
```

### Дополнительная информация

#### Внешние ресурсы

- [Feature Toggles by Martin Fowler](https://martinfowler.com/articles/feature-toggles.html)
- [LaunchDarkly Documentation](https://docs.launchdarkly.com/)
- [Unleash Documentation](https://docs.getunleash.io/)

#### Связанные документы

- **[Обзор Feature Toggles](./overview.md)** — для понимания базовых концепций.
- **[Типы Feature Toggles](./types.md)** — для выбора правильного типа флага под конкретный сценарий.

# Сценарии использования Feature Toggles

## Определения

- **Сценарии использования** — это типовые задачи и проблемы, которые эффективно решаются с помощью техники Feature Toggles.

---

## Базовые концепции

### Критерии выбора сценария

Выбор сценария зависит от цели и требуемой динамичности управления флагом:

| Цель | Сценарий | Тип флага | Динамичность |
| :--- | :--- | :--- | :--- |
| Постепенный запуск | Canary Deployment | Экспериментальный / Релизный | Высокая |
| Минимизация риска | Аварийный выключатель | Операционный | Критически высокая |
| Ограниченный доступ | Бета-тестирование | Доступный / Релизный | Средняя |
| Проверка гипотез | A/B тестирование | Экспериментальный | Высокая |

### Общие принципы реализации

Все сценарии требуют:

- **Контекстная проверка** — передача атрибутов пользователя (идентификатор (ID), роль, регион) для принятия решений.
- **Безопасные fallback-значения** — предсказуемое поведение при недоступности хранилища флагов.
- **Мониторинг** — логирование проверок и отправка метрик использования.

Детали архитектуры — в документе **[Архитектура систем Feature Toggles](./architecture.md)**, реализация в коде — в документе **[Реализация Feature Toggles](./implementation.md)**.

---

## Практические сценарии

### Сценарий 1: Canary Deployment

Постепенный и контролируемый запуск новой функциональности на определенный процент пользователей.

- **Тип флага:** [Экспериментальный (Experiment Toggle)](./types.md#2-экспериментальные-флаги-experiment-toggles) или [Релизный (Release Toggle)](./types.md#1-релизные-флаги-release-toggles).

**Пример реализации (Python):**

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

Подробнее о стратегии канареечного развертывания — в документе **[Canary Deployment](../../Deployment_Strategies/canary_deployment.md)**.

### Сценарий 2: Аварийный выключатель (Kill Switch)

Мгновенное отключение проблемной или нестабильной функции в production без отката всего релиза.

- **Тип флага:** [Операционный (Ops Toggle)](./types.md#3-операционные-флаги-ops-toggles).

**Пример реализации (Python):**

```python
@app.route('/api/recommendations')
def get_recommendations():
    # Программный интерфейс (API) рекомендаций
    if not feature_flags.is_enabled('recommendations-api', default=True):
        return get_popular_items() # Fallback-логика

    # ... основная логика ...
```

### Сценарий 3: Бета-тестирование

Предоставление доступа к новым функциям ограниченному кругу пользователей (например, внутренним сотрудникам или участникам бета-программы).

- **Тип флага:** [Доступный (Permission Toggle)](./types.md#4-флаги-доступов-permission-toggles) или [Релизный (Release Toggle)](./types.md#1-релизные-флаги-release-toggles).

**Пример реализации (Python):**

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

### Сценарий 4: A/B тестирование

Сравнение двух или более версий одной и той же функциональности для определения, какая из них лучше достигает бизнес-целей (например, конверсии, кликабельности).

- **Тип флага:** [Экспериментальный (Experiment Toggle)](./types.md#2-экспериментальные-флаги-experiment-toggles).

**Пример реализации (Python):**

```python
# Флаг может вернуть вариант 'A', 'B', или 'C'
button_variant = feature_flags.get_variant(
    'new-checkout-button-test',
    context={'user_id': user.id}
)

if button_variant == 'A':
    render_button('blue')
elif button_variant == 'B':
    render_button('green')
else: # Контрольная группа
    render_button('gray')

# Собираем метрики по каждой группе для анализа
statsd.increment(f'checkout.button.shown.{button_variant}')
```

---

## Дополнительная информация

**Связанные документы:**

- **[Обзор Feature Toggles](./overview.md)** — базовые концепции и преимущества.
- **[Типы Feature Toggles](./types.md)** — классификация по назначению и жизненному циклу.
- **[Архитектура систем Feature Toggles](./architecture.md)** — описание компонентов.
- **[Реализация Feature Toggles](./implementation.md)** — примеры встраивания в код.

**Внешние ресурсы:**

- Статья [Feature Toggles by Martin Fowler](https://martinfowler.com/articles/feature-toggles.html).
- Документация [LaunchDarkly](https://docs.launchdarkly.com/).
- Документация [Unleash](https://docs.getunleash.io/).

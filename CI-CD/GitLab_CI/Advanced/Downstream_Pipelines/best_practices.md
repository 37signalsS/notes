# Best Practices — Downstream Pipelines (2025-2026)

## Определения

**Best Practices** — рекомендации по использованию downstream pipelines для обеспечения безопасности, производительности и maintainability.

## Основные концепции

### Ключевые принципы

1. **Используйте `inputs` вместо `variables` (GitLab 17+)**
2. **`strategy: depend` для отчётов**
3. **`strategy: mirror` для синхронизации статусов**
4. **Версионирование шаблонов**
5. **Минимальные права для multi-project pipelines**
6. **Ограничение вложенности**

## Практические сценарии

### 1. Используйте `inputs` вместо `variables` (GitLab 17+)

**Преимущества:**
- Типизированные параметры с валидацией
- Защита от инъекций и несанкционированного изменения

```yaml
# child-pipeline.yml
spec:
  inputs:
    environment:
      options: [staging, production]
      default: staging

# parent-pipeline.yml
deploy:
  trigger:
    include: child.yml
    inputs:
      environment: production
```

### 2. `strategy: depend` для отчётов

- Обязательно для unit-тестов, code quality, security отчётов
- Гарантирует отображение в Merge Request
- Без `strategy: depend` отчёты не появятся в MR

```yaml
test:
  trigger:
    include: tests.yml
    strategy: depend  # Обязательно!
```

### 3. `strategy: mirror` для синхронизации статусов

- Отображает реальный статус downstream в trigger job
- Авто-отмена при провале child pipeline
- Критично для зависимых stages

```yaml
critical-deploy:
  trigger:
    include: deploy.yml
    strategy: mirror
```

### 4. Версионирование шаблонов

- Используйте `ref: 'v1.2.3'` для include из других проектов
- Избегайте поломки при обновлении шаблонов

```yaml
trigger:
  include:
    - project: 'group/ci-templates'
      ref: 'v1.2.3'
      file: 'pipeline.yml'
```

### 5. Минимальные права для multi-project pipelines

- Проверяйте права пользователя на запуск в downstream-проекте
- Используйте Deploy Tokens с ограниченными правами
- Избегайте передачи secret variables

```yaml
# Использование deploy token
deploy:
  trigger:
    project: 'group/production'
    token: $DEPLOY_TOKEN  # Только для конкретной задачи
```

### 6. Ограничение вложенности

- Parent-child: максимум 2 уровня
- Multi-project: без ограничений, но следите за сложностью
- Избегайте глубокой вложенности

### 7. Безопасность

- Не передавайте masked variables в multi-project
- Используйте `inherit: variables: false` когда нужно
- Проверяйте конфиденциальность проектов

```yaml
# Блокировка наследования переменных
secure-trigger:
  trigger:
    include: sensitive.yml
  inherit:
    variables: false
  variables:
    SAFE_VAR: value
```

### 8. Мониторинг и отладка

- Используйте `needs` для управления зависимостями
- Настраивайте timeout для long-running pipelines
- Логируйте upstream/downstream relationships

## Дополнительная информация

### Чеклист перед production

- [ ] Используется `inputs` вместо `variables` (GitLab 17+)
- [ ] `strategy: depend` для всех отчётов
- [ ] `strategy: mirror` для критичных зависимостей
- [ ] Версионирование шаблонов через ref
- [ ] Минимальные права для запуска
- [ ] Нет передачи secret/masked variables
- [ ] Ограничения вложенности соблюдены
- [ ] Настроен мониторинг pipeline status

### Распространённые ошибки

1. Отсутствие `strategy: depend` → отчёты не появляются в MR
2. Передача masked variables в multi-project → утечка данных
3. Глубокая вложенность parent-child → сложность отладки
4. Отсутствие версионирования → поломка при обновлении шаблонов
5. Использование `variables` вместо `inputs` → нет валидации

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Наследование переменных](./variable_inheritance.md)
- [Стратегии выполнения](./strategies.md)

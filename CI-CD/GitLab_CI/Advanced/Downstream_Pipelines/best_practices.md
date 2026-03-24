# Best Practices — Downstream Pipelines (2025-2026)

## Определения

**Best Practices** — рекомендации по использованию downstream pipelines для обеспечения безопасности, производительности и maintainability.

## Основные концепции

### Ключевые принципы

1. **Используйте `inputs` вместо `variables`** (GitLab 17+) — типизированные параметры с валидацией
2. **`strategy: depend` для отчётов** — обязательно для тестов, security, code quality
3. **`strategy: mirror` для синхронизации статусов** — критично для зависимых stages
4. **Версионирование шаблонов** — используйте `ref: 'v1.2.3'` для include
5. **Минимальные права** — Deploy Tokens с ограниченными правами для multi-project
6. **Ограничение вложенности** — parent-child максимум 2 уровня
7. **Безопасность переменных** — блокировка наследования masked variables
8. **Мониторинг** — настройка timeout и логирование upstream/downstream relationships

## Практические сценарии

### 1. Версионирование шаблонов

Используйте `ref` для include из других проектов — избегайте поломки при обновлении шаблонов.

```yaml
trigger:
  include:
    - project: 'group/ci-templates'
      ref: 'v1.2.3'
      file: 'pipeline.yml'
```

### 2. Минимальные права для multi-project pipelines

Проверяйте права пользователя на запуск в downstream-проекте. Используйте Deploy Tokens с ограниченными правами. Избегайте передачи secret variables.

```yaml
deploy:
  trigger:
    project: 'group/production'
    token: $DEPLOY_TOKEN
```

### 3. Ограничение вложенности

- **Parent-child:** максимум 2 уровня вложенности
- **Multi-project:** без ограничений, но следите за сложностью
- Избегайте глубокой вложенности — усложняет отладку

### 4. Безопасность

Не передавайте masked variables в multi-project pipelines — риск unmask и утечки данных. Используйте `inherit: variables: false` для блокировки наследования.

```yaml
secure-trigger:
  trigger:
    include: sensitive.yml
  inherit:
    variables: false
  variables:
    SAFE_VAR: value
```

Проверяйте конфиденциальность проектов при использовании multi-project pipelines.

### 5. Мониторинг и отладка

- Используйте `needs` для управления зависимостями
- Настраивайте timeout для long-running pipelines
- Логируйте upstream/downstream relationships

## Дополнительная информация

### Чеклист перед production

- [ ] Используется `inputs` вместо `variables` (GitLab 17+)
- [ ] `strategy: depend` для всех отчётов
- [ ] `strategy: mirror` для критичных зависимостей
- [ ] Версионирование шаблонов через `ref`
- [ ] Минимальные права для запуска
- [ ] Нет передачи secret/masked variables
- [ ] Ограничения вложенности соблюдены
- [ ] Настроен мониторинг pipeline status

### Распространённые ошибки

1. **Отсутствие `strategy: depend`** — отчёты не появляются в MR
2. **Передача masked variables в multi-project** — утечка данных
3. **Глубокая вложенность parent-child** — сложность отладки
4. **Отсутствие версионирования** — поломка при обновлении шаблонов
5. **Использование `variables` вместо `inputs`** — нет валидации типов

---

**Связанные документы:** [Определения](./definitions.md), [Наследование переменных](./variable_inheritance.md), [Стратегии выполнения](./strategies.md).

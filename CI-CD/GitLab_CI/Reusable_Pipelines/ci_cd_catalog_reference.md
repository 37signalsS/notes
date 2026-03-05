# GitLab CI: Каталог Компонентов — Справочная информация

## Форматы версий для компонентов

| Формат | Пример | Рекомендация |
| :--- | :--- | :--- |
| **SemVer (полный)** | `@1.2.0` | ✅ Для релизов |
| **SemVer (частичный)** | `@1.2` или `@1` | ✅ Для автообновлений |
| **Commit SHA** | `@e3262fd...` | ✅ Для максимальной стабильности |
| **~latest** | `@~latest` | ⚠️ Только если доверяете автору |
| **Ветка** | `@main` | ❌ Не рекомендуется |

**Правила разрешения версий:**

- При совпадении имени тега и SHA — приоритет у SHA
- При совпадении имени тега и ветки — приоритет у тега
- `~latest` не включает pre-release версии (`1.0.1-rc`)

## Валидация компонента

```bash
# Проверка конфигурации компонента
gitlab-ci lint --project=group/ci-components/build-docker

# Проверка использования в проекте
gitlab-ci lint --project=my-group/my-project
```

## Публикация в каталог

**Требования для публикации:**

1. Семантическое версионирование (SemVer)
2. Файл `.gitlab-ci.yml` с `spec:inputs`
3. Созданный GitLab Release с тегом

**Процесс:**

```yaml
# .gitlab-ci.yml в репозитории компонента
release:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: $CI_COMMIT_TAG  # Запуск только при создании тега
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "Component release $CI_COMMIT_TAG"
```

## Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Spec must be a valid json schema` | Пустой `spec:inputs` | Используйте пустой `spec:` без `inputs` |
| `content not found` | Использование `~latest` без релиза | Создайте новый релиз с тегом |
| `invalid input type` | Несоответствие типа в inputs | Проверьте тип значения (string/boolean/number) |
| `regex validation failed` | Значение не соответствует regex | Исправьте значение или regex |

## Связанные документы

- [Обзор переиспользуемых пайплайнов](./overview.md)
- [Механизм `include`](./include_keyword.md)
- [Механизм `extends`](./extends_keyword.md)

## Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [Официальная документация: `spec:inputs`](https://docs.gitlab.com/ci/components/#specinputs)
- [GitLab Components Catalog](https://gitlab.com/explore/catalog)

## Связанные документы (все разделы)

- [Определения](./ci_cd_catalog_definitions.md)
- [Основные концепции](./ci_cd_catalog_concepts.md)
- [Практические сценарии](./ci_cd_catalog_scenarios.md)
- [Ограничения](./ci_cd_catalog_limits.md)

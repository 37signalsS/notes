# GitLab CI: Каталог Компонентов — Справочная информация

## Определения

**Справочная информация** — технические детали, API, CLI-команды и дополнительные материалы по CI/CD Components, не вошедшие в основные концепции.

---

## Основные концепции

### Форматы версий для компонентов

| Формат | Пример | Рекомендация | Когда использовать |
| :--- | :--- | :--- | :--- |
| **SemVer (полный)** | `@1.2.0` | ✅ Для релизов | Продакшен, стабильные версии |
| **SemVer (частичный)** | `@1.2` или `@1` | ✅ Для автообновлений | Dev/staging, автоматические обновления |
| **Commit SHA** | `@e3262fd...` | ✅ Для максимальной стабильности | Критичные системы, audit trail |
| **~latest** | `@~latest` | ⚠️ Только если доверяете автору | Быстрое прототипирование |
| **Ветка** | `@main` | ❌ Не рекомендуется | Локальная разработка (не в production) |

**Правила разрешения версий:**

- При совпадении имени тега и SHA — приоритет у SHA
- При совпадении имени тега и ветки — приоритет у тега
- `~latest` не включает pre-release версии (`1.0.1-rc`, `1.0.0-beta`)
- Частичные версии (`@1.2`) автоматически обновляются до последнего patch

---

## Практические сценарии

### Сценарий 1: Валидация компонента

**Проверка через CLI:**

```bash
# Проверка конфигурации компонента
gitlab-ci lint --project=group/ci-components/build-docker

# Проверка использования в проекте
gitlab-ci lint --project=my-group/my-project

# Развёрнутый вывод с количеством include
gitlab-ci lint --project=my-group/my-project --show-expanded
```

**Проверка через API:**

```bash
# Валидация .gitlab-ci.yml
curl --request POST --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/ci/lint" \
  --data '{"content": "include:\n  - component: ..."}'
```

### Сценарий 2: Публикация компонента в каталог

**Требования для публикации:**

1. Семантическое версионирование (SemVer)
2. Файл `.gitlab-ci.yml` с `spec:inputs` (или пустым `spec:`)
3. Созданный GitLab Release с тегом
4. Проект должен быть видим для потребителей компонента

**Процесс публикации:**

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
    milestones:
      - "v$CI_COMMIT_TAG"
  script:
    - echo "Component published to catalog"
```

**Создание релиза через CLI:**

```bash
# Создание тега
git tag -a v1.0.0 -m "Initial release"
git push origin v1.0.0

# Создание релиза через API
curl --request POST --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/releases" \
  --data "tag_name=v1.0.0&name=Release 1.0.0&description=Initial release"
```

### Сценарий 3: Отладка распространённых ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Spec must be a valid json schema` | Пустой `spec:inputs` | Используйте пустой `spec:` без `inputs` |
| `content not found` | Использование `~latest` без релиза | Создайте новый релиз с тегом |
| `invalid input type` | Несоответствие типа в inputs | Проверьте тип значения (string/boolean/number) |
| `regex validation failed` | Значение не соответствует regex | Исправьте значение или regex |
| `Component not found` | Неправильный путь или нет доступа | Проверьте путь и права доступа к проекту |
| `Version does not follow SemVer` | Тег не соответствует SemVer | Используйте формат `vX.Y.Z` или `X.Y.Z` |

### Сценарий 4: Поиск компонентов в каталоге

**Через UI GitLab:**

1. Перейдите в `CI/CD > Components`
2. Используйте поиск по имени или описанию
3. Фильтруйте по группе или проекту

**Через API:**

```bash
# Получение списка компонентов проекта
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/ci/components"

# Получение конкретного компонента
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/ci/components/<component_name>"
```

---

## Справочная информация

### API-эндпоинты для компонентов

| Метод | Эндпоинт | Описание |
| :--- | :--- | :--- |
| `GET` | `/projects/:id/ci/components` | Список всех компонентов |
| `GET` | `/projects/:id/ci/components/:name` | Информация о компоненте |
| `GET` | `/projects/:id/ci/components/:name/versions` | Версии компонента |
| `POST` | `/projects/:id/ci/lint` | Валидация конфигурации |
| `POST` | `/projects/:id/releases` | Создание релиза |

### CLI-команды

| Команда | Описание |
| :--- | :--- |
| `gitlab-ci lint --project=<path>` | Валидация конфигурации |
| `gitlab-ci lint --show-expanded` | Показать развёрнутый пайплайн |
| `git tag -a vX.Y.Z -m "message"` | Создание тега версии |
| `git push origin vX.Y.Z` | Публикация тега |

### Changelog версий GitLab

| Версия | Изменение |
| :--- | :--- |
| **16.0** | Components как экспериментальная функция |
| **16.2** | Включено по умолчанию (GitLab.com, Self-Managed) |
| **16.9** | Лимит компонентов увеличен с 10 до 30 |
| **16.10** | SemVer обязателен для компонентов каталога |
| **17.0** | General Availability (GA) |
| **17.6** | Component context (experimental) |
| **18.5** | Лимит компонентов увеличен до 100 |
| **18.7** | Component context (GA) |

### Технические ограничения

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| Максимум компонентов на проект | 100 | С GitLab 18.5 |
| Лимит вложенности include | 150 | Все типы include суммируются |
| Максимальный размер `.gitlab-ci.yml` | 1 MB | Включая все include |
| Timeout валидации | 30 сек | Для `gitlab-ci lint` |

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [Официальная документация: `spec:inputs`](https://docs.gitlab.com/ci/components/#specinputs)
- [GitLab Components Catalog](https://gitlab.com/explore/catalog)
- [GitLab API: Components](https://docs.gitlab.com/api/components/)
- [GitLab CLI: ci/lint](https://docs.gitlab.com/cli/ci/lint/)

---

## Связанные документы

- **SSoT:** [GitLab CI: Каталог Компонентов](./ci_cd_catalog_components.md)
- [Определения](./ci_cd_catalog_definitions.md)
- [Концепции](./ci_cd_catalog_concepts.md)
- [Базовые сценарии](./ci_cd_catalog_scenarios.md)
- [Продвинутые сценарии](./ci_cd_catalog_advanced_scenarios.md)
- [Ограничения](./ci_cd_catalog_limits.md)
- [Механизм include](./include_keyword.md)

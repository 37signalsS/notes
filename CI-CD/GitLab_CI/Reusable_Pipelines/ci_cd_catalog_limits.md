# GitLab CI: Каталог Компонентов — Ограничения

## Определения

**Лимит компонентов** — максимальное количество CI/CD Components, которое может содержать один проект GitLab.

**Лимит вложенности include** — максимальное количество директив `include`, которые могут быть обработаны при построении одного пайплайна (включая компоненты, проекты, шаблоны).

**Глобальные ключи** — директивы верхнего уровня (`stages:`, `default:`, `workflow:`), влияющие на весь пайплайн целиком.

---

## Основные концепции

### Таблица ограничений

| Ограничение | Значение | Версия GitLab | Примечание |
| :--- | :--- | :--- | :--- |
| Максимум компонентов на проект | **100** | 18.5+ | До 18.5 — 30 компонента, до 16.9 — 10 компонентов |
| Лимит вложенности include | **150** | Все | Для self-managed настраивается через `ci_max_includes` |
| Глобальные ключи в компоненте | ❌ Запрещены | 16.0+ | `stages:`, `default:`, `workflow:` влияют на весь пайплайн |
| `spec:include` в компоненте | ❌ Запрещено | 16.0+ | Компоненты должны быть самодостаточными |

### Эволюция лимита компонентов

| Версия GitLab | Лимит | Изменение |
| :--- | :--- | :--- |
| 16.0 – 16.8 | 10 | Начальный лимит |
| 16.9 – 18.4 | 30 | Увеличен в 3 раза |
| 18.5+ | 100 | Увеличен в 3.3 раза |

### Запрещённые ключи в компонентах

**Глобальные ключи** запрещены, потому что компоненты должны быть изолированными блоками:

- `stages:` — определяет этапы для всего пайплайна, а не одного компонента
- `default:` — применяет настройки ко всем job, включая внешние
- `workflow:` — управляет созданием пайплайна на уровне проекта

**`spec:include`** запрещено — компоненты не могут подключать внешние файлы, должны быть самодостаточными.

---

## Практические сценарии

### Сценарий 1: Проверка лимита компонентов в проекте

```bash
# Подсчёт количества компонентов в проекте
git ls-files '**/.gitlab-ci.yml' | wc -l

# Проверка через API GitLab
curl --header "PRIVATE-TOKEN: <your_token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/ci/components"
```

### Сценарий 2: Настройка лимита include для self-managed

**Через UI:**

1. `Admin > Settings > CI/CD > General Pipelines`
2. Параметр `Maximum includes` (по умолчанию 150)
3. `Save changes`

**Через API:**

```bash
curl --request PUT --header "PRIVATE-TOKEN: <admin_token>" \
  "https://gitlab.example.com/api/v4/application/settings" \
  --data "ci_max_includes=200"
```

### Сценарий 3: Оптимизация при достижении лимита include

При приближении к 150 include:

- Консолидируйте компоненты (объединяйте связанные job)
- Используйте `!reference` вместо `include:local` для внутренних ссылок
- Избегайте глубокой вложенности компонентов
- Удаляйте неиспользуемые `include`

---

## Справочная информация

### Валидация ограничений

```bash
# Проверка конфигурации на соответствие ограничениям
gitlab-ci lint --project=group/project

# Проверка количества include в пайплайне
gitlab-ci lint --project=group/project --show-expanded
```

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Too many includes` | Превышен лимит 150 | Уменьшите количество `include` или увеличьте лимит (self-managed) |
| `Component limit reached` | Достигнут лимит 100 компонентов | Удалите неиспользуемые компоненты или разделите на проекты |
| `Invalid global key in component` | Использование `stages:`, `default:` в компоненте | Переместите глобальные ключи в корневой `.gitlab-ci.yml` |

### Технические детали

**Лимит 150 include** включает:

- `include:component`
- `include:project`
- `include:local`
- `include:template`
- `include:remote`

**Рекурсивные include** поддерживаются, но учитываются в общем лимите.

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [GitLab Issue: Increase component limit](https://gitlab.com/gitlab-org/gitlab/-/work_items/569158)
- [GitLab Issue: Configurable max includes](https://gitlab.com/gitlab-org/gitlab/-/issues/207270)

---

## Связанные документы

- **SSoT:** [GitLab CI: Каталог Компонентов](./ci_cd_catalog_components.md)
- [Определения](./ci_cd_catalog_definitions.md)
- [Концепции](./ci_cd_catalog_concepts.md)
- [Сценарии использования](./ci_cd_catalog_scenarios.md)
- [Справочная информация](./ci_cd_catalog_reference.md)
- [Механизм include](./include_keyword.md)

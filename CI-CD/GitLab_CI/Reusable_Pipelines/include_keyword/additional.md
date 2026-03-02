# Дополнительная информация

## Приоритеты слияния

| Конфигурация | Приоритет |
| :--- | :--- |
| Задание в `.gitlab-ci.yml` | **Наивысший** |
| `default:` в `.gitlab-ci.yml` | Средний |
| Файлы `include:` | **Низший** |

## Валидация

```bash
# Проверка конфигурации
gitlab-ci lint --project=my-group/my-project

# Отладка include
gitlab-ci lint --include-debug
```

## Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `file does not exist` | Неправильный путь к файлу | Проверьте путь и расширение |
| `exceeded max includes` | Более 150 включений | Упростите структуру |
| `timeout waiting for include` | Файл недоступен более 30 сек | Проверьте доступность remote/project |

## Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение подходов
- **[Механизм `extends`](./extends_keyword.md)** — наследование конфигураций
- **[CI/CD Catalog](./ci_cd_catalog_components.md)** — создание компонентов
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление переменными

## Внешние ресурсы

- [Официальная документация: `include`](https://docs.gitlab.com/ci/yaml/#include)
- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)

# GitLab CI: `!reference` и YAML Anchors

### Определения

- **`!reference`**: Специальный тег GitLab CI, который явно ссылается на другие элементы и вставляет их содержимое в текущий контекст.
- **YAML Anchor (`&`)**: Механизм YAML для определения якоря (переменной) для фрагмента конфигурации.
- **YAML Alias (`*`)**: Механизм YAML для вставки содержимого, определенного через Anchor.
- **Скрытое задание (Hidden job)**: Задание в `.gitlab-ci.yml`, начинающееся с точки (`.`), которое не выполняется напрямую, но используется как шаблон.

### Основные концепции

#### `!reference` vs. YAML Anchors (`&`) и Aliases (`*`)

Оба механизма используются для переиспользования фрагментов конфигурации внутри одного файла `.gitlab-ci.yml`.

- **`!reference`**: Специальный тег GitLab CI, который явно ссылается на другие элементы и вставляет их содержимое.
  - **Преимущества `!reference`:**
    - **Четкость:** Явно указывает на ссылку, улучшая читаемость.
    - **Гибкость:** Можно ссылаться на любые элементы (скрипты, правила, переменные и т.д.), в том числе на конкретные элементы списков или словарей.
    - **Валидация:** Линтер GitLab CI способен валидировать ссылки, что упрощает отладку.
- **YAML Anchors (`&`) и Aliases (`*`)**: Стандартный механизм YAML. `&anchor_name` задает якорь, `*anchor_name` вставляет содержимое.
  - Эти механизмы менее специфичны для GitLab CI и парсер GitLab не всегда полностью интерпретирует их, что может быть менее предсказуемо, чем `!reference`.

**Предпочтение:** `!reference` обычно более предпочтителен в GitLab CI, так как предоставляет лучшую читаемость и поддержку со стороны GitLab CLI Lint.

### Практические сценарии

#### Сценарий 2: Использование `!reference` и YAML Anchors

**Пример использования `!reference` и YAML Anchors:**

```yaml
.script_template:
  - echo "Running common script part 1"
  - echo "Running common script part 2"

.default_tags: &default_runner_tags
  tags:
    - linux
    - shell

build_job:
  stage: build
  script:
    - !reference [.script_template] # Вставка содержимого .script_template
    - echo "Running build specific script"
  <<: *default_runner_tags # Использование YAML-якоря

test_job:
  stage: test
  script:
    - !reference [.script_template]
    - echo "Running test specific script"
  tags:
    - !reference [.default_tags, tags, 0] # Ссылка на конкретный элемент списка из якоря
```

**Пример с YAML Anchors (`&`) и Aliases (`*`):**

```yaml
.after_script_template: &after_script_definition
  - echo "Cleaning up..."

job1:
  script:
    - echo "Running job 1"
  after_script:
    - *after_script_definition

job2:
  script:
    - echo "Running job 2"
  after_script:
    - *after_script_definition
```

### Дополнительная информация

#### Рекомендации по выбору механизма

| Критерий | `!reference` | YAML Anchors |
| :--- | :--- | :--- |
| **Поддержка GitLab Lint** | Полная | Ограниченная |
| **Читаемость** | Высокая | Средняя |
| **Гибкость** | Высокая (можно ссылаться на элементы списков) | Низкая |
| **Рекомендация** | **Предпочтительно** | Для простых случаев |

#### Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение всех подходов к переиспользованию.
- **[Механизм `extends`](./extends_keyword.md)** — наследование конфигураций.
- **[Механизм `include`](./include_keyword.md)** — подключение внешних файлов.

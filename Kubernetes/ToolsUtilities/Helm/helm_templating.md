# Шаблонизация в Helm

Helm использует Go template engine с библиотекой Sprig для генерации манифестов Kubernetes на основе параметров и логики.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Go templates** | Движок шаблонизации, используемый Helm для рендеринга YAML |
| **Встроенные объекты** | Предопределённые переменные: `.Values`, `.Release`, `.Chart`, `.Capabilities`, `.Files`, `.Template` |
| **Именованные шаблоны** | Переиспользуемые блоки, определяемые через `{{ define }}` и вызываемые через `{{ include }}` |
| **Функции Sprig** | Расширенная библиотека функций для работы со строками, коллекциями, математикой, датами |
| **Хелперы** | Вспомогательные шаблоны в файле `_helpers.tpl` |

---

## Навигация по документации

### Основы

- [Синтаксис шаблонов](./templating/syntax.md) — базовый синтаксис, управляющие конструкции (if/else, with, range), управление пробелами
- [Встроенные объекты](./templating/objects.md) — .Values, .Release, .Chart, .Capabilities, .Files, .Template
- [Функции](./templating/functions.md) — quote, default, required, toYaml, nindent, tpl, include, trunc, trimSuffix и другие
- [Именованные шаблоны и хелперы](./templating/_helpers.md) — создание переиспользуемых блоков в _helpers.tpl

### Практические сценарии

- [Обзор сценариев](./templating/scenarios/overview.md) — оглавление всех примеров
- [Условная логика](./templating/scenarios/conditionals.md) — if/else, условное создание ресурсов, условные аннотации
- [Работа с ConfigMap и файлами](./templating/scenarios/configmap_files.md) — вставка данных, чтение файлов, экранирование
- [Автоматический перезапуск](./templating/scenarios/restart_on_change.md) — rolling update при изменении ConfigMap
- [Проверка API версий](./templating/scenarios/api_versions.md) — адаптация под версию Kubernetes
- [NOTES.txt](./templating/scenarios/notes_txt.md) — инструкции после установки
- [NetworkPolicy](./templating/scenarios/networkpolicy.md) — шаблонизация сетевых политик

---

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции, жизненный цикл релиза
- [Структура Helm-чарта](./helm_chart_structure.md) — расположение шаблонов, _helpers.tpl, values.yaml
- [Управление версиями релизов](./helm_release_versioning.md) — ревизии релизов, откаты

**Полезные ресурсы:**

- Документация Go templates: <https://golang.org/pkg/text/template/>
- Библиотека Sprig: <http://masterminds.github.io/sprig/>
- Локальная отладка: `helm template myrelease .` и `helm install --dry-run --debug myrelease .`

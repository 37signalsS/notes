# Тестирование контента Ansible через ansible-test

## Определения

**ansible-test** — специализированный инструмент, входящий в состав `ansible-core`, предназначенный для тестирования коллекций, плагинов и модулей Ansible. Это официальный стандарт и обязательное требование для публикации контента в Ansible Galaxy и Automation Hub.

**Sanity-тесты** — набор проверок статического анализа, которые контролируют соответствие кода стандартам (PEP8), полноту документации, структуру директорий и корректность метаданных модулей.

**Unit-тесты** — модульное тестирование отдельных компонентов (функций, классов) в изоляции от среды выполнения Ansible. Базируются на фреймворке `pytest`.

**Интеграционные тесты (Integration tests)** — функциональная проверка модулей и плагинов в реальных окружениях (Docker, ВМ, сетевые устройства) путем запуска плейбуков против тестовых целей (targets).

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource`, использование которого обязательно при тестировании через `ansible-test`.

**Таргет (Target)** — отдельный тестовый сценарий в директории `tests/integration/targets/`, представляющий собой роль Ansible с задачами, 변수ми и файлами обработчиков.

## Предварительные требования

Для использования `ansible-test` необходимо выполнение следующих условий:

- **Ansible Core:** версия 2.14+ (рекомендуется актуальная стабильная версия)
- **Python:** версия 3.9+ (рекомендуется 3.11 или 3.12)
- **Docker или Podman:** для запуска тестов в изолированных контейнерах (рекомендуется Docker 24+)
- **pytest:** необходим для unit-тестов (устанавливается автоматически с `ansible-core`)
- **Структура коллекции:** коллекция должна находиться в иерархии `ansible_collections/{namespace}/{collection}/`

Проверка версий:
```bash
ansible --version        # → ansible-core 2.16.x
python3 --version       # → Python 3.11.x
docker --version        # → Docker version 24.x
```

## Основные концепции

### Сравнение: ansible-test vs Molecule

| Характеристика | ansible-test | Molecule |
| :--- | :--- | :--- |
| **Основная цель** | Коллекции, модули, плагины | Роли Ansible |
| **Интеграция** | Часть `ansible-core` | Внешний инструмент (комьюнити-стандарт) |
| **Среды** | Встроенный Docker, Remote (VM), Podman | Драйверы (Docker, Vagrant, Libvirt) |
| **Стандарты** | Обязателен для Galaxy/Automation Hub | Рекомендован для разработки ролей |
| **Структура** | Фиксированная (коллекционная) | Гибкая (через сценарии) |

### Структура директорий коллекции

Для успешного запуска `ansible-test` коллекция должна находиться в иерархии `ansible_collections/{namespace}/{collection}/`.

```text
my_collection/
├── galaxy.yml
├── plugins/
│   ├── modules/
│   │   └── my_module.py
│   └── module_utils/
└── tests/
    ├── sanity/        # Файлы игнорирования (ignore-X.Y.txt)
    ├── unit/          # Тесты pytest (зеркальное дерево плагинов)
    └── integration/   # Сценарии тестирования (targets)
        ├── targets/   # Индивидуальные тесты модулей
        └── inventory  # Специфичный инвентарь (например, для WinRM)
```

### Виды Sanity-проверок

`ansible-test` включает более 40 проверок. Основные:
*   `compile`: Проверка синтаксиса Python под разные версии (3.9–3.12+).
*   `validate-modules`: Валидация `argument_spec` и соответствие документации коду.
*   `import`: Проверка, что модуль может быть импортирован без ошибок зависимостей.
*   `pep8` / `pylint`: Контроль стиля кодирования.
*   `ansible-doc`: Проверка корректности рендеринга документации.

**Игнорирование ошибок:** Если тест не может быть пройден по объективным причинам, создается файл `tests/sanity/ignore-X.Y.txt` (где X.Y — версия ansible-core), содержащий путь к файлу и имя теста.

### Формат файла игнорирования

Файл `tests/sanity/ignore-X.Y.txt` использует формат:
```
# Комментарий
path/to/file.py test-name
# Пример:
plugins/modules/my_module.py validate-modules:parameter-type-not-basic-type
```

Для игнорирования ошибок во всех версиях используйте файл `tests/sanity/ignore.txt`.

### Полный список Sanity-тестов

| Тест | Описание |
| :--- | :--- |
| `ansible-doc` | Проверка корректности рендеринга документации модулей |
| `compile` | Проверка синтаксиса Python для указанных версий |
| `empty-version` | Проверка отсутствия версии в `galaxy.yml` для development-сборок |
| `import` | Проверка импорта модулей без ошибок зависимостей |
| `install` | Проверка корректности установки коллекции |
| `legacy` | Проверка использования устаревших конструкций |
| `metaclass-validation` | Проверка корректности metaclass в модулях |
| `no-assert` | Запрет использования `assert` в production-коде |
| `no-basestring` | Проверка отсутствия `basestring` (Python 2) |
| `no-dict-iteritems` | Проверка отсутствия `dict.iteritems()` (Python 2) |
| `no-dict-keys` | Проверка отсутствия `dict.keys()` в циклах |
| `no-get-exception` | Запрет `except Exception, e` (Python 2) |
| `no-illegal-filename` | Проверка допустимых символов в именах файлов |
| `no-smart-quotes` | Запрет «умных кавычек» в коде |
| `no-tests-as-tests` | Запрет использования `tests/` как имени модуля |
| `no-wildcard-import` | Запрет `from x import *` |
| `pep8` | Проверка соответствия PEP 8 |
| `pylint` | Статический анализ кода |
| `validate-modules` | Валидация аргументов и документации модулей |

## Практические сценарии

### 1. Запуск Sanity-тестов в Docker

Рекомендуется всегда использовать Docker для обеспечения идентичности окружения у всех разработчиков и в CI.

```bash
# Запуск всех sanity-тестов в контейнере по умолчанию
ansible-test sanity --docker default

# Запуск конкретной проверки для одного модуля
ansible-test sanity --test validate-modules plugins/modules/my_module.py

# Запуск всех проверок кроме одной
ansible-test sanity --skip-test pep8

# Запуск проверок для конкретной версии Python
ansible-test sanity --docker default --python 3.11
```

**Список доступных Docker-образов:**
```bash
ansible-test sanity --list-docker-images
# → default (последняя поддерживаемая версия Python)
# → fedora39
# → ubuntu2404
# → alpine319
```

### 2. Разработка Unit-тестов

Unit-тесты располагаются в `tests/unit/plugins/...` и повторяют структуру `plugins/`.

```bash
# Запуск модульных тестов для конкретной версии Python
ansible-test units --docker --python 3.11

# Запуск конкретного тестового файла
ansible-test units --docker tests/unit/plugins/modules/test_my_module.py

# Запуск с фильтрацией по имени теста
ansible-test units --docker -k "test_validation"
```

Пример простейшего теста с моком (`tests/unit/plugins/modules/test_my_module.py`):
```python
from ansible_collections.ns.col.plugins.modules import my_module
# Использование pytest для проверки логики
def test_logic():
    assert my_module.some_function() == "expected_result"
```

Пример unit-теста с мокированием Ansible-модулей:
```python
import pytest
from ansible_collections.my_namespace.my_collection.plugins.modules import my_module
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes

@pytest.fixture
def module_args():
    return {"name": "test_resource", "state": "present"}

def test_my_module_success(mocker, module_args):
    """Тест успешного создания ресурса."""
    mocker.patch.object(basic.AnsibleModule, 'exit_json')
    result = my_module.main(module_args)
    assert result['changed'] is True

def test_my_module_idempotency(mocker, module_args):
    """Тест идемпотентности - повторный запуск без изменений."""
    mocker.patch('ansible_collections.my_namespace.my_collection.plugins.modules.my_module.get_resource')
    mocker.patch.object(basic.AnsibleModule, 'exit_json')
    result = my_module.main(module_args)
    assert result['changed'] is False
```

Структура unit-тестов:
```text
tests/unit/
├── __init__.py
├── plugins/
│   └── modules/
│       ├── __init__.py
│       └── test_my_module.py
└── conftest.py    # Общие фикстуры pytest
```

### 3. Интеграционное тестирование через Targets

Каждый таргет в `tests/integration/targets/` — это фактически роль Ansible.

**Файл `aliases`:** Управляет условиями запуска таргета.
*   `shippable/posix/group1` — группировка для CI.
*   `needs/root` — требует прав root в контейнере.
*   `needs/privileged` — требует запуска Docker в привилегированном режиме.
*   `needs/httptester` — требует запуска HTTP-сервера для тестирования API.

```bash
# Запуск теста с проверкой идемпотентности (стандартный паттерн)
ansible-test integration my_target --docker fedora39

# Запуск всех интеграционных тестов коллекции
ansible-test integration --docker default

# Запуск тестов для конкретного модуля
ansible-test integration my_namespace.my_collection.my_target --docker default
```

**Структура таргета:**
```text
tests/integration/targets/my_module/
├── aliases              # Условия запуска
├── defaults/
│   └── main.yml         # Значения переменных по умолчанию
├── tasks/
│   └── main.yml         # Основные задачи тестирования
├── handlers/
│   └── main.yml         # Обработчики (очистка ресурсов)
├── files/
│   └── test_config.yml  # Тестовые файлы
├── templates/
│   └── config.j2        # Шаблоны для тестов
└── meta/
    └── main.yml         # Метаданные таргета
```

**Пример файла `aliases`:**
```
shippable/posix/group1
needs/root
```

### 4. Тестирование Windows и сетевого оборудования

*   **Windows:** Интеграционные тесты используют алиас `shippable/windows/group1`. Требуют настройки WinRM в `tests/integration/inventory.winrm`.
*   **Network:** Для тестирования сетевых модулей (IOS, Junos) часто используются контейнеры-имитаторы API (алиас `needs/httptester`).

**Пример inventory.winrm:**
```ini
[win]
windows-host ansible_host=192.168.1.100

[win:vars]
ansible_connection=winrm
ansible_winrm_transport=ntlm
ansible_winrm_server_cert_validation=ignore
ansible_port=5986
```

### 5. Удаленное тестирование (--remote)

Если возможностей Docker недостаточно (нужны специфические ядра или ОС), `ansible-test` может арендовать эфемерную ВМ в облаке (AWS, Azure).

```bash
# Запуск интеграционных тестов на реальной Ubuntu в AWS
ansible-test integration my_module --remote aws/ubuntu/jammy
```

*Примечание: Требуется предварительная настройка учетных данных в `credentials.yml`.*

**Поддерживаемые платформы для remote-тестирования:**
```bash
# Список доступных удаленных платформ
ansible-test remote --list
# → aws/ubuntu/jammy
# → aws/ubuntu/focal
# → aws/centos/9
# → azure/Ubuntu2204
```

### 6. Проверка идемпотентности и Check Mode

Хороший интеграционный тест должен содержать:
1.  Первый запуск: ожидается `changed=true`.
2.  Второй запуск: ожидается `changed=false` (идемпотентность).
3.  Запуск в Check Mode (`--check`): ожидается отсутствие реальных изменений.

```yaml
# Пример задачи в tests/integration/targets/my_module/tasks/main.yml
- name: Тест модуля
  my_module:
    name: "test"
  register: result

- name: Проверка изменения
  assert:
    that:
      - result.changed == true

- name: Второй запуск (идемпотентность)
  my_module:
    name: "test"
  register: result第二次

- name: Проверка идемпотентности
  assert:
    that:
      - result第二次.changed == false
```

### 7. Тестирование с переменными и параметрами

```yaml
# tests/integration/targets/my_module/defaults/main.yml
test_resource_name: "test_resource_{{ inventory_hostname }}"
test_resource_state: "present"

# tests/integration/targets/my_module/tasks/main.yml
- name: Тест создания ресурса
  my_module:
    name: "{{ test_resource_name }}"
    state: "{{ test_resource_state }}"
  register: result

- name: Проверка результата
  assert:
    that:
      - result is changed
      - result.resource_id is defined
      - result.resource_id | length > 0
```

## Устранение неполадок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR: Collection not found` | Неверная структура директорий | Убедитесь, что коллекция находится в `ansible_collections/{ns}/{col}/` |
| `ERROR: Python version not supported` | Неподдерживаемая версия Python | Используйте Python 3.9+ (рекомендуется 3.11+) |
| `ERROR: Docker not available` | Docker не запущен или не установлен | Запустите Docker или установите его |
| `ERROR: Permission denied` | Недостаточно прав для Docker | Добавьте пользователя в группу `docker` или используйте `sudo` |
| `ERROR: Module import failed` | Ошибка импорта модуля | Проверьте зависимости в `meta/runtime.yml` |
| `ERROR: Invalid FQCN` | Неверный формат имени коллекции | Используйте формат `namespace.collection.resource` |
| `ERROR: Test target not found` | Таргет не найден в `tests/integration/targets/` | Проверьте имя таргета и его наличие в директории |

### Диагностические команды

```bash
# Проверка структуры коллекции
ansible-test sanity --docker default -v

# Просмотр логов с подробностями
ansible-test integration my_target --docker default -vvv

# Запуск в интерактивном режиме для отладки
ansible-test integration my_target --docker default --interactive

# Проверка конкретного модуля с выводом ошибок
ansible-test sanity --docker default --test validate-modules plugins/modules/my_module.py -vvv
```

### Отладка через ANSIBLE_KEEP_REMOTE_FILES

Если модуль падает с невнятной ошибкой, установите переменную окружения `ANSIBLE_KEEP_REMOTE_FILES=1`. Ansible не удалит временный файл на удаленном узле. Вы сможете зайти на хост и запустить его вручную:
```bash
python3 ~/.ansible/tmp/ansible-tmp-.../AnsiballZ_clickhouse_user.py explode
cd debug_dir
python3 ansible_module_clickhouse_user.py args.json
```

## Переменные окружения

| Переменная | Описание | Пример значения |
| :--- | :--- | :--- |
| `ANSIBLE_TEST_DOCKER_USER` | Пользователь для запуска в контейнере | `root`, `runner` |
| `ANSIBLE_TEST_REMOTE_ENABLE` | Включение удаленного тестирования | `1`, `0` |
| `ANSIBLE_TEST_COVERAGE_ENABLED` | Включение сбора покрытия | `1`, `0` |
| `ANSIBLE_TEST_COMBINATIONS_LIMIT` | Ограничение комбинаций тестов | `1`, `2`, `auto` |
| `ANSIBLE_TEST_PYTHON_VERSION` | Версия Python для тестов | `3.11`, `3.12` |
| `ANSIBLE_TEST_DOCKER_REGISTRY` | Регистр Docker для образов | `quay.io/ansible` |

## Анализ покрытия (Coverage)

```bash
# Сбор покрытия при запуске интеграционных тестов
ansible-test integration --coverage my_module

# Сбор покрытия для unit-тестов
ansible-test units --coverage --docker

# Просмотр отчета
ansible-test coverage report

# Генерация HTML-отчета
ansible-test coverage html

# Экспорт в формат LCOV (для интеграции с CI/CD)
ansible-test coverage lcov
```

**Настройка минимального покрытия:**
```yaml
# tests/sanity/coverage-config.yml
minimum_coverage:
  overall: 80
  modules: 70
  plugins: 85
```

## Интеграция с CI/CD

### GitHub Actions

```yaml
name: Ansible Collection Tests
on: [push, pull_request]

jobs:
  sanity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Run sanity tests
        run: ansible-test sanity --docker default

  units:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Run unit tests
        run: ansible-test units --docker --python 3.11

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Run integration tests
        run: ansible-test integration --docker default
```

### GitLab CI

```yaml
stages:
  - test

sanity-tests:
  stage: test
  image: python:3.11
  script:
    - pip install ansible-core
    - ansible-test sanity --docker default

unit-tests:
  stage: test
  image: python:3.11
  script:
    - pip install ansible-core
    - ansible-test units --docker --python 3.11

integration-tests:
  stage: test
  image: python:3.11
  services:
    - docker:dind
  script:
    - pip install ansible-core
    - ansible-test integration --docker default
```

## Управление тестами

### Список доступных тестов

```bash
# Список всех sanity-тестов
ansible-test sanity --list-tests

# Список всех интеграционных таргетов
ansible-test integration --list-targets

# Список всех unit-тестов
ansible-test units --list
```

### Фильтрация тестов

```bash
# Запуск тестов по маске имени
ansible-test integration --docker default -t "test_create_*"

# Исключение тестов по маске
ansible-test integration --docker default -e "test_delete_*"

# Запуск тестов с определенным тегом
ansible-test integration --docker default --tags "network,security"
```

### Пропуск тестов

```bash
# Пропуск конкретного sanity-теста
ansible-test sanity --docker default --skip-test pep8

# Пропуск нескольких тестов
ansible-test sanity --docker default --skip-test pep8 --skip-test pylint

# Пропуск интеграционного таргета
ansible-test integration --docker default --skip-targets my_broken_target
```

## Лучшие практики

### Структура тестов

1. **Разделяйте тесты по назначению:** sanity, unit, integration — это разные уровни тестирования.
2. **Следуйте конвенции именования:** файлы unit-тестов начинаются с `test_`, таргеты имеют осмысленные имена.
3. **Используйте фикстуры pytest:** выносите общую настройку в `conftest.py`.
4. **Пишите атомарные тесты:** каждый тест должен проверять одну конкретную функциональность.

### Интеграционные тесты

1. **Всегда проверяйте идемпотентность:** два последовательных запуска должны дать одинаковый результат.
2. **Используйте Check Mode:** проверяйте, что модуль корректно работает в режиме проверки.
3. **Очищайте ресурсы:** используйте handlers для удаления созданных ресурсов после тестов.
4. **Изоляция тестов:** каждый тест должен работать независимо от других.

### CI/CD интеграция

1. **Кэшируйте зависимости:** ускоряйте запуск тестов в CI/CD.
2. **Параллелизация:** запускайте sanity, unit и integration тесты параллельно.
3. **Отчеты о покрытии:** публикуйте отчеты как артефакты CI/CD.
4. **Регрессия:** запускайте тесты на каждом pull request.

## Дополнительная информация

### Переменные окружения и отладка

*   `ANSIBLE_TEST_DOCKER_USER`: Указывает пользователя для запуска в контейнере.
*   `--interactive`: Позволяет войти в контейнер при падении теста для ручной отладки.

### Анализ покрытия (Coverage)

```bash
# Сбор покрытия при запуске интеграционных тестов
ansible-test integration --coverage my_module
# Просмотр отчета
ansible-test coverage report
```

### Смотрите также

*   **[Разработка собственных модулей](./ansible_custom_modules.md)** — основы создания кода.
*   **[Тестирование ролей через Molecule](./ansible_testing_with_molecule.md)** — когда ваш продукт — это роли, а не коллекции.
*   **[Среды выполнения (EE)](./ansible-execution-environments.md)** — современный способ упаковки Ansible.
*   [Официальный справочик по тестам (EN)](https://docs.ansible.com/ansible/latest/dev_guide/testing_sanity.html)

# Тестирование контента Ansible через ansible-test

## Определения

**ansible-test** — специализированный инструмент, входящий в состав `ansible-core`, предназначенный для тестирования коллекций, плагинов и модулей Ansible. Это официальный стандарт и обязательное требование для публикации контента в Ansible Galaxy и Automation Hub.

**Sanity-тесты** — набор проверок статического анализа, которые контролируют соответствие кода стандартам (PEP8), полноту документации, структуру директорий и корректность метаданных модулей.

**Unit-тесты** — модульное тестирование отдельных компонентов (функций, классов) в изоляции от среды выполнения Ansible. Базируются на фреймворке `pytest`.

**Интеграционные тесты (Integration tests)** — функциональная проверка модулей и плагинов в реальных окружениях (Docker, ВМ, сетевые устройства) путем запуска плейбуков против тестовых целей (targets).

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource`, использование которого обязательно при тестировании через `ansible-test`.

**Таргет (Target)** — отдельный тестовый сценарий в директории `tests/integration/targets/`, представляющий собой роль Ansible с задачами, переменными и файлами обработчиков.

## Предварительные требования

Для использования `ansible-test` необходимо выполнение следующих условий:

- **Ansible Core:** версия 2.18+ (актуальные поддерживаемые: 2.18, 2.19, 2.20, 2.21; рекомендуется целевая версия проекта)
- **Python:** версия 3.9+ для управляемых узлов; на контрольном узле — 3.12–3.14 (для ansible-core 2.21)
- **Docker или Podman:** для запуска тестов в изолированных контейнерах (рекомендуется Docker 24+ или Podman 4+)
- **pytest:** необходим для unit-тестов (устанавливается автоматически с `ansible-core`)
- **Структура коллекции:** коллекция должна находиться в иерархии `ansible_collections/{namespace}/{collection}/`

Проверка версий:
```bash
ansible --version        # → ansible-core 2.21.x
python3 --version       # → Python 3.12.x
docker --version        # → Docker version 24.x
```

## Основные концепции

### Сравнение: ansible-test vs Molecule

| Характеристика | ansible-test | Molecule |
| :--- | :--- | :--- |
| **Основная цель** | Коллекции, модули, плагины | Роли Ansible |
| **Интеграция** | Часть `ansible-core` | Внешний инструмент (комьюнити-стандарт) |
| **Среды** | Встроенный Docker, Podman, venv | Драйверы (Docker, Vagrant, Libvirt) |
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
*   `compile`: Проверка синтаксиса Python под разные версии (3.9–3.14+).
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
| `changelog` | Проверка формата и наличия файла CHANGELOG.rst |
| `compile` | Проверка синтаксиса Python для указанных версий |
| `empty-init` | Проверка отсутствия пустых `__init__.py` |
| `import` | Проверка импорта модулей без ошибок зависимостей |
| `line-endings` | Проверка окончаний строк (LF vs CRLF) |
| `no-assert` | Запрет использования `assert` в production-коде |
| `no-basestring` | Проверка отсутствия `basestring` (Python 2) |
| `no-dict-iteritems` | Проверка отсутствия `dict.iteritems()` (Python 2) |
| `no-dict-iterkeys` | Проверка отсутствия `dict.iterkeys()` (Python 2) |
| `no-dict-itervalues` | Проверка отсутствия `dict.itervalues()` (Python 2) |
| `no-get-exception` | Запрет `except Exception, e` (Python 2) |
| `no-illegal-filenames` | Проверка допустимых символов в именах файлов |
| `no-main-display` | Запрет `display()` в модулях без обертки |
| `no-smart-quotes` | Запрет «умных кавычек» в коде |
| `no-unicode-literals` | Проверка отсутствия `from __future__ import unicode_literals` |
| `no-wildcard-import` | Запрет `from x import *` |
| `pep8` | Проверка соответствия PEP 8 |
| `pylint` | Статический анализ кода |
| `replace-urlopen` | Запрет `urllib2.urlopen` (Python 2) |
| `runtime-metadata` | Проверка корректности `meta/runtime.yml` |
| `shebang` | Проверка корректности shebang в скриптах |
| `shellcheck` | Анализ shell-скриптов (если установлен) |
| `symlinks` | Проверка симлинков в репозитории |
| `use-argspec-type-path` | Проверка использования `type='path'` в `argument_spec` |
| `use-compat-six` | Запрет `ansible.module_utils.six` (устарело) |
| `validate-modules` | Валидация аргументов и документации модулей |
| `yamllint` | Проверка синтаксиса YAML-файлов |

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
ansible-test sanity --docker default --python 3.12
```

**Список доступных Docker-образов:**
```bash
ansible-test sanity --list-docker-images
# → default (используется по умолчанию для sanity и unit-тестов)
# → base (минимальный образ для platform-independent тестов)
# → alpine320
# → fedora40
# → ubuntu2204
# → ubuntu2404
```

### 2. Разработка Unit-тестов

Unit-тесты располагаются в `tests/unit/plugins/...` и повторяют структуру `plugins/`.

```bash
# Запуск модульных тестов для конкретной версии Python
ansible-test units --docker --python 3.12

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

Каждый таргет в `tests/integration/targets/` — это фактически роль Ansible. Существует два типа интеграционных тестов:
*   **Ролевые (role-based):** запускаются через `ansible-playbook` и проверяют взаимодействие модуля с системой.
*   **Скриптовые (`runme.sh`):** запускаются напрямую как shell-скрипты; позволяют настроить инвентарь и выполнить произвольные команды.

**Файл `aliases`:** Управляет условиями запуска таргета.
*   `shippable/posix/group1` — группировка для CI.
*   `needs/root` — требует прав root в контейнере.
*   `needs/privileged` — требует запуска Docker в привилегированном режиме.
*   `needs/httptester` — требует запуска HTTP-сервера для тестирования API.
*   `unsupported` — тест не может быть запущен в CI (пропускается автоматически).

```bash
# Запуск теста с проверкой идемпотентности (стандартный паттерн)
ansible-test integration my_target --docker fedora40

# Запуск всех интеграционных тестов коллекции
ansible-test integration --docker default

# Запуск тестов для конкретного модуля
ansible-test integration my_namespace.my_collection.my_target --docker default

# Автоматический повтор при ошибке с повышенной детализацией
ansible-test integration --docker default --retry-on-error
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

**Скриптовые тесты (`runme.sh`):**

Для не-Ansible сценариев или тонкой настройки окружения используйте `runme.sh` в корне таргета:

```bash
#!/bin/bash
# tests/integration/targets/my_module/runme.sh

# Настройка инвентаря
cat > inventory <<EOF
[target]
localhost ansible_connection=local
EOF

# Запуск плейбука
ansible-playbook -i inventory tasks/main.yml -v
```

Файл `runme.sh` должен возвращать `0` при успехе и ненулевое значение при ошибке.

### 4. Тестирование Windows и сетевого оборудования

*   **Windows:** Интеграционные тесты используют алиас `shippable/windows/group1`. Требуют настройки WinRM в `tests/integration/inventory.winrm`. Для локального тестирования без облака используйте on-prem Windows Server с включенным WinRM.
*   **Network:** Для тестирования сетевых модулей (IOS, Junos, EOS) часто используются контейнеры-имитаторы API (алиас `needs/httptester`). В продакшн-средах тестируйте на стендах с реальным оборудованием или виртуальными маршрутизаторами (VRF, EVE-NG, GNS3).

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

**Сетевые тесты в изоляции:**
```bash
# Запуск с HTTP-тестировщиком (имитация API)
ansible-test integration my_network_module --docker default

# Для тестов, требующих привилегий
ansible-test integration my_network_module --docker default --tags "network"
```

### 5. Тестирование в виртуальных окружениях (--venv)

Если использование Docker/Podman невозможно (ограничения ОС, требования к системным вызовам), `ansible-test` может запускать тесты в виртуальном окружении Python (`--venv`). Зависимости устанавливаются автоматически.

```bash
# Запуск sanity-тестов в venv
ansible-test sanity --venv

# Запуск unit-тестов с указанием Python
ansible-test units --venv --python 3.12

# Запуск интеграционных тестов в venv
ansible-test integration --venv my_target
```

### 5.1. Тестирование на реальной инфраструктуре (on-prem)

Для модулей, требующих доступа к физическим устройствам или специфичному железу (BMC, IPMI, RAID-контроллеры), используйте целевые хосты в локальном дата-центре. Настройте инвентарь в `tests/integration/inventory`:

```ini
[target]
baremetal01 ansible_host=10.0.1.10 ansible_user=root

[target:vars]
ansible_connection=ssh
ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

Запуск на реальных хостах через Docker-образ, совпадающий с ОС цели:
```bash
ansible-test integration my_hardware_module --docker ubuntu2204
```

Для полностью изолированных стендов (без Docker) используйте `--venv` и указывайте кастомный инвентарь через переменные окружения или конфиг `ansible.cfg`.

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
  register: result

- name: Проверка идемпотентности
  assert:
    that:
      - result.changed == false
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
| `ERROR: Python version not supported` | Неподдерживаемая версия Python | Используйте Python 3.9+ (рекомендуется 3.12+) |
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
| `ANSIBLE_TEST_COVERAGE_ENABLED` | Включение сбора покрытия | `1`, `0` |
| `ANSIBLE_TEST_COMBINATIONS_LIMIT` | Ограничение комбинаций тестов | `1`, `2`, `auto` |
| `ANSIBLE_TEST_PYTHON_VERSION` | Версия Python для тестов | `3.12`, `3.13`, `3.14` |
| `ANSIBLE_TEST_DOCKER_REGISTRY` | Регистр Docker для образов | `quay.io/ansible` |
| `ANSIBLE_TEST_PREFER_PODMAN` | Предпочитать Podman вместо Docker | `1`, `0` |

## Анализ покрытия (Coverage)

`ansible-test` автоматически генерирует конфигурацию покрытия во временной директории. Пороговые значения покрытия обычно enforcing в CI-пайплайне через внешние инструменты (codecov, coveralls) или через `pytest-cov` с настройкой `--cov-fail-under`.

```bash
# Сбор покрытия при запуске интеграционных тестов
ansible-test integration --coverage my_target --docker default

# Сбор покрытия для unit-тестов
ansible-test units --coverage --docker

# Очистка данных покрытия
ansible-test coverage erase

# Просмотр отчета в консоли
ansible-test coverage report

# Генерация HTML-отчета
ansible-test coverage html

# Экспорт в LCOV (для Codecov, Coveralls)
ansible-test coverage lcov

# Комбинирование результатов из разных запусков
ansible-test coverage combine
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
          python-version: '3.12'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Run sanity tests
        run: ansible-test sanity --docker default -v

  units:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Run unit tests
        run: ansible-test units --docker --python 3.12

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Run integration tests
        run: ansible-test integration --docker default -v
```

### GitLab CI

```yaml
stages:
  - test

sanity-tests:
  stage: test
  image: python:3.12
  script:
    - pip install ansible-core
    - ansible-test sanity --docker default -v

unit-tests:
  stage: test
  image: python:3.12
  script:
    - pip install ansible-core
    - ansible-test units --docker --python 3.12

integration-tests:
  stage: test
  image: python:3.12
  services:
    - docker:dind
  script:
    - pip install ansible-core
    - ansible-test integration --docker default -v
```

### Jenkins (Declarative Pipeline)

```groovy
pipeline {
  agent any
  stages {
    stage('Sanity') {
      steps {
        sh 'pip install ansible-core'
        sh 'ansible-test sanity --docker default -v'
      }
    }
    stage('Unit') {
      steps {
        sh 'pip install ansible-core'
        sh 'ansible-test units --docker --python 3.12'
      }
    }
    stage('Integration') {
      steps {
        sh 'pip install ansible-core'
        sh 'ansible-test integration --docker default -v'
      }
    }
  }
  post {
    always {
      junit '**/test/results/*.xml'
      archiveArtifacts artifacts: '**/test/results/coverage/**', allowEmptyArchive: true
    }
  }
}
```

### Интеграция с pre-commit

Для соблюдения стандартов до коммита используйте `pre-commit` с хуками для `ansible-test` и `ansible-lint`:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v26.8.0
    hooks:
      - id: ansible-lint
        files: \.(yaml|yml)$

  - repo: local
    hooks:
      - id: ansible-test-sanity
        name: ansible-test sanity
        entry: bash -c 'cd ansible_collections/my_namespace/my_collection && ansible-test sanity --docker default'
        language: system
        pass_filenames: []
        types: [python]
```

Установка:
```bash
pip install pre-commit
pre-commit install
# Ручной запуск для всех файлов
pre-commit run --all-files
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
# Запуск конкретного таргета
ansible-test integration --docker default my_target

# Запуск нескольких таргетов
ansible-test integration --docker default target1 target2

# Исключение таргета
ansible-test integration --docker default --exclude my_broken_target

# Запуск с определенным тегом Ansible (применяется внутри плейбуков)
ansible-test integration --docker default --tags "network,security"
```

### Пропуск тестов

```bash
# Пропуск конкретного sanity-теста
ansible-test sanity --docker default --skip-test pep8

# Пропуск нескольких тестов
ansible-test sanity --docker default --skip-test pep8 --skip-test pylint

# Пропуск интеграционного таргета
ansible-test integration --docker default --exclude my_broken_target
```

## Лучшие практики

### Структура тестов

1. **Разделяйте тесты по назначению:** sanity, unit, integration — это разные уровни тестирования.
2. **Следуйте конвенции именования:** файлы unit-тестов начинаются с `test_`, таргеты имеют осмысленные имена.
3. **Используйте фикстуры pytest:** выносите общую настройку в `conftest.py`.
4. **Пишите атомарные тесты:** каждый тест должен проверять одну конкретную функциональность.
5. **Единый корень тестов:** все тесты запускаются из корня коллекции, чтобы избежать проблем с путями.

### Интеграционные тесты

1. **Всегда проверяйте идемпотентность:** два последовательных запуска должны дать одинаковый результат.
2. **Используйте Check Mode:** проверяйте, что модуль корректно работает в режиме проверки.
3. **Очищайте ресурсы:** используйте handlers для удаления созданных ресурсов после тестов.
4. **Изоляция тестов:** каждый тест должен работать независимо от других.
5. **Не храните секреты в тестах:** используйте `vault` или переменные окружения CI для учетных данных.
6. **Тестируйте на минимально поддерживаемых версиях:** включите matrix build в CI с целевыми версиями Python и ОС.

### CI/CD интеграция

1. **Кэшируйте зависимости:** ускоряйте запуск тестов в CI/CD (кэш pip, Docker layer cache).
2. **Параллелизация:** запускайте sanity, unit и integration тесты параллельно.
3. **Отчеты о покрытии:** публикуйте отчеты как артефакты CI/CD, настройте пороговые значения (`--cov-fail-under`).
4. **Регрессия:** запускайте тесты на каждом pull request, включая merge-queue.
5. **Fail-fast:** прерывайте пайплайн на sanity-тестах, чтобы не тратить время на integration при критических ошибках.
6. **Артефакты:** сохраняйте логи, JUnit-отчеты и HTML-покрытия для пост-фактум анализа.
7. **Matrix-стратегия:** тестируйте комбинации ОС × Python × версия ansible-core, релевантные для поддержки.
8. **Change management:** интегрируйте тесты в GitOps-воркфлоу ( Atlantis, Pull Request Automation).

### SRE-практики

1. **Измеримость:** каждый failing-тест должен давать actionable-сообщение с причиной и местом.
2. **Воспроизводимость:** тесты должны проходить на любом инженерном хосте за <10 минут для sanity/unit.
3. **Наблюдаемость:** собирайте метрики длительности тестов, выделите аутлаеры (flaky tests).
4. **Безопасность:** не запускайте integration-тесты с `--tags network` на uncontrolled хостах; изолируйте сеть контейнера.
5. **Документация:** каждый failing-тест — это баг в модуле или в тесте; ведите реестр ignored sanity-ошибок с причиной и планом дальнейшего удаления.

### Работа с игнорированиями sanity

1. **Обоснуйте каждое игнорирование:** добавьте комментарий с ссылкой на issue или PR.
2. **Периодически пересматривайте:** удаляйте устаревшие ignore-записи при обновлении кода.
3. **Версионность:** игнорирования привязаны к версии ansible-core (`ignore-2.21.txt`), не смешивайте разные версии.
4. **Минимизируйте область:** игнорируйте конкретный тест для конкретного файла, а не целый класс тестов.

## Дополнительная информация

### Вспомогательные инструменты

*   **pytest-ansible:** плагин для pytest, упрощающий вызов Ansible-модулей из тестов. Обеспечивает фикстуры `ansible_module`, `ansible_adhoc`, `localhost` и `ansible_facts`.
*   **tox-ansible:** расширение для tox, запускающее sanity, unit и integration тесты в нескольких окружениях Python/ansible-core.
*   **ansible-dev-tools:** объединенный пакет (ansible-lint + molecule + pytest-ansible + tox-ansible + ansible-creator). Рекомендуется для единообразной настройки окружения разработчика.

### Переменные окружения и отладка

*   `ANSIBLE_TEST_DOCKER_USER`: Указывает пользователя для запуска в контейнере.
*   `--interactive`: Позволяет войти в контейнер при падении теста для ручной отладки.

### Смотрите также

*   **[Разработка собственных модулей](./ansible_custom_modules.md)** — основы создания кода.
*   **[Тестирование ролей через Molecule](./ansible_testing_with_molecule.md)** — когда ваш продукт — это роли, а не коллекции.
*   **[Среды выполнения (EE)](./ansible-execution-environments.md)** — современный способ упаковки Ansible.
*   [Официальная документация по тестированию (EN)](https://docs.ansible.com/projects/ansible/latest/dev_guide/testing.html)

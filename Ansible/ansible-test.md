# Тестирование контента Ansible через ansible-test

## Определения

**ansible-test** — специализированный инструмент, входящий в состав `ansible-core`, предназначенный для тестирования коллекций, плагинов и модулей Ansible. Это официальный стандарт и обязательное требование для публикации контента в Ansible Galaxy и Automation Hub.

**Sanity-тесты** — набор проверок статического анализа, которые контролируют соответствие кода стандартам (PEP8), полноту документации, структуру директорий и корректность метаданных модулей.

**Unit-тесты** — модульное тестирование отдельных компонентов (функций, классов) в изоляции от среды выполнения Ansible. Базируются на фреймворке `pytest`.

**Интеграционные тесты (Integration tests)** — функциональная проверка модулей и плагинов в реальных окружениях (Docker, ВМ, сетевые устройства) путем запуска плейбуков против тестовых целей (targets).

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource`, использование которого обязательно при тестировании через `ansible-test`.

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

## Практические сценарии

### 1. Запуск Sanity-тестов в Docker

Рекомендуется всегда использовать Docker для обеспечения идентичности окружения у всех разработчиков и в CI.

```bash
# Запуск всех sanity-тестов в контейнере по умолчанию
ansible-test sanity --docker default

# Запуск конкретной проверки для одного модуля
ansible-test sanity --test validate-modules plugins/modules/my_module.py
```

### 2. Разработка Unit-тестов

Unit-тесты располагаются в `tests/unit/plugins/...` и повторяют структуру `plugins/`.

```bash
# Запуск модульных тестов для конкретной версии Python
ansible-test units --docker --python 3.11
```

Пример простейшего теста с моком (`tests/unit/plugins/modules/test_my_module.py`):
```python
from ansible_collections.ns.col.plugins.modules import my_module
# Использование pytest для проверки логики
def test_logic():
    assert my_module.some_function() == "expected_result"
```

### 3. Интеграционное тестирование через Targets

Каждый таргет в `tests/integration/targets/` — это фактически роль Ansible.

**Файл `aliases`:** Управляет условиями запуска таргета.
*   `shippable/posix/group1` — группировка для CI.
*   `needs/root` — требует прав root в контейнере.
*   `needs/privileged` — требует запуска Docker в привилегированном режиме.

```bash
# Запуск теста с проверкой идемпотентности (стандартный паттерн)
ansible-test integration my_target --docker fedora39
```

### 4. Тестирование Windows и сетевого оборудования

*   **Windows:** Интеграционные тесты используют алиас `shippable/windows/group1`. Требуют настройки WinRM в `tests/integration/inventory.winrm`.
*   **Network:** Для тестирования сетевых модулей (IOS, Junos) часто используются контейнеры-имитаторы API (алиас `needs/httptester`).

### 5. Удаленное тестирование (--remote)

Если возможностей Docker недостаточно (нужны специфические ядра или ОС), `ansible-test` может арендовать эфемерную ВМ в облаке (AWS, Azure).

```bash
# Запуск интеграционных тестов на реальной Ubuntu в AWS
ansible-test integration my_module --remote aws/ubuntu/jammy
```
*Примечание: Требуется предварительная настройка учетных данных в `credentials.yml`.*

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
```

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
*   [Официальный справочник по тестам (EN)](https://docs.ansible.com/ansible/latest/dev_guide/testing_sanity.html)

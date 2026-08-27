# Ansible — разработка Action-плагинов

## Определения

**Action-плагин (Action Plugin)** — это специализированное расширение Ansible, которое выполняется исключительно на **узле управления (Control Node)**. Он выступает посредником между движком Ansible и модулем, выполняемым на удаленном хосте, позволяя перехватывать выполнение задачи и реализовывать сложную логику на стороне контроллера.

Многие ключевые модули (например, `ansible.builtin.template`, `ansible.builtin.copy`, `ansible.builtin.fetch`) являются Action-плагинами. Они выполняют тяжелые или специфичные для контроллера операции (генерация шаблонов, сравнение контрольных сумм локальных файлов) до того, как инициировать выполнение кода на целевом узле.

- **ActionBase** — базовый класс (`ansible.plugins.action.ActionBase`), от которого наследуются все action-плагины. Предоставляет вспомогательные методы для работы с соединениями, временными файлами, рендерингом шаблонов и запуска модулей на удалённых хостах.
- **ActionModule** — обязательный класс плагина, наследуемый от `ActionBase`. Должен содержать метод `run(self, tmp=None, task_vars=None)`, который является точкой входа при выполнении.
- **Adaptive Action Plugin** — action-плагин, который определяет自己自身 как замену для модуля с тем же именем. При поиске Ansible сначала проверяет наличие action-плагина, и если он найден — выполняет его вместо модуля. Это позволяет перехватывать выполнение модуля и добавлять логику до или после него.

## Основные концепции

### Зачем нужны Action-плагины?

1.  **Локальные операции:** Выполнение действий, требующих прямого доступа к файловой системе или ресурсам узла управления (например, чтение локальных конфигураций или секретов).
2.  **Сложная логика управления:** Реализация условий или цепочек действий, которые невозможно (или нецелесообразно) реализовать внутри одного модуля на Python/Shell на удаленном хосте.
3.  **Оптимизация трафика:** Проверка состояния ресурса перед передачей данных. Например, плагин `copy` не передает файл, если его хеш-сумма на удаленном хосте уже совпадает с локальной.
4.  **Скрытие сложности:** Пользователь видит вызов одной задачи, в то время как Action-плагин может прозрачно вызывать несколько разных модулей.
5.  **Предварительная обработка:** Валидация параметров, рендеринг Jinja2-шаблонов и подготовка данных до передачи модулю на удалённый хост.
6.  **Интеграция с Control Node:** Доступ к локальным ресурсам (API-ключи, файлы, переменные окружения) для принятия решений перед выполнением на хосте.

### Различия: Action Plugin vs Module

| Критерий | Action Plugin | Module |
| :--- | :--- | :--- |
| **Место выполнения** | Узел управления (Control Node) | Управляемый узел (Managed Node) |
| **Доступ к ресурсам** | Полный доступ к локальной ФС и переменным окружения контроллера | Ограничен средой выполнения на хосте |
| **Зависимости** | Использует Python и библиотеки, установленные на контроллере | Зависит от интерпретатора Python и библиотек на удаленном хосте |
| **Жизненный цикл** | Запускается первым; решает, нужно ли запускать модуль | Выполняется по запросу Action-плагина или ядра |
| **Возможности** | Может вызывать несколько модулей, работать с соединениями, передавать файлы | Ограничен одной операцией |
| **Доступ к контексту** | `self._task`, `self._play_context`, `self._connection`, `self._templar` | Только аргументы модуля |

### Поток выполнения задачи

1.  **Парсинг:** Ядро Ansible считывает задачу из плейбука.
2.  **Поиск плагина:** Ansible ищет Action-плагин с именем, соответствующим модулю. Если action-плагин найден — выполняется он. Если нет — модуль передаётся на удалённый хост напрямую.
3.  **Выполнение (Controller):** Запускается метод `run()` плагина.
4.  **Предварительная обработка:** Плагин рендерит Jinja2-шаблоны через `_templar`, валидирует аргументы, проверяет `_VALID_ARGS`.
5.  **Взаимодействие (Optional):** Плагин может вызвать `_execute_module` для выполнения кода на хосте, `_transfer_file` для передачи файлов или `_low_level_execute_command` для выполнения сырых команд.
6.  **Возврат результата:** Плагин агрегирует данные и возвращает JSON-ответ ядру. Результат должен содержать ключи `changed`, `failed`, `msg` (при необходимости).

### Обнаружение и загрузка плагинов

Ansible ищет action-плагины в следующих местах (в порядке приоритета):

1.  Директория `action_plugins/` в корне текущего плейбука.
2.  Директория `action_plugins/` внутри роли (`roles/<role_name>/action_plugins/`).
3.  Директория `plugins/action/` внутри коллекции.
4.  Пути, указанные в `action_plugins` параметре `ansible.cfg`.
5.  Встроенные action-плагины Ansible Core (в `lib/ansible/plugins/action/`).

```bash
# Просмотр встроенных action-плагинов
python3 -c "import ansible.plugins.action; print(ansible.plugins.action.__path__)"
# → ['/path/to/ansible/plugins/action']
```

Приоритет разрешения: локальные плагины > роли > коллекции > встроенные. Если плагин с одинаковым именем существует в нескольких местах — используется первый найденный.

### Метаданные плагина

Action-плагин может определять документацию и метаданные через переменные модуля уровня модуля:

```python
DOCUMENTATION = r'''
---
short_description: Краткое описание плагина
description:
  - Подробное описание того, что делает плагин и зачем он нужен.
options:
  src:
    description: Путь к исходному файлу
    required: true
    type: str
  dest:
    description: Путь назначения на удалённом хосте
    required: true
    type: str
  force:
    description: Принудительная перезапись
    type: bool
    default: false
'''

EXAMPLES = r'''
- name: Пример использования
  my_namespace.my_collection.my_module:
    src: /local/path/file.conf
    dest: /remote/path/file.conf
    force: true
'''

RETURN = r'''
changed:
  description: Были ли внесены изменения
  type: bool
  sample: true
msg:
  description: Сообщение о результате
  type: str
  sample: "Файл успешно скопирован"
'''
```

### Рекурсивный рендеринг аргументов

Если action-плагин вызывает другой модуль через `_execute_module`, аргументы для этого модуля также могут содержать Jinja2-выражения. Ansible автоматически рекурсивно рендерит аргументы, передаваемые через `module_args` в `_execute_module`. Это означает, что разработчику не нужно вручную рендерить каждый аргумент — достаточно передать их в `module_args`.

## Практические сценарии

### Базовый шаблон плагина

Файлы Action-плагинов располагаются в `action_plugins/` (корень проекта) или `plugins/action/` (внутри коллекции).

```python
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleError, AnsibleActionFail

class ActionModule(ActionBase):
    # Указывает, требует ли плагин соединения с хостом
    _VALID_ARGS = frozenset(['src', 'dest', 'force'])

    def run(self, tmp=None, task_vars=None):
        # Инициализация базового результата
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Проверка обязательных аргументов
        if 'dest' not in self._task.args:
            raise AnsibleActionFail("Параметр 'dest' обязателен для этого плагина")

        # Логика на контроллере...
        result['changed'] = False
        result['msg'] = "Action plugin executed successfully"
        
        return result
```

### Пример: Использование Templar для обработки переменных

Если параметры плагина могут содержать Jinja2-выражения, их необходимо отрендерить перед использованием.

```python
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Получение необработанного аргумента
        raw_dest = self._task.args.get('dest')
        
        # Рендеринг через внутренний объект _templar
        dest = self._templar.template(raw_dest)
        
        result['final_path'] = dest
        return result
```

### Пример: Обработка check_mode и diff

Action-плагин обязан учитывать режим проверки (`--check`) и вывода различий (`--diff`).

```python
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Проверка режима check_mode
        check_mode = self._play_context.check_mode
        
        # Имитация изменений без их внесения
        if check_mode:
            result['changed'] = True
            result['skipped'] = False
            result['msg'] = "Check mode: изменения были бы внесены"
            return result

        # Поддержка diff
        if self._play_context.diff:
            result['diff'] = {
                'before': 'old_state',
                'after': 'new_state'
            }
            
        return result
```

### Пример: Работа с удаленными временными файлами

Правильный цикл: создание временной папки -> передача файла -> удаление папки.

```python
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # 1. Создание временной директории на удаленном хосте
        remote_tmp = self._make_tmp_path()
        
        try:
            # 2. Передача локального файла
            source_file = "/path/to/local/file"
            remote_dest = remote_tmp + "uploaded_file"
            
            self._transfer_file(source_file, remote_dest)
            
            # 3. Выполнение модуля, использующего этот файл
            module_res = self._execute_module(
                module_name='ansible.builtin.command',
                module_args={'_raw_params': f'cat {remote_dest}'},
                task_vars=task_vars
            )
            result.update(module_res)
            
        finally:
            # 4. Обязательная очистка
            self._remove_tmp_path(remote_tmp)
            
        return result
```

### Пример: Делегирование выполнения на другой хост

Action-плагин может делегировать выполнение модуля на другой хост, используя `_execute_module` с параметром `delegate_to`.

```python
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Делегирование на другой хост
        module_res = self._execute_module(
            module_name='ansible.builtin.ping',
            module_args={},
            task_vars=task_vars,
            # Делегирование на другой хост
            **{'delegate_to': 'bastion_host'}
        )
        result.update(module_res)
        return result
```

### Пример: Проверка подключения перед выполнением

Action-плагин может проверить доступность хоста перед запуском модуля.

```python
from ansible.module_utils.common.text.converters import to_bytes, to_text

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Проверка доступности хоста через low-level команду
        rc, stdout, stderr = self._low_level_execute_command(
            cmd='echo "host_reachable"',
            sudoable=False
        )
        
        if rc != 0:
            result['failed'] = True
            result['msg'] = f"Хост недоступен: {stderr}"
            return result
        
        # Продолжение нормальной работы
        module_res = self._execute_module(
            module_name='ansible.builtin.setup',
            module_args={},
            task_vars=task_vars
        )
        result.update(module_res)
        return result
```

## Основные методы класса ActionBase

| Метод | Описание |
| :--- | :--- |
| `_execute_module(name, args, task_vars, ...)` | Основной метод для запуска модуля на удаленном хосте. Рекомендуется всегда передавать `task_vars`. |
| `_transfer_file(local_path, remote_path)` | Копирует файл с контроллера на хост через текущее соединение (SSH/WinRM). |
| `_low_level_execute_command(cmd, ...)` | Выполняет сырую команду в Shell. Полезно для задач без использования Python-модулей. |
| `_make_tmp_path()` | Генерирует безопасный путь для временных файлов на удаленном хосте. |
| `_remove_tmp_path(path)` | Рекурсивно удаляет временную директорию на хосте. |
| `_fixup_perms2(remote_paths, ...)` | Устанавливает правильные права доступа на удалённые файлы. Используется после передачи файлов. |
| `_set_user_lock-context(user)` | Устанавливает контекст пользователя для блокировки (sudo su). |
| `_get_task_path()` | Возвращает путь к текущему выполняемому плейбуку. |
| `_task_vars_hash(task_vars)` | Вычисляет хеш переменных задачи для кеширования. |

## Доступ к контексту выполнения

*   `self._task`: Объект текущей задачи (доступ к `args`, `action`, `name`).
*   `self._play_context`: Параметры выполнения (`check_mode`, `diff`, `remote_addr`, `remote_user`).
*   `self._connection`: Объект активного соединения с хостом.
*   `self._templar`: Инструмент для рендеринга Jinja2-шаблонов.
*   `self._loader`: Объект для загрузки файлов (DataLoader).
*   `self._shared_loader_obj`: Объект для доступа к другим плагинам Ansible.

### Доступ к соединению

```python
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Получение информации о соединении
        connection = self._connection
        remote_addr = connection._connection_info.remote_addr
        transport = connection._connection_info.transport
        
        result['connection_info'] = {
            'host': remote_addr,
            'transport': transport
        }
        
        return result
```

## Коллекции и Action-плагины

Начиная с Ansible 2.10, предпочтительным способом распространения action-плагинов являются **Коллекции**.

### Структура коллекции

```
my_namespace/
  my_collection/
    plugins/
      action/
        my_custom_action.py      # Action-плагин
      modules/
        my_custom_module.py      # Соответствующий модуль (опционально)
      module_utils/
        my_shared_utils.py       # Общие библиотеки
```

### FQCN (Fully Qualified Collection Name)

```yaml
# В плейбуке
- name: Использование action-плагина из коллекции
  my_namespace.my_collection.my_module:
    param1: value1
    param2: value2
```

При использовании FQCN Ansible автоматически находит action-плагин с именем `my_module` в коллекции `my_namespace.my_collection`.

### Поиск плагинов в коллекциях

Ansible ищет action-плагины в коллекциях в порядке:

1.  Каталоги, указанные в `COLLECTIONS_PATHS` или `ANSIBLE_COLLECTIONS_PATH`.
2.  Стандартные пути: `~/.ansible/collections/`, `/usr/share/ansible/collections/`.
3.  Внутри установленных коллекций: `~/.ansible/collections/ansible_collections/namespace/collection/plugins/action/`.

## Рекомендации (Best Practices)

1.  **Используйте FQCN:** При вызове `_execute_module` всегда указывайте полное имя модуля (например, `ansible.builtin.shell`), чтобы избежать конфликтов.
2.  **Делегируйте разумно:** Если логика может быть реализована простым модулем на Python, используйте модуль. Action-плагины сложнее в отладке и тестировании.
3.  **Обработка исключений:** Используйте `AnsibleActionFail` для контролируемых ошибок. Необработанное исключение в плагине может привести к аварийному завершению всего процесса Ansible на контроллере.
4.  **Совместимость:** Помните, что Action-плагин использует Python контроллера. В Ansible 2.17+ это минимум Python 3.10.
5.  **Блокировка (Locking):** Action-плагин должен уметь работать в условиях конкурентного доступа, если плейбуки запускаются параллельно.
6.  **Идемпотентность:** Плагин должен быть идемпотентным — повторный запуск не должен вызывать нежелательных изменений.
7.  **Валидация аргументов:** Используйте `_VALID_ARGS` для объявления допустимых аргументов. Проверяйте обязательные параметры в методе `run()`.
8.  **Очистка:** Всегда удаляйте временные файлы на удалённых хостах в блоке `finally`.
9.  **Логирование:** Используйте `self._display.vvv()` или `self._display.debug()` вместо `print()` для вывода отладочной информации.

## Тестирование Action-плагинов

### Unit-тесты

Для unit-тестирования action-плагинов используйте `ansible.executor.test.action_module_action_plugin` или мокируйте зависимости:

```python
import pytest
from unittest.mock import MagicMock, patch

# Пример unit-теста для action-плагина
class TestMyActionPlugin:
    def test_run_success(self):
        """Тест успешного выполнения плагина"""
        # Создание мока для task
        task = MagicMock()
        task.args = {'src': '/local/file', 'dest': '/remote/file'}
        
        # Создание мока для play_context
        play_context = MagicMock()
        play_context.check_mode = False
        play_context.diff = False
        
        # Создание мока для templar
        templar = MagicMock()
        templar.template.side_effect = lambda x: x
        
        # Создание экземпляра плагина
        plugin = ActionModule(
            task=task,
            connection=MagicMock(),
            play_context=play_context,
            loader=MagicMock(),
            templar=templar,
            shared_loader_obj=MagicMock()
        )
        
        # Выполнение
        result = plugin.run(task_vars={})
        
        # Проверка
        assert result['changed'] == False
        assert 'msg' in result
```

### Интеграционные тесты

Для интеграционного тестирования используйте `ansible-test`:

```bash
# Запуск unit-тестов
ansible-test units my_namespace.my_collection.my_action_plugin

# Запуск интеграционных тестов
ansible-test integration my_namespace.my_collection.my_action_plugin

# Запуск тестов с конкретным Python
ansible-test units --python 3.11 my_namespace.my_collection.my_action_plugin
```

### Тестирование через плейбуки

Создайте тестовый плейбук для проверки плагина в реальных условиях:

```yaml
---
- name: Тест action-плагина
  hosts: test_host
  tasks:
    - name: Запуск кастомного action-плагина
      my_namespace.my_collection.my_module:
        src: /tmp/test_source
        dest: /tmp/test_dest
      register: plugin_result
      
    - name: Проверка результата
      ansible.builtin.assert:
        that:
          - plugin_result is not failed
          - plugin_result.msg is defined
```

## Отладка Action-плагинов

### Использование verbose-режима

```bash
# Уровень 1 (-v): общая информация
ansible-playbook test.yml -v

# Уровень 2 (-vv): информация о задачах
ansible-playbook test.yml -vv

# Уровень 3 (-vvv): информация о соединениях
ansible-playbook test.yml -vvv

# Уровень 4 (-vvvv): отладка SSH
ansible-playbook test.yml -vvvv
```

### Логирование в плагине

```python
from ansible.utils.display import Display

display = Display()

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        
        # Отладочный вывод (виден при -vvv)
        display.debug(f"Action plugin запущен с аргументами: {self._task.args}")
        display.vvv(f"Переменные задачи: {task_vars}")
        
        # Детальный вывод (виден при -vvvv)
        display.verbose(f"Информация о соединении: {self._connection}")
        
        return result
```

### Проверка атрибутов плагина

```bash
# Просмотр доступных атрибутов и методов
python3 -c "
from ansible.plugins.action import ActionBase
import inspect
members = [m for m in dir(ActionBase) if not m.startswith('__')]
for m in members:
    print(f'{m}: {getattr(ActionBase, m, None)}')
"
```

## Типовые ошибки и их решение (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `AttributeError: 'ActionModule' object has no attribute '_execute_module'` | Action-плагин не наследуется от ActionBase | Убедитесь, что класс наследуется от `ActionBase` |
| `AnsibleActionFail: Параметр 'dest' обязателен` | Не проверены обязательные аргументы | Добавьте проверку `_VALID_ARGS` в методе `run()` |
| `UndefinedError: 'task_vars' is undefined` | Не переданы переменные задачи | Всегда передавайте `task_vars` в `_execute_module` |
| `AnsibleError: No action detected for module` | Модуль не найден в `action_plugins/` или коллекции | Проверьте путь к плагину и FQCN |
| `ConnectionRefused: SSH connection failed` | Хост недоступен или настройки соединения неверны | Проверьте `inventory`, SSH-доступ и настройки `ansible.cfg` |
| `Jinja2Error: template error` | Некорректный Jinja2-шаблон в аргументе | Проверьте синтаксис шаблона, используйте `_templar.template()` |
| `Permission denied: нет прав на выполнение` | Недостаточно прав для выполнения команды | Используйте `become: true` или проверьте права доступа |
| `AnsibleError: module_utils not found` | Не найдена общая библиотека `module_utils` | Проверьте путь к `plugins/module_utils/` |

### Диагностические команды

```bash
# Просмотр всех доступных action-плагинов
ansible-doc -t action -l

# Просмотр документации конкретного плагина
ansible-doc -t action ansible.builtin.copy

# Просмотр исходного кода плагина
python3 -c "import ansible.plugins.action.copy; print(ansible.plugins.action.copy.__file__)"

# Проверка путей поиска плагинов
ansible-config dump | grep ACTION_PLUGINS

# Просмотр переменных окружения
ansible-config dump --only-changed | grep -i plugin
```

## Безопасность

- **Секреты:** Никогда не храните пароли или API-ключи в коде action-плагина. Используйте Ansible Vault или переменные окружения.
- **Валидация ввода:** Всегда валидируйте пользовательский ввод через `_VALID_ARGS` и явные проверки в `run()`.
- **Песочница:** Ограничивайте операции плагина最小必要ными привилегиями. Избегайте использования `become` без необходимости.
- **Проверка целостности:** При работе с файлами проверяйте контрольные суммы и подписи.
- **Логирование:** Записывайте критические операции в лог для аудита.

## Дополнительная информация

### Смотрите также

- [Разработка собственных модулей](./ansible_custom_modules.md) — логика выполнения на удаленном узле.
- [Callback-плагины](./ansible-callback-plugins.md) — обработка событий и результатов выполнения.
- [Основные концепции Ansible](./ansible_core_concepts.md) — архитектура взаимодействия Control и Managed Node.

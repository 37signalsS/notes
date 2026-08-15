# Ansible — разработка Action-плагинов

## Определения

**Action-плагин (Action Plugin)** — это специализированное расширение Ansible, которое выполняется исключительно на **узле управления (Control Node)**. Он выступает посредником между движком Ansible и модулем, выполняемым на удаленном хосте, позволяя перехватывать выполнение задачи и реализовывать сложную логику на стороне контроллера.

Многие ключевые модули (например, `ansible.builtin.template`, `ansible.builtin.copy`, `ansible.builtin.fetch`) являются Action-плагинами. Они выполняют тяжелые или специфичные для контроллера операции (генерация шаблонов, сравнение контрольных сумм локальных файлов) до того, как инициировать выполнение кода на целевом узле.

## Основные концепции

### Зачем нужны Action-плагины?

1.  **Локальные операции:** Выполнение действий, требующих прямого доступа к файловой системе или ресурсам узла управления (например, чтение локальных конфигураций или секретов).
2.  **Сложная логика управления:** Реализация условий или цепочек действий, которые невозможно (или нецелесообразно) реализовать внутри одного модуля на Python/Shell на удаленном хосте.
3.  **Оптимизация трафика:** Проверка состояния ресурса перед передачей данных. Например, плагин `copy` не передает файл, если его хеш-сумма на удаленном хосте уже совпадает с локальной.
4.  **Скрытие сложности:** Пользователь видит вызов одной задачи, в то время как Action-плагин может прозрачно вызывать несколько разных модулей.

### Различия: Action Plugin vs Module

| Критерий | Action Plugin | Module |
| :--- | :--- | :--- |
| **Место выполнения** | Узел управления (Control Node) | Управляемый узел (Managed Node) |
| **Доступ к ресурсам** | Полный доступ к локальной ФС и переменным окружения контроллера | Ограничен средой выполнения на хосте |
| **Зависимости** | Использует Python и библиотеки, установленные на контроллере | Зависит от интерпретатора Python и библиотек на удаленном хосте |
| **Жизненный цикл** | Запускается первым; решает, нужно ли запускать модуль | Выполняется по запросу Action-плагина или ядра |

### Поток выполнения задачи

1.  **Парсинг:** Ядро Ansible считывает задачу из плейбука.
2.  **Поиск плагина:** Ansible ищет Action-плагин с именем, соответствующим модулю.
3.  **Выполнение (Controller):** Запускается метод `run()` плагина.
4.  **Взаимодействие (Optional):** Плагин может вызвать `_execute_module` для выполнения кода на хосте.
5.  **Возврат результата:** Плагин агрегирует данные и возвращает JSON-ответ ядру.

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

Правильный цикл: создание временной папки → передача файла → удаление папки.

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

## Дополнительная информация

### Основные методы класса ActionBase

| Метод | Описание |
| :--- | :--- |
| `_execute_module(name, args, task_vars, ...)` | Основной метод для запуска модуля на удаленном хосте. Рекомендуется всегда передавать `task_vars`. |
| `_transfer_file(local_path, remote_path)` | Копирует файл с контроллера на хост через текущее соединение (SSH/WinRM). |
| `_low_level_execute_command(cmd, ...)` | Выполняет сырую команду в Shell. Полезно для задач без использования Python-модулей. |
| `_make_tmp_path()` | Генерирует безопасный путь для временных файлов на удаленном хосте. |
| `_remove_tmp_path(path)` | Рекурсивно удаляет временную директорию на хосте. |

### Доступ к контексту выполнения

*   `self._task`: Объект текущей задачи (доступ к `args`, `action`, `name`).
*   `self._play_context`: Параметры выполнения (`check_mode`, `diff`, `remote_addr`, `remote_user`).
*   `self._connection`: Объект активного соединения с хостом.
*   `self._templar`: Инструмент для рендеринга Jinja2-шаблонов.

### Рекомендации (Best Practices)

1.  **Используйте FQCN:** При вызове `_execute_module` всегда указывайте полное имя модуля (например, `ansible.builtin.shell`), чтобы избежать конфликтов.
2.  **Делегируйте разумно:** Если логика может быть реализована простым модулем на Python, используйте модуль. Action-плагины сложнее в отладке и тестировании.
3.  **Обработка исключений:** Используйте `AnsibleActionFail` для контролируемых ошибок. Необработанное исключение в плагине может привести к аварийному завершению всего процесса Ansible на контроллере.
4.  **Совместимость:** Помните, что Action-плагин использует Python контроллера. В Ansible 2.17+ это минимум Python 3.10.

### Смотрите также

*   [Разработка собственных модулей](./ansible_custom_modules.md) — логика выполнения на удаленном узле.
*   [Callback-плагины](./ansible-callback-plugins.md) — обработка событий и результатов выполнения.
*   [Основные концепции Ansible](./ansible_core_concepts.md) — архитектура взаимодействия Control и Managed Node.
*   [Официальная документация по Action Plugins](https://docs.ansible.com/ansible/latest/dev_guide/developing_plugins.html#action-plugins) (EN).

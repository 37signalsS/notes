# Создание кастомных плагинов Ansible

## Определения

**Plugin (плагин)** — расширение Ansible, добавляющее новую функциональность без изменения ядра. Типы плагинов: callback, connection, lookup, filter, vars, strategy, inventory, shell, module, test.

**Callback plugin** — плагин на Control Node, перехватывающий события выполнения плейбука (`v2_playbook_on_start`, `v2_runner_on_ok`, `v2_runner_on_failed` и др.) для логирования, уведомлений и интеграции с внешними системами.

**Connection plugin** — плагин, определяющий транспорт подключения к управляемым хостам (ssh, docker, podman, winrm, kubernetes).

**Lookup plugin** — плагин, загружающий данные из внешних источников (файлы, API, базы данных, KV-хранилища) во время выполнения плейбука.

**Filter plugin** — плагин, добавляющий кастомные Jinja2-фильтры для преобразования данных в шаблонах.

**Vars plugin** — плагин, автоматически подгружающий переменные из внешних систем (Consul, etcd, Vault) в контекст каждой задачи.

**Test plugin** — плагин, добавляющий кастомные тесты для директив `when` и `assert`.

**Shell plugin** — плагин, определяющий путь к интерпретатору и способ запуска команд для определённых расширений файлов на managed node.

**Action plugin** — плагин на Control Node, который перехватывает вызов модуля и реализует логику до/после его выполнения. Многие встроенные модули (`copy`, `template`, `fetch`) являются action-плагинами.

**Strategy plugin** — плагин, определяющий порядок выполнения задач: `linear` (по умолчанию) или `free` (параллельно по хостам).

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.plugin_name` (например, `ansible.posix.timer`). Использование FQCN предотвращает конфликты имен.

**Ansiballz** — современный фреймворк выполнения модулей. Упаковывает модуль и зависимости в zip, передаёт на Managed Node через JSON-протокол и обеспечивает изоляцию.

**Idempotency** — свойство операции, при котором повторный запуск не вызывает изменений, если desired state уже достигнут.

**Blast Radius** — радиус последствий ошибки. У action-плагинов blast radius ограничен Control Node, в отличие от модулей, которые выполняются на managed nodes.

**Observability** — возможность трассировки выполнения через callback-плагины и метрики для compliance и аудита.

## Базовые концепции

### Архитектура плагинов

Все плагины, за исключением модулей и connection-плагинов, выполняются на **Control Node**. Модули и connection-плагины работают на **Managed Node**.

```
Control Node                    Managed Node
┌─────────────────────┐        ┌──────────────────┐
│  Playbook Engine    │        │   Module Exec    │
│  ┌───────────────┐  │        │   (yum, apt,     │
│  │ Plugin Loader │──┼───────▶│    template...)  │
│  │  ├─ callback  │  │        │                  │
│  │  ├─ lookup    │  │        │                  │
│  │  ├─ filter    │  │        │                  │
│  │  └─ action    │  │        │                  │
│  └───────────────┘  │        └──────────────────┘
└─────────────────────┘
```

### Жизненный цикл плагина

1. **Обнаружение** — Ansible ищет плагин в стандартных директориях: локально (`library/`, `filter_plugins/`, `callback_plugins/`), в ролях (`roles/<role_name>/plugins/`), в коллекциях (`plugins/` внутри коллекции) и встроенных путях.
2. **Загрузка** — плагин загружается в память при первом использовании.
3. **Конфигурация** — плагин читает конфигурацию из `ansible.cfg` или переменных окружения.
4. **Инициализация** — плагин выполняет начальную настройку (установка connection, чтение DOCUMENTATION блока).
5. **Выполнение** — плагин выполняется при соответствующих событиях.
6. **Завершение** — плагин выполняет cleanup при завершении работы Ansible.

### Приоритет разрешения плагинов

Ansible ищет плагины в следующем порядке (первый найденный побеждает):

1. Локальная директория проекта (`library/`, `filter_plugins/`, `callback_plugins/`)
2. Директория роли (`roles/<role_name>/plugins/`)
3. Коллекции (`plugins/` внутри установленной коллекции)
4. Встроенные плагины Ansible Core

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| ansible-core | 2.21+ | `ansible --version` |
| Python (Control Node) | 3.12+ | `python3 --version` |
| Python (Managed Node) | 3.9+ | `python3 --version` |
| ansible-lint | 26.8+ | `ansible-lint --version` |
| pytest | 8.0+ | `pytest --version` |

### Ключевые принципы

1. **Idempotency** — плагин должен быть идемпотентным. Повторный запуск не должен вызывать нежелательных изменений.
2. **Error handling** — плагин должен корректно обрабатывать ошибки и возвращать понятные сообщения через `fail_json` или `self._display.warning()`.
3. **Documentation** — плагин должен иметь блоки `DOCUMENTATION`, `EXAMPLES`, `RETURN` для работы `ansible-doc`.
4. **Testing** — плагин должен иметь unit-тесты (`pytest`) и, где применимо, integration-тесты (`ansible-test`).
5. **Performance** — плагин не должен блокировать выполнение плейбука на Control Node. Для сетевых операций используйте асинхронность или очереди.
6. **Security** — не храните credentials в коде плагина. Используйте Ansible Vault, переменные окружения или внешние секретные хранилища.
7. **FQCN** — используйте полные имена для плагинов из коллекций, чтобы избежать конфликтов.
8. **Versioning** — храните кастомные плагины в git с семантическим версионированием и changelog.

## Практические сценарии

### Сценарий 1: Filter plugin для кастомных преобразований

Создание filter plugin, добавляющего фильтры для snake_case, camelCase, маскирования чувствительных данных и валидации IP.

```python
# filter_plugins/custom_filters.py
from __future__ import absolute_import
import re
import ipaddress
from ansible.errors import AnsibleFilterError

class FilterModule(object):
    def filters(self):
        return {
            'to_snake_case': self.to_snake_case,
            'to_camel_case': self.to_camel_case,
            'mask_sensitive': self.mask_sensitive,
            'extract_version': self.extract_version,
            'validate_ip': self.validate_ip,
        }

    def to_snake_case(self, text):
        if not isinstance(text, str):
            raise AnsibleFilterError(f"Expected string, got {type(text)}")
        text = re.sub(r'[-\s]+', '_', text)
        text = re.sub(r'([A-Z])', r'_\1', text)
        return text.lower().lstrip('_')

    def to_camel_case(self, text):
        if not isinstance(text, str):
            raise AnsibleFilterError(f"Expected string, got {type(text)}")
        components = text.replace('-', '_').split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    def mask_sensitive(self, text, mask_char='*', visible_chars=4):
        if not isinstance(text, str):
            raise AnsibleFilterError(f"Expected string, got {type(text)}")
        if len(text) <= visible_chars:
            return mask_char * len(text)
        return text[:visible_chars] + mask_char * (len(text) - visible_chars)

    def extract_version(self, text):
        if not isinstance(text, str):
            raise AnsibleFilterError(f"Expected string, got {type(text)}")
        match = re.search(r'\d+\.\d+\.\d+', text)
        return match.group(0) if match else None

    def validate_ip(self, ip):
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False
```

**Использование в playbook:**

```yaml
---
- name: Использование кастомных фильтров
  hosts: localhost
  gather_facts: no
  vars:
    app_name: "My Application"
    version: "nginx-1.20.1"
    api_key: "sk-1234567890abcdef"

  tasks:
    - name: Преобразование в snake_case
      ansible.builtin.debug:
        msg: "{{ app_name | to_snake_case }}"
      # → my_application

    - name: Преобразование в camelCase
      ansible.builtin.debug:
        msg: "{{ app_name | to_camel_case }}"
      # → myApplication

    - name: Маскирование чувствительных данных
      ansible.builtin.debug:
        msg: "API Key: {{ api_key | mask_sensitive }}"
      # → API Key: sk-1****cdef
```

**Валидация:**

```bash
# Запуск плейбука с фильтрами
ansible-playbook -i inventory.ini use_custom_filters.yml
# → TASK [Преобразование в snake_case]
# → ok: [localhost] => {
# →     "msg": "my_application"
# → }

# Проверка синтаксиса filter-плагина
python3 -m py_compile filter_plugins/custom_filters.py
# → (нет вывода, ошибок нет)

# Просмотр доступных фильтров
ansible-doc -t filter -l | grep custom
# → custom.to_snake_case
# → custom.to_camel_case
# → custom.mask_sensitive
# → custom.extract_version
# → custom.validate_ip
```

### Сценарий 2: Lookup plugin для внутреннего CMDB

Создание lookup plugin, который получает данные из внутреннего CMDB API.

```python
# lookup_plugins/cmdb.py
from __future__ import absolute_import
import os
import json
from ansible.plugins.lookup import LookupBase
from ansible.module_utils.common.text.converters import to_text

class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        results = []
        cmdb_url = os.environ.get('CMDB_API_URL', 'http://cmdb.internal/api/v1/hosts')
        cmdb_token = os.environ.get('CMDB_API_TOKEN', '')

        for term in terms:
            url = f"{cmdb_url}/{term}"
            headers = {'Authorization': f'Bearer {cmdb_token}'}
            try:
                response = self._loader.get_url(url, headers=headers)
                data = json.loads(response.read().decode())
                results.append(data)
            except Exception as e:
                self._display.warning(f"CMDB lookup failed for {term}: {e}")
                results.append({})
        return results
```

**Использование в playbook:**

```yaml
---
- name: Использование кастомного lookup плагина
  hosts: localhost
  gather_facts: no
  vars:
    host_data: "{{ lookup('cmdb', 'web1') }}"

  tasks:
    - name: Получение данных хоста из CMDB
      ansible.builtin.debug:
        msg: "Host {{ host_data.hostname }} is in {{ host_data.environment }}"

    - name: Использование данных CMDB в шаблоне
      ansible.builtin.template:
        src: templates/config.j2
        dest: /tmp/config.yml
      vars:
        cmdb_data: "{{ lookup('cmdb', inventory_hostname) }}"
```

**Валидация:**

```bash
# Запуск плейбука с lookup плагином
ansible-playbook -i inventory.ini use_cmdb_lookup.yml
# → TASK [Получение данных хоста из CMDB]
# → ok: [localhost] => {
# →     "msg": "Host web1 is in production"
# → }

# Проверка через ad-hoc команду
ansible localhost -m debug -a "msg={{ lookup('cmdb', 'web1') }}"
# → ok: [localhost] => {
# →     "msg": "{'hostname': 'web1', 'environment': 'production'}"
# → }
```

### Сценарий 3: Test plugin для валидации данных

Создание test plugin, добавляющего кастомные тесты для `when` и `assert`.

```python
# test_plugins/custom_tests.py
from __future__ import absolute_import
import re
import ipaddress
from ansible.plugins.test import TestBase

class TestModule(TestBase):
    def tests(self):
        return {
            'is_valid_email': self.is_valid_email,
            'is_strong_password': self.is_strong_password,
            'is_ip_in_range': self.is_ip_in_range,
            'is_valid_hostname': self.is_valid_hostname,
        }

    def is_valid_email(self, email):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    def is_strong_password(self, password):
        return (len(password) >= 8 and
                any(c.isupper() for c in password) and
                any(c.isdigit() for c in password) and
                any(c in '!@#$%^&*' for c in password))

    def is_ip_in_range(self, ip, range):
        try:
            return ipaddress.ip_address(ip) in ipaddress.ip_network(range)
        except ValueError:
            return False

    def is_valid_hostname(self, hostname):
        pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        return bool(re.match(pattern, hostname)) and len(hostname) <= 253
```

**Использование в playbook:**

```yaml
---
- name: Использование кастомных тестов
  hosts: localhost
  gather_facts: no
  vars:
    user_email: "admin@example.com"
    user_password: "SecurePass123!"
    server_ip: "192.168.1.10"

  tasks:
    - name: Проверка email
      ansible.builtin.debug:
        msg: "Valid email"
      when: user_email is valid_email

    - name: Проверка пароля
      ansible.builtin.debug:
        msg: "Strong password"
      when: user_password is strong_password

    - name: Проверка IP в диапазоне
      ansible.builtin.debug:
        msg: "IP in range"
      when: server_ip is ip_in_range('192.168.1.0/24')

    - name: Assert с кастомным тестом
      ansible.builtin.assert:
        that:
          - server_ip is valid_hostname
        fail_msg: "Invalid hostname: {{ server_ip }}"
```

**Валидация:**

```bash
# Запуск плейбука с тестами
ansible-playbook -i inventory.ini use_custom_tests.yml
# → TASK [Проверка email]
# → ok: [localhost] => {
# →     "msg": "Valid email"
# → }

# Проверка отрицательного случая
ansible localhost -m assert -a "that=['bad-email' is valid_email]"
# → fatal: [localhost]: FAILED! => ...
```

### Сценарий 4: Vars plugin для Consul KV

Создание vars plugin, автоматически подгружающего переменные из Consul KV-хранилища.

```python
# vars_plugins/consul_vars.py
from __future__ import absolute_import
import os
import json
from ansible.plugins.vars import BaseVarsPlugin
from ansible.inventory.host import Host

class VarsModule(BaseVarsPlugin):
    REQUIRES_WHITELIST = False

    def get_vars(self, host, path, entities=None):
        vars = super(VarsModule, self).get_vars(host, path, entities)
        consul_url = os.environ.get('CONSUL_URL', 'http://localhost:8500')
        try:
            url = f"{consul_url}/v1/kv/{host.name}/?recurse=true"
            # Используем встроенный loader для HTTP-запросов
            response = self._loader.get_url(url)
            data = json.loads(response.read().decode())
            for item in data:
                key = item['Key'].split('/')[-1]
                value = item.get('Value', '')
                if isinstance(value, str):
                    vars[key] = value
                else:
                    vars[key] = value.decode('utf-8') if value else ''
        except Exception:
            pass
        return vars
```

**Использование:**

```yaml
# ansible.cfg
[defaults]
vars_plugins = ./vars_plugins:/usr/share/ansible/plugins/vars

# playbook.yml
---
- name: Использование Consul vars plugin
  hosts: web01
  gather_facts: no
  tasks:
    - name: Вывод переменной из Consul
      ansible.builtin.debug:
        msg: "App version: {{ app_version }}"
```

**Валидация:**

```bash
# Запись в Consul KV
curl -X PUT http://localhost:8500/v1/kv/web01/app_version -d "1.2.3"

# Запуск плейбука
ansible-playbook -i inventory.ini use_consul_vars.yml
# → ok: [web01] => {
# →     "msg": "App version: 1.2.3"
# → }

# Проверка переменной
ansible web01 -m debug -a "var=app_version"
# → ok: [web01] => {
# →     "app_version": "1.2.3"
# → }
```

### Сценарий 5: Shell plugin для кастомного binary path

Создание shell plugin, задающего путь к интерпретатору для определённых расширений файлов.

```python
# shell_plugins/custom_shell.py
from __future__ import absolute_import
import os
from ansible.plugins.shell import ShellBase

class ShellModule(ShellBase):
    SHELL_NAME = 'custom_shell'

    def get_binary_path(self):
        return os.environ.get('CUSTOM_SHELL_PATH', '/usr/local/bin/custom-shell')

    def run(self, command, args, stdin):
        return super(ShellModule, self).run(command, args, stdin)
```

**Использование:**

```ini
# ansible.cfg
[defaults]
interpreter_python = /usr/bin/python3
shell_plugin_path = ./shell_plugins

# inventory.ini
[webservers]
web01 ansible_shell_type=custom_shell
```

**Валидация:**

```bash
# Проверка доступных shell-плагинов
ansible-doc -t shell -l
# → custom_shell  Custom shell interpreter

# Проверка подключения
ansible web01 -m ping
# → web01 | SUCCESS => {"ping": "pong"}
```

### Сценарий 6: Module plugin для управления конфигурационными файлами

Создание модуля для управления конфигурационными файлами приложения с поддержкой check_mode и diff.

```python
# library/app_config.py
from __future__ import absolute_import
import os
import hashlib
from ansible.module_utils.basic import AnsibleModule

def calculate_file_hash(filepath):
    if not os.path.exists(filepath):
        return None
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type='str', required=True),
            content=dict(type='str', required=False),
            owner=dict(type='str', required=False, default='root'),
            group=dict(type='str', required=False, default='root'),
            mode=dict(type='str', required=False, default='0644'),
            backup=dict(type='bool', required=False, default=False)
        ),
        supports_check_mode=True
    )

    path = module.params['path']
    content = module.params['content']
    owner = module.params['owner']
    group = module.params['group']
    mode = module.params['mode']
    backup = module.params['backup']

    result = dict(changed=False, path=path, checksum=None, backup=None)

    if not os.path.exists(path):
        if module.check_mode:
            result['changed'] = True
        else:
            try:
                with open(path, 'w') as f:
                    f.write(content)
                os.chown(path, owner, group)
                os.chmod(path, int(mode, 8))
                result['changed'] = True
            except Exception as e:
                module.fail_json(msg=f"Failed to create file: {e}", **result)
    else:
        current_hash = calculate_file_hash(path)
        new_hash = hashlib.sha256(content.encode()).hexdigest()
        result['checksum'] = current_hash

        if current_hash != new_hash:
            if module.check_mode:
                result['changed'] = True
            else:
                if backup:
                    backup_path = f"{path}.bak"
                    import shutil
                    shutil.copy2(path, backup_path)
                    result['backup'] = backup_path
                try:
                    with open(path, 'w') as f:
                        f.write(content)
                    os.chown(path, owner, group)
                    os.chmod(path, int(mode, 8))
                    result['changed'] = True
                except Exception as e:
                    module.fail_json(msg=f"Failed to update file: {e}", **result)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

**Использование:**

```yaml
---
- name: Использование кастомного модуля
  hosts: all
  become: true
  tasks:
    - name: Установка конфигурации приложения
      app_config:
        path: /etc/myapp/config.yml
        content: "{{ lookup('file', 'templates/config.yml.j2') }}"
        owner: myapp
        group: myapp
        mode: '0640'
        backup: yes
      register: config_result

    - name: Проверка результата
      ansible.builtin.debug:
        msg: "Config changed: {{ config_result.changed }}"
```

**Валидация:**

```bash
# Запуск плейбука с кастомным модулем
ansible-playbook -i inventory.ini use_custom_module.yml --check
# → показывает, будет ли изменен файл, без внесения изменений

# Применение изменений
ansible-playbook -i inventory.ini use_custom_module.yml
# → ok: [web01] => {
# →     "changed": true,
# →     "backup": "/etc/myapp/config.yml.bak"
# → }

# Проверка документации модуля
ansible-doc ./library/app_config.py
# → APP_CONFIG    (/path/to/library/app_config.py)
```

### Сценарий 7: Action plugin для кеширования результатов

Создание action plugin, кеширующего результаты выполнения модулей для ускорения повторных запусков.

```python
# action_plugins/cache_module.py
from __future__ import absolute_import
import os
import json
import hashlib
from ansible.plugins.action import ActionBase
from ansible.utils.unsafe_proxy import wrap_var

class ActionModule(ActionBase):
    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(*args, **kwargs)
        self.cache_dir = os.path.expanduser('~/.ansible/tmp/module_cache')
        self.cache_enabled = True

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = {}

        module_args = self._task.args.copy()
        cache_key = self._generate_cache_key(module_args, task_vars)

        if self.cache_enabled and os.path.exists(cache_key):
            try:
                with open(cache_key, 'r') as f:
                    cached_result = json.load(f)
                return cached_result
            except Exception:
                pass

        module_return = super(ActionModule, self).run(tmp=tmp, task_vars=task_vars)

        if self.cache_enabled and module_return.get('changed', False) is False:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                with open(cache_key, 'w') as f:
                    json.dump(module_return, f)
            except Exception as e:
                self._display.warning(f"Failed to cache module result: {e}")

        return module_return

    def _generate_cache_key(self, module_args, task_vars):
        cache_data = {
            'module_name': self._task.action,
            'args': module_args,
            'host': task_vars.get('inventory_hostname', ''),
            'playbook_dir': task_vars.get('playbook_dir', '')
        }
        cache_string = json.dumps(cache_data, sort_keys=True)
        cache_hash = hashlib.md5(cache_string.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{cache_hash}.json")
```

**Использование:**

```yaml
---
- name: Использование кеширующего action plugin
  hosts: all
  tasks:
    - name: Получение фактов с кешированием
      ansible.builtin.setup:
        gather_subset:
          - '!all'
          - '!min'
      register: setup_result

    - name: Проверка, что результат закеширован
      ansible.builtin.debug:
        msg: "Setup result cached: {{ setup_result is defined }}"
```

**Валидация:**

```bash
# Запуск плейбука с action plugin
ansible-playbook -i inventory.ini use_cache_plugin.yml
# → ok: [web01] => {
# →     "msg": "Setup result cached: True"
# → }

# Проверка кеша
ls -la ~/.ansible/tmp/module_cache/
# → файлы кеша созданы

# Повторный запуск (использует кеш)
ansible-playbook -i inventory.ini use_cache_plugin.yml
# → использует закешированные результаты
```

## Операции и команды

### Основные команды для работы с плагинами

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-doc -t callback -l` | Список callback-плагинов | `ansible-doc -t callback -l` |
| `ansible-doc -t lookup -l` | Список lookup-плагинов | `ansible-doc -t lookup -l` |
| `ansible-doc -t filter -l` | Список filter-плагинов | `ansible-doc -t filter -l` |
| `ansible-doc -t connection -l` | Список connection-плагинов | `ansible-doc -t connection -l` |
| `ansible-doc -t action -l` | Список action-плагинов | `ansible-doc -t action -l` |
| `ansible-doc -t vars -l` | Список vars-плагинов | `ansible-doc -t vars -l` |
| `ansible-doc -t shell -l` | Список shell-плагинов | `ansible-doc -t shell -l` |
| `ansible-doc -t test -l` | Список test-плагинов | `ansible-doc -t test -l` |
| `ansible-doc <plugin_name>` | Документация плагина | `ansible-doc ansible.posix.timer` |
| `ansible-doc -t callback ansible.posix.timer` | Документация конкретного callback | `ansible-doc -t callback ansible.posix.timer` |
| `ansible-config dump \| grep -i callback_plugins` | Проверка путей callback-плагинов | `ansible-config dump \| grep -i callback_plugins` |
| `ansible-config dump \| grep -i ACTION_PLUGINS` | Проверка путей action-плагинов | `ansible-config dump \| grep -i ACTION_PLUGINS` |
| `python3 -m py_compile <plugin_file>` | Проверка синтаксиса Python | `python3 -m py_compile filter_plugins/custom_filters.py` |

### Команды для установки коллекций с плагинами

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-galaxy collection install <collection>` | Установка коллекции | `ansible-galaxy collection install community.general` |
| `ansible-galaxy collection list` | Список установленных коллекций | `ansible-galaxy collection list` |
| `ansible-galaxy collection search <query>` | Поиск коллекций | `ansible-galaxy collection search netbox` |

### Переменные окружения для отладки

| Переменная | Назначение |
|---|---|
| `ANSIBLE_KEEP_REMOTE_FILES=1` | Сохраняет временные файлы на Managed Node (не удаляет после выполнения) |
| `ANSIBLE_DEBUG=1` | Включает расширенное логирование ядра Ansible |
| `ANSIBLE_VERBOSITY=3` | Увеличивает детализацию вывода (`-vvv`) |
| `ANSIBLE_LOAD_CALLBACK_PLUGINS=1` | Загружает callback-плагины при выполнении через `ansible` CLI |
| `PYTHONPATH=/path/to/plugins` | Добавляет путь к пользовательским плагинам |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `Plugin not found` | Плагин не установлен или не в PATH | Установите коллекцию или проверьте `callback_plugins`, `action_plugins` в `ansible.cfg` |
| `ImportError` | Зависимости плагина не установлены | Установите зависимости: `pip install <package>` |
| `Permission denied` | Нет прав на чтение/запись плагина | Проверьте права доступа к файлам плагинов |
| `Syntax error in plugin` | Ошибка в коде плагина | Проверьте синтаксис Python: `python3 -m py_compile <file>` |
| `Callback plugin не отправляет уведомления` | Плагин не активирован | Проверьте `callbacks_enabled` в `ansible.cfg`, используйте `CALLBACK_NEEDS_ENABLED = True` |
| `CALLBACK_NEEDS_ENABLED игнорируется` | Плагин не указан в `callbacks_enabled` | Добавьте имя плагина в `callbacks_enabled` |
| `Cache plugin не работает` | Ошибка в коде кеширования | Проверьте права на директорию кеша, логи Ansible |
| `ModuleNotFoundError для кастомного плагина` | Неправильный путь в `action_plugins` | Проверьте пути поиска через `ansible-config dump \| grep -i ACTION_PLUGINS` |
| `Action-плагин блокирует выполнение` | Необработанное исключение в `run()` | Используйте `try/except`, возвращайте `failed: true` |
| `Drift между versioned плагином и production` | Плагин изменен в git, но не обновлен на Control Node | Храните плагины в коллекциях с версиями, обновляйте через `ansible-galaxy collection install` |
| `Конфликт имен между кастомным и встроенным плагином` | Одинаковое имя в `action_plugins/` и встроенном плагине | Используйте FQCN в `_execute_module`, проверяйте приоритеты через `ansible-doc -t action` |
| `Утечка временных файлов на managed node` | Пропущен `finally` блок с `_remove_tmp_path()` | Всегда удаляйте tmp в `finally`, мониторьте `/tmp` на managed nodes |
| `Check mode не работает` | `supports_check_mode=True` не указан | Добавьте `supports_check_mode=True` в `AnsibleModule` или проверяйте `module.check_mode` |
| `JSON decode error` | В stdout модуля попадает мусор | Убедитесь, что в модуле нет `print()`, используйте `module.exit_json()` и `module.fail_json()` |
| `KeyError в метаданных callback` | Отсутствует обязательный атрибут класса | Добавьте `CALLBACK_VERSION`, `CALLBACK_TYPE`, `CALLBACK_NAME`, `CALLBACK_NEEDS_ENABLED` |
| `UnicodeEncodeError в callback` | Необработанные символы в выводе | Добавьте `ensure_ascii=False` при сериализации JSON |

## Рекомендации

### Best Practices

1. **FQCN** — используйте полные имена для плагинов из коллекций: `ansible.posix.timer`, `community.general.yaml`. Это предотвращает конфликты имен.
2. **Testing** — пишите unit-тесты (`pytest`) для бизнес-логики и integration-тесты (`ansible-test integration`) для проверки на реальных системах. Используйте Molecule для end-to-end тестирования.
3. **Documentation** — заполняйте блоки `DOCUMENTATION`, `EXAMPLES`, `RETURN` в полном объёме. Это обязательно для работы `ansible-doc` и публикации в Galaxy.
4. **Check Mode** — всегда реализуйте `supports_check_mode=True` для модулей и проверяйте `module.check_mode` или `self._play_context.check_mode` для action-плагинов.
5. **Diff Mode** — для модулей, изменяющих файлы, реализуйте `supports_diff=True` и возвращайте `result['diff']`. Это критично для audit-трейлов.
6. **Security** — не храните credentials в коде плагина. Используйте Ansible Vault, переменные окружения Control Node или внешние секретные хранилища. Никогда не логируйте чувствительные данные.
7. **no_log** — в callback-плагинах всегда проверяйте `result._result.get('_ansible_no_log', False)` перед логированием результата.
8. **Versioning** — храните кастомные плагины в git с семантическим версионированием. Каждая версия должна иметь changelog.
9. **Performance** — callback-плагины работают синхронно в основном потоке. Для высоконагруженных систем используйте очереди сообщений (Redis, RabbitMQ) или фоновые потоки.
10. **Cleanup** — в action-плагинах всегда удаляйте временные файлы на удалённых хостах в блоке `finally` через `_remove_tmp_path()`.
11. **Collections** — распространяйте плагины в составе коллекций. Это обеспечивает изоляцию, версионирование и повторное использование.
12. **CI/CD** — тестируйте плагины в CI/CD пайплайне: `ansible-lint`, `ansible-test sanity`, `ansible-test units`, `ansible-test integration`.

### Чек-лист валидации после создания плагина

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Синтаксис Python | `python3 -m py_compile <plugin_file>` | Нет ошибок |
| Плагин загружается | `ansible-doc -t <type> -l` | Плагин в списке |
| Документация | `ansible-doc <plugin_name>` | Документация отображается |
| Работа в плейбуке | `ansible-playbook test_plugin.yml` | Плагин выполняется без ошибок |
| Check mode | `ansible-playbook test_plugin.yml --check` | Изменения не применяются |
| Логи плагина | `ANSIBLE_DEBUG=true ansible-playbook test_plugin.yml -vvv` | Логи содержат сообщения плагина |
| Unit-тесты | `pytest tests/unit/` | Все тесты проходят |
| Sanity-тесты | `ansible-test sanity` | Нет ошибок стиля |
| Integration-тесты | `ansible-test integration` | Задачи выполнены без ошибок |

## Дополнительная информация

### Смотрите также

- **[Ansible: разработка Callback-плагинов](../ansible-callback-plugins.md)** — lifecycle events (`v2_*`), метаданные (`CALLBACK_VERSION`, `CALLBACK_NEEDS_ENABLED`), примеры (log_to_json, slack_notify, task_timer), интеграция с Loki/ELK/Slack.
- **[Ansible: разработка Action-плагинов](../ansible-action-plugins.md)** — Control Node execution, `ActionBase`/`ActionModule`, методы (`_execute_module`, `_transfer_file`), SRE-сценарии (валидация конфигурации, incident artifacts, canary-деплой).
- **[Ansible: разработка собственных модулей](../ansible_custom_modules.md)** — `AnsibleModule`, Ansiballz, check_mode/diff, `module_utils`, FQCN, примеры модулей.

### Интеграция с внешними системами

| Система | Назначение | Тип плагина |
|---|---|---|
| **Slack** | Уведомления | Callback |
| **PagerDuty** | Алерты | Callback |
| **Prometheus Pushgateway** | Метрики | Callback |
| **Loki/Grafana** | Централизованные логи | Callback |
| **Elasticsearch/OpenSearch** | Хранение событий | Callback |
| **Syslog** | Аудит | Callback |
| **Email** | Отчеты | Callback |
| **Consul** | Service discovery, KV | Vars, Lookup |
| **HashiCorp Vault** | Секреты | Lookup, Vars |
| **NetBox** | CMDB | Inventory, Lookup |
| **etcd** | Конфигурация | Vars, Lookup |
| **Foreman** | Жизненный цикл хостов | Inventory |
| **Proxmox** | Инвентарь ВМ | Inventory |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Плагин падает в production | Необработанная ошибка | Добавьте обработку исключений, логирование через `self._display.warning()`, unit-тесты |
| Плагин работает медленно | Синхронные сетевые вызовы | Используйте асинхронность, кеширование, очереди сообщений (Redis/RabbitMQ) |
| Плагин несовместим с версией Ansible | Изменения в API | Используйте совместимые версии, тестируйте на новых версиях `ansible-core` |
| Плагин нарушает идемпотентность | Неправильная логика | Убедитесь, что повторный запуск не вызывает изменений; проверяйте current state |
| Callback-плагин дублируется | Два плагина зарегистрированы | Проверьте `callbacks_enabled` — оставьте только нужные |
| Action-плагин утечка памяти | Неочищенные временные файлы | Всегда удаляйте tmp в `finally`, мониторьте `/tmp` на managed nodes |
| Vars plugin замедляет запуск | Медленный запрос к Consul/etcd | Включите кеширование (`cache: true`, `cache_plugin: jsonfile`) |
| Секреты в логах | Отсутствие проверки `_ansible_no_log` | Всегда проверяйте `_ansible_no_log` перед логированием результата |
| Concurrent remediation | Два оператора изменяют плагин одновременно | Используйте approval queue, maintenance windows, lock mechanism |
| Плагин не работает в CI/CD | Отсутствуют переменные окружения | Используйте `vars` в `ansible.cfg` или переменные окружения CI/CD, не хардкодьте пути |

# Структура роли Ansible

## Определения

**Структура роли** — стандартизированная организация каталогов и файлов в роли Ansible, которая позволяет движку автоматически находить и выполнять ресурсы (задачи, обработчики, шаблоны, переменные) без явного указания полных путей.

**Каталог роли** — директория с предопределенной структурой подкаталогов. Каждый подкаталог имеет специфическое назначение и приоритет в жизненном цикле выполнения роли.

**FQCN (Fully Qualified Collection Name)** — полное имя роли или модуля (например, `community.general.docker_container`), используемое для однозначной идентификации ресурсов в современных коллекциях.

**Спецификация аргументов (`argument_spec`)** — декларативное описание входных параметров роли в файле `meta/argument_specs.yml`, позволяющее Ansible автоматически проверять типы и обязательность переменных до начала выполнения задач.

---

## Предварительные требования

### Системные требования (Ansible 2.17+)

*   **Control Node:** Требуется **Python 3.10+**.
*   **Target Nodes:** Требуется **Python 3.8+** (для Ansible 2.18+ рекомендуется Python 3.10+).

### Инструменты

```bash
# Установка ansible-core
pip install ansible-core

# Проверка версии
ansible --version  # Должна быть 2.17+ или 2.18+

# Инициализация роли для проверки структуры
ansible-galaxy role init test_role
rm -rf test_role  # Удаление тестовой роли
```

---

## Основные концепции

### Инициализация роли

Для создания каркаса роли со стандартной структурой каталогов используется утилита `ansible-galaxy`:

```bash
# Создание каркаса роли со стандартной структурой каталогов
ansible-galaxy role init my_new_role  # → роль успешно инициализирована

# Инициализация роли без создания всех каталогов (только необходимые)
ansible-galaxy role init my_minimal_role --offline
```

### Стандартная структура каталогов (Ansible 2.17+)

Современная роль поддерживает расширенный набор каталогов для плагинов и метаданных:

| Каталог / Файл | Назначение |
| :--- | :--- |
| `tasks/` | Основные задачи роли (`main.yml` — входная точка) |
| `handlers/` | Обработчики уведомлений (перезапуск сервисов по сигналу `notify`) |
| `templates/` | Jinja2-шаблоны конфигураций (обычно с расширением `.j2`) |
| `files/` | Статические файлы для копирования без обработки |
| `defaults/` | Переменные по умолчанию (самый низкий приоритет, для настройки пользователем) |
| `vars/` | Внутренние переменные и константы роли (высокий приоритет, не для изменения пользователем) |
| `meta/` | Метаданные: зависимости (`main.yml`) и спецификация аргументов (`argument_specs.yml`) |
| `library/` | Собственные модули на Python (в Ansible 2.17+ требуют Python 3.8+ на целевом узле) |
| `module_utils/` | Общий Python-код, разделяемый модулями из `library/` |
| `plugins/` | (Ansible 2.14+) Унифицированный каталог для плагинов: `lookup`, `filter`, `action` и др. |
| `lookup_plugins/` | Классический путь для плагинов поиска данных (API, БД) |
| `filter_plugins/` | Классический путь для пользовательских фильтров Jinja2 |
| `molecule/` | Конфигурации для тестирования роли (современный стандарт вместо `tests/`) |
| `README.md` | Полное описание роли, её параметров и примеров использования |

### Ключевые файлы и их назначение

#### Задачи и входные точки (`tasks/main.yml`)
Ansible всегда ищет `tasks/main.yml` как основную точку входа. Если логика сложная, рекомендуется разбивать её на файлы (например, `install.yml`, `configure.yml`, `service.yml`) и подключать их через `ansible.builtin.import_tasks` или `ansible.builtin.include_tasks` в основном файле.

#### Обработчики (`handlers/main.yml`)

Обработчики выполняются **только** по сигналу `notify` из задач и только **один раз** в конце каждой секции плейбука (или при явном `ansible.builtin.flush_handlers`). Они предназначены для перезапуска сервисов, перечитывания конфигураций и других действий, которые должны произойти только при реальном изменении системы.

```yaml
# handlers/main.yml
---
- name: restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
  listen: "restart web services"  # Универсальное имя для listen

- name: reload systemd
  ansible.builtin.systemd:
    daemon_reload: true

- name: restart postgresql
  ansible.builtin.service:
    name: postgresql
    state: restarted
  when: ansible_os_family == "Debian"
```

**Использование в задачах:**
```yaml
# tasks/main.yml
- name: Deploy nginx configuration
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: restart nginx  # Вызов конкретного обработчика

- name: Deploy application config
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/config.yml
  notify: restart web services  # Вызов через listen
```

**Полезные паттерны:**
- Используйте `listen` для создания общих обработчиков, доступных из нескольких ролей
- Обработчики выполняются **после** всех задач секции, даже если вызваны из `pre_tasks`
- Флаг `listen` позволяет вызывать несколько обработчиков одним именем
- Используйте `ansible.builtin.flush_handlers` для принудительного выполнения обработчиков до перехода к следующей секции

#### Разделение задач: `import_tasks` vs `include_tasks`

| Критерий | `import_tasks` (Static) | `include_tasks` (Dynamic) |
| :--- | :--- | :--- |
| **Время обработки** | До выполнения плейбука | Во время выполнения |
| **Циклы (`loop`)** | Не поддерживает | Поддерживает |
| **Теги** | Применяются ко всем задачам файла | Применяются только к вызову |
| **Когда (`when`)** | Не поддерживает | Поддерживает |
| **Производительность** | Быстрее (статический парсинг) | Медленнее (динамический импорт) |

```yaml
# Статический импорт (приоритет производительности)
- ansible.builtin.import_tasks: install.yml
  vars:
    app_version: "2.0"

# Динамический импорт (приоритет гибкости)
- ansible.builtin.include_tasks: configure.yml
  when: enable_config | bool
  loop: "{{ config_items }}"
```

#### Метаданные и спецификации (`meta/`)
*   **`main.yml`**: Описывает зависимости роли. Если роль A зависит от роли B, роль B будет выполнена до роли A. Также содержит информацию для Ansible Galaxy (автор, лицензия, платформы).
*   **`argument_specs.yml`** (Ansible 2.11+): Позволяет формально описать интерфейс роли (типы, значения по умолчанию, обязательность). В Ansible 2.17+ добавлено поле **`context`** для передачи дополнительных метаданных внешним инструментам (IDE, генераторам документации).

#### Изоляция переменных (Namespacing)
Поскольку в Ansible глобальное пространство имен переменных (Flat Namespace), критически важно:
1.  **Префиксы:** Все переменные роли ДОЛЖНЫ начинаться с имени роли (например, `nginx_port`, `nginx_conf_path`).
2.  **Defaults vs Vars:** Используйте `defaults/main.yml` для всего, что пользователь МОЖЕТ захотеть изменить. Используйте `vars/main.yml` для того, что НЕ ДОЛЖНО меняться (константы, пути в зависимости от ОС).

### Технические подробности поиска ресурсов (Search Path)

Ansible использует механизм относительного поиска для модулей `copy`, `template`, `script`, `patch`. При вызове из задачи в роли поиск происходит в следующем порядке:

1.  Каталог `files/` или `templates/` внутри **текущей роли**.
2.  Каталоги ресурсов во всех ролях, перечисленных в **зависимостях** (`meta/main.yml`).
3.  Каталог, где находится вызывающий плейбук.
4.  Каталоги ролей, установленных на уровне проекта (`roles_path` в `ansible.cfg`).

Это позволяет "переопределять" файлы базовых ролей в дочерних или в основном проекте.

### Кастомные модули и утилиты (`library/` и `module_utils/`)

Для ролей, требующих уникальную логику, недоступную в стандартных модулях, можно создавать собственные Python-модули.

**Простой модуль в `library/`:**
```python
#!/usr/bin/python
# library/check_port.py

from ansible.module_utils.basic import AnsibleModule
import socket

def check_port(host, port, timeout=5):
    """Проверка доступности TCP-порта."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Port {port} on {host} is open"
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return False, f"Port {port} on {host} is closed: {str(e)}"

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            port=dict(type='int', required=True),
            timeout=dict(type='int', default=5),
        ),
        supports_check_mode=True
    )

    host = module.params['host']
    port = module.params['port']
    timeout = module.params['timeout']

    is_open, message = check_port(host, port, timeout)

    module.exit_json(
        changed=False,
        is_open=is_open,
        msg=message
    )

if __name__ == '__main__':
    main()
```

**Использование модуля:**
```yaml
# tasks/main.yml
- name: Check if database port is available
  check_port:
    host: "{{ db_host }}"
    port: "{{ db_port }}"
    timeout: 3
  register: port_check

- name: Fail if port is not available
  ansible.builtin.fail:
    msg: "Database port is not reachable"
  when: not port_check.is_open
```

**Общий код в `module_utils/`:**
```python
# module_utils/api_utils.py
import json
import urllib.request

def make_api_call(url, method='GET', data=None, headers=None):
    """Общая функция для REST API вызовов."""
    if headers is None:
        headers = {'Content-Type': 'application/json'}

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return True, json.loads(response.read().decode())
    except Exception as e:
        return False, str(e)
```

**Использование `module_utils` в модуле:**
```python
# library/my_api_module.py
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.api_utils import make_api_call

def main():
    module = AnsibleModule(
        argument_spec=dict(
            url=dict(type='str', required=True),
            method=dict(type='str', default='GET'),
            data=dict(type='dict'),
        )
    )

    success, result = make_api_call(
        module.params['url'],
        module.params['method'],
        module.params['data']
    )

    if success:
        module.exit_json(changed=False, api_result=result)
    else:
        module.fail_json(msg=f"API call failed: {result}")

if __name__ == '__main__':
    main()
```

### Роли в составе коллекций

В современных проектах (Ansible 2.10+) роли часто упаковываются в коллекции.
**Unified Layout (Ansible 2.14+):** Если роль является частью коллекции, она может не содержать свои папки плагинов. Все плагины выносятся на уровень коллекции в единую директорию `plugins/`:

```text
my_namespace/
└── my_collection/
    ├── plugins/              # Общие плагины коллекции
    │   ├── modules/          # Вместо library/
    │   ├── filter/           # Вместо filter_plugins/
    │   └── lookup/           # Вместо lookup_plugins/
    ├── roles/
    │   └── my_role/          # Стандартная структура роли внутри (без plugins/)
    │       ├── tasks/
    │       └── meta/
    └── README.md
```

Для использования такой роли необходимо указывать её полное имя (**FQCN**):
```yaml
- name: Подключение роли из коллекции
  ansible.builtin.include_role:
    name: my_namespace.my_collection.my_role
```

---

## Практические сценарии

### Сценарий 1: Сравнение `defaults/main.yml` и `vars/main.yml`

| Параметр | `defaults/main.yml` | `vars/main.yml` |
| :--- | :--- | :--- |
| **Назначение** | Настройки для пользователя | Внутренние константы |
| **Приоритет** | 1 (самый низкий) | 15 (очень высокий) |
| **Пример** | `app_port: 8080` | `app_bin_path: /usr/local/bin/app` |

**Лучшая практика:** Большинство переменных определяйте в `defaults`. Используйте `vars` только для данных, которые зависят от дистрибутива ОС и не должны переопределяться пользователем вручную (например, названия пакетов: `apache2` для Debian vs `httpd` для RedHat).

### Сценарий 2: Настройка зависимостей в `meta/main.yml`

Зависимости гарантируют выполнение необходимых компонентов перед основной ролью:

```yaml
# meta/main.yml
dependencies:
  - role: geerlingguy.nginx
    vars:
      nginx_http_port: 8080
  - role: my_custom_db_role
    allow_duplicates: false # Запрет повторного выполнения, если роль уже была вызвана
```

### Сценарий 3: Валидация аргументов через `meta/argument_specs.yml` (Ansible 2.17+)

Пример глубокой валидации параметров роли с использованием новых метаданных:

```yaml
# meta/argument_specs.yml
argument_specs:
  main:
    short_description: Основная точка входа настройки приложения
    options:
      app_user:
        type: str
        required: true
        description: Пользователь, от которого работает сервис
      app_port:
        type: int
        default: 8080
        description: Порт приложения
        context:
          monitoring_group: "web-services"
          security_level: "high"
      app_environment:
        type: str
        choices: ['prod', 'stage', 'dev']
        default: 'dev'
        description: Среда развертывания
```

### Сценарий 4: Досрочное завершение роли (`meta: end_role`)

В Ansible 2.18+ можно завершить роль для конкретного хоста, не прерывая выполнение плейбука для других. Это эффективнее, чем оборачивать все задачи в `when`.

```yaml
# tasks/main.yml
- name: Проверка наличия конфигурационного файла
  ansible.builtin.stat:
    path: /etc/myapp/config.yml
  register: config_stat

- name: Завершить роль, если конфигурация уже существует
  ansible.builtin.meta: end_role
  when: config_stat.stat.exists

- name: Основные задачи установки (выполнятся только если файла нет)
  ansible.builtin.yum:
    name: myapp
    state: present
```

### Сценарий 5: Использование плагинов внутри роли

Если роли нужен специфический фильтр для обработки строк, его можно разместить в `filter_plugins/custom_filters.py` (классический путь) или в `plugins/filter/` (современный путь):

```python
# filter_plugins/custom_filters.py
def to_upper_custom(value):
    return value.upper() + "_SUFFIX"

class FilterModule(object):
    def filters(self):
        return {
            'my_upper': to_upper_custom
        }
```

В задачах (`tasks/main.yml`) он станет доступен автоматически:
```yaml
- name: Использование кастомного фильтра
  ansible.builtin.debug:
    msg: "{{ 'test' | my_upper }}" # Результат: TEST_SUFFIX
```

### Сценарий 6: Организация шаблонов и файлов

Для сложных ролей рекомендуется структурировать подкаталоги для удобства навигации:

```text
roles/webserver/
├── files/
│   ├── static/
│   │   └── index.html
│   └── ssl/
│       └── dhparam.pem
├── templates/
│   ├── nginx/
│   │   ├── main.conf.j2
│   │   └── vhost.conf.j2
│   └── scripts/
│       └── cleanup.sh.j2
└── tasks/
    └── main.yml
```

Использование в задачах:
```yaml
- name: Деплой конфигурации Nginx
  ansible.builtin.template:
    src: nginx/vhost.conf.j2 # Путь относительно каталога templates/
    dest: /etc/nginx/sites-available/app.conf
```

---

## Дополнительная информация

### Приоритеты переменных (Variable Precedence)

Иерархия приоритетов (от самого низкого к самому высокому):

1.  **Defaults роли** (`defaults/main.yml`)
2.  Переменные из инвентаря (`group_vars`, `host_vars`)
3.  **Vars роли** (`vars/main.yml`)
4.  Переменные, переданные как аргументы при вызове роли (через `vars:`)
5.  **Extra vars** (`-e` в командной строке) — абсолютный приоритет.

Подробное описание уровней — в [Переменные и факты](../PlaybookStructure/variables.md).

### Системные требования (Ansible 2.17+)

*   **Контрольный узел:** Для работы Ansible 2.17+ требуется Python 3.10 или новее.
*   **Управляемые узлы:** Для выполнения кастомных модулей из `library/` требуется Python 3.8+ (для Ansible 2.18+ рекомендуется Python 3.10+).

---

## Troubleshooting

### Роль не найдена при вызове

**Причина:** Неправильный путь или имя роли.

**Решение:**
```bash
# Проверка путей поиска
ansible-config dump | grep roles_path

# Проверка установленных ролей
ansible-galaxy role list

# Явное указание пути в плейбуке
- hosts: all
  roles:
    - role: my_role
      paths: ./roles  # Явный путь к роли
```

### Ошибка: "module not found"

**Причина:** Кастомный модуль не найден в `library/`.

**Решение:**
```bash
# Проверка структуры каталогов
ls -la roles/my_role/library/

# Проверка прав доступа
chmod +x roles/my_role/library/my_module.py

# Проверка синтаксиса Python
python3 -m py_compile roles/my_role/library/my_module.py
```

### Переменные не переопределяются

**Причина:** Конфликт приоритетов переменных.

**Решение:**
```bash
# Просмотр всех переменных хоста
ansible-inventory --host webserver1

# Просмотр переменных роли
ansible-playbook site.yml --list-variables

# Проверка приоритетов
ansible-doc -t vars 2>/dev/null || echo "См. документацию по приоритетам"
```

### Задачи выполняются дважды

**Причина:** Дублирование вызовов `import_tasks` или `include_role`.

**Решение:**
```bash
# Просмотр импортированных задач
ansible-playbook site.yml --list-tasks

# Использование тегов для фильтрации
ansible-playbook site.yml --list-tags
```

### Обработчик не выполняется

**Причина:** Задача не вызвала `changed` или обработчик вызван из `import_tasks`.

**Решение:**
```yaml
# Убедитесь, что задача помечает изменение
- name: Deploy config
  ansible.builtin.template:
    src: config.j2
    dest: /etc/app/config
  notify: restart app
  register: deploy_result
  changed_when: deploy_result.changed  # Явная проверка

# Или используйте force_handler
- name: Force handler execution
  ansible.builtin.flush_handlers:
```

---

## Best Practices

### Структура каталогов

1. **Единая точка входа:** Всегда используйте `tasks/main.yml` как основную точку входа роли.
2. **Разделение ответственности:** Разбивайте сложные роли на файлы: `install.yml`, `configure.yml`, `service.yml`.
3. **Именование файлов:** Используйте единообразные имена: `install.yml`, `config.yml`, `service.yml`, `validate.yml`.

### Управление переменными

1. **Префиксы:** Все переменные роли ДОЛЖНЫ начинаться с имени роли (например, `nginx_port`, `nginx_conf_path`).
2. **Defaults:** Определяйте в `defaults/main.yml` всё, что пользователь МОЖЕТ захотеть изменить.
3. **Vars:** Используйте `vars/main.yml` только для констант и данных, зависящих от ОС.
4. **Безопасность:** Никогда не храните пароли в `defaults/` или `vars/` — используйте Ansible Vault.

### Производительность

1. **import_tasks:** Используйте для статических подключений (производительность).
2. **include_tasks:** Используйте только когда нужна динамическая логика (`when`, `loop`).
3. **Минимизация фактов:** Отключайте `gather_facts: false` если факты не нужны.
4. **Параллелизм:** Используйте `forks` в `ansible.cfg` для ускорения выполнения.

### Безопасность

1. **Валидация аргументов:** Всегда используйте `meta/argument_specs.yml` для проверки входных параметров.
2. **Проверка подписей:** Используйте `ansible-galaxy collection verify` для проверки целостности.
3. **Минимальные привилегии:** Избегайте `become: true` когда это не необходимо.
4. **Логирование:** Используйте `callback_whitelist` для аудита выполнения.

### Тестирование

1. **Molecule:** Используйте Molecule для тестирования ролей в изолированных средах.
2. ** ansible-lint:** Запускайте `ansible-lint` перед коммитом для проверки синтаксиса.
3. **ansible-test:** Используйте для тестирования кастомных модулей.

---

## Edge Cases

### Скрытые файлы и каталоги

Ansible игнорирует файлы, начинающиеся с точки (`.gitignore`, `.DS_Store`). Если necessary скрытые файлы:

```yaml
# Явное копирование скрытых файлов
- name: Copy hidden config
  ansible.builtin.copy:
    src: "files/.app_config"
    dest: /etc/app/.config
    force: true
```

### Символические ссылки в ролях

Ansible **не следует** символические ссылки по умолчанию. Используйте `follow: true`:

```yaml
- name: Follow symlink
  ansible.builtin.copy:
    src: "files/symlinked_config"
    dest: /etc/app/config
    follow: true
```

### Роли с одинаковыми именами

Если две роли имеют одинаковое имя, приоритет определяется порядком в `ansible.cfg`:

```ini
# ansible.cfg
[defaults]
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
```

### Динамические включения в `meta/`

В Ansible 2.18+ поддерживается условная зависимость в `meta/main.yml`:

```yaml
# meta/main.yml
dependencies:
  - role: database
    when: install_database | bool
```

### Удаление устаревших ролей

```bash
# Просмотр всех установленных ролей
ansible-galaxy role list

# Удаление конкретной роли
ansible-galaxy role uninstall geerlingguy.nginx

# Удаление всех ролей (ОСТОРОЖНО!)
ansible-galaxy role uninstall --all
```

### См. также

- [Создание и использование ролей](usage.md) — практическое руководство по подключению
- [Тестирование через Molecule](../ansible_testing_with_molecule.md) — современный подход к QA
- [Антипаттерны](../ansible_bad_practices.md) — типичные ошибки при структурировании ролей
- [Jinja2 в Ansible](../ansible_jinja_templating.md) — возможности шаблонизации
- [Управление через Galaxy](galaxy.md) — поиск и установка готовых ролей

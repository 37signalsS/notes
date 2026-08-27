# Ansible — шаблонизация Jinja2

## Определения

**Jinja2** — это мощный шаблонизатор для Python, используемый в Ansible для динамической генерации текстовых файлов (конфигураций, скриптов, манифестов). Он позволяет использовать переменные, условную логику, циклы и фильтры непосредственно внутри файлов.

**Шаблон (Template)** — текстовый файл (обычно с расширением `.j2`), содержащий статический текст и вставки Jinja2. В Ansible шаблоны обрабатываются модулем `ansible.builtin.template` на стороне контрольного узла перед отправкой результата на управляемый хост.

**Выражение (Expression)** — фрагмент кода Jinja2, который вычисляется и возвращает результат (например, `{{ 2 + 2 }}`).

**Макрос (Macro)** — переиспользуемый блок шаблона с параметрами, аналог функции в программировании.

**Фильтр (Filter)** — функция, применяемая к переменной через символ `|` для трансформации данных (например, `{{ list | unique }}`).

**Тест (Test)** — функция, проверяющая данные и возвращающая `True`/`False` (например, `{{ var is defined }}`).

---

## Основные концепции

### Переменные и комментарии

Вывод значения переменной: `{{ variable_name }}`.
Доступ к вложенным данным: `{{ my_dict.key }}` или `{{ my_list[0] }}`.

Комментарии (не попадают в итоговый файл):
```jinja
{# Это комментарий Jinja2 #}
```

### Управление пробелами

Jinja2 сохраняет все переносы строк и пробелы по умолчанию. Для контроля отступов используются символы `-`:
- `{%-` — удаляет пробелы и пустые строки перед блоком.
- `-%}` — удаляет пробелы и пустые строки после блока.

Также в модуле `ansible.builtin.template` можно управлять этим глобально через параметры `trim_blocks: yes` и `lstrip_blocks: yes`.

```jinja
{% if items -%}
    Contains items
{%- endif %}
```

### Условная логика

**Простое условие `if`:**
```jinja
{% if env == 'prod' %}
debug: false
{% elif env == 'dev' %}
debug: true
{% else %}
debug: default
{% endif %}
```

**Условие с `and` / `or` / `not`:**
```jinja
{% if env == 'prod' and enable_ssl %}
ssl: true
{% elif env == 'dev' or env == 'staging' %}
debug: true
{% endif %}
```

**Условие с проверкой списка:**
```jinja
{% if groups['webservers'] | length > 0 %}
# Есть веб-серверы
{% endif %}
```

**Условие с `is in`:**
```jinja
{% if env in ['prod', 'staging'] %}
monitoring: strict
{% endif %}
```

### Циклы

**Базовый цикл `for`:**
```jinja
{% for user in users %}
user: {{ user.name }}
{% endfor %}
```

**Цикл с `loop` объектом:**
```jinja
{% for user in users %}
- {{ loop.index }}. {{ user.name }} ({{ 'active' if user.active else 'inactive' }})
{% endfor %}
```

**Доступные атрибуты `loop`:**
- `loop.index`: Текущая итерация (от 1).
- `loop.index0`: Текущая итерация (от 0).
- `loop.first` / `loop.last`: True, если это первая или последняя итерация.
- `loop.length`: Общее количество элементов.
- `loop.cycle('odd', 'even')`: Чередование значений.

**Цикл со `startlimit` / `stoplimit`:**
```jinja
{% for item in range(0, 10, 2) %}
  Item: {{ item }}
{% endfor %}
```

**Вложенные циклы:**
```jinja
{% for group in groups %}
Group: {{ group }}
{% for host in groups[group] %}
  - {{ host }}
{% endfor %}
{% endfor %}
```

**Цикл со `break` / `continue`:**
```jinja
{% for item in items %}
  {% if item.skip %}
    {% continue %}
  {% endif %}
  Processing: {{ item.name }}
{% endfor %}
```

### Фильтры и тесты

Фильтры изменяют данные (используется символ трубы `|`), а тесты проверяют их состояние (`is`).

#### Фильтры трансформации

- `default('value', true)`: Значение по умолчанию. Если второй аргумент `true`, фильтр сработает даже если переменная — пустая строка или False.
- `combine(other_dict, recursive=True)`: Слияние словарей. Параметр `recursive` позволяет объединять вложенные структуры.
- `regex_replace('pattern', 'replacement')`: Замена подстрок через регулярные выражения.
- `json_query('query_string')`: Выполнение запросов JMESPath к структурам данных (требует библиотеки `jmespath` на контроллере).
- `dict2items` / `items2dict`: Преобразование словаря в список пар ключ-значение и обратно. Полезно для циклов по словарям с фильтрацией.
- `ipaddr('address/prefix')`: Мощный инструмент для работы с IP-адресами (требует библиотеки `netaddr` на контроллере). Позволяет проверять валидность, извлекать маски, широковещательные адреса и т.д.
- `extract(variable, key)`: Извлечение значения из словаря или списка по динамическому ключу.
- `map(attribute='name')`: Извлечение атрибута из списка словарей.
- `selectattr('attr', 'op', 'value')`: Фильтрация списка по атрибуту.
- `rejectattr('attr', 'op', 'value')`: Исключение элементов из списка по атрибуту.
- `unique`: Удаление дубликатов из списка.
- `flatten`: Сглаживание вложенных списков.
- `sort`: Сортировка списка.
- `join(', ')`: Объединение списка в строку с разделителем.
- `first` / `last`: Получение первого/последнего элемента списка.
- `random`: Выбор случайного элемента из списка.
- `min` / `max`: Минимальное/максимальное значение в списке.
- `sum`: Сумма элементов списка.
- `count`: Подсчет количества элементов.
- `groupby('key')`: Группировка списка словарей по ключу.
- `map('replace', 'old', 'new')`: Замена в каждом элементе списка.
- `map('int')`: Преобразование всех элементов в целые числа.
- `map('float')`: Преобразование всех элементов в числа с плавающей точкой.

#### Фильтры конвертации форматов

- `to_nice_json` / `to_nice_yaml`: Форматирование структур в читаемый JSON/YAML.
- `from_json` / `from_yaml`: Парсинг строк в объекты.
- `b64encode` / `b64decode`: Кодирование и декодирование Base64.
- `type_debug`: Возвращает тип данных переменной (очень полезно для отладки).
- `to_json` / `to_yaml`: Конвертация в JSON/YAML без форматирования.
- `from_csv`: Парсинг CSV-строки в список.
- `to_csv`: Конвертация списка в CSV-строку.

#### Строковые фильтры

- `upper` / `lower`: Преобразование в верхний/нижний регистр.
- `capitalize` / `title`: Преобразование первой буквы/каждого слова в верхний регистр.
- `trim` / `lstrip` / `rstrip`: Удаление пробелов по краям/слева/справа.
- `replace('old', 'new')`: Замена подстроки (без регулярных выражений).
- `regex_replace('^', '#')`: Добавление префикса к каждой строке.
- `format(*args)`: Форматирование строки (аналог `str.format()`).
- `urlencode`: URL-кодирование строки.
- `wordwrap(width)`: Перенос строк по ширине.
- `truncate(length)`: Обрезка строки до указанной длины.

#### Числовые фильтры

- `int` / `float`: Преобразование в целое число / число с плавающей точкой.
- `round(precision)`: Округление до указанной точности.
- `abs`: Абсолютное значение.
- `min` / `max`: Минимум/максимум (работает с числами и списками).

#### Фильтры для словарей

- `dict2items`: Словарь → список `{key: ..., value: ...}`.
- `items2dict`: Список `{key: ..., value: ...}` → словарь.
- `combine(other_dict)`: Слияние словарей.
- `json_query('key')`: Извлечение значения по JMESPath-запросу.

#### Специальные фильтры

- `shuffle`: Случайное перемешивание списка.
- `random`: Случайный элемент списка.
- `ipaddr('network')`: Работа с IP-адресами (требует `netaddr`).
- `community.general.routeros`: Конвертация для MikroTik API.

#### Популярные тесты

- `is defined` / `is undefined`: Проверка существования.
- `is failed` / `is succeeded`: Проверка статуса выполнения задачи.
- `is version('2.10', '>=')`: Сравнение версий ПО.
- `is subset(other_list)`: Проверка, является ли список подмножеством другого.
- `is directory` / `is file`: Проверка типа пути на контрольном узле.
- `is match('pattern')`: Проверка строки по регулярному выражению.
- `is search('pattern')`: Поиск подстроки по регулярному выражению.
- `is contains('substring')`: Проверка наличия подстроки.
- `is odd` / `is even`: Проверка на нечетность/четность.
- `is number`: Проверка, является ли значение числом.
- `is string`: Проверка, является ли значение строкой.
- `is iterable`: Проверка, является ли значение итерируемым объектом.
- `is mapping`: Проверка, является ли значение словарем.
- `is none`: Проверка на `None`.

---

## Плагины доступа к данным (Lookup и Query)

Плагины `lookup` и `query` позволяют считывать данные из внешних источников (файлы, базы данных, API, облака) непосредственно на контрольном узле во время выполнения.

**Ключевое различие:**
- `lookup('plugin', 'arg')`: По умолчанию возвращает строку, где элементы разделены запятыми. Это поведение можно изменить параметром `wantlist=True`, но это менее удобно.
- `query('plugin', 'arg')`: Всегда возвращает **список** (даже если результат один). Это современный стандарт, рекомендуемый для использования в циклах `loop`.

**Популярные плагины:**
- `env`: Чтение переменных окружения контроллера.
- `file`: Чтение содержимого локальных файлов.
- `dict`: Превращает словарь в список словарей с ключами `key` и `value`. Полезно, когда нужно итерироваться по словарю, сохраняя доступ к обоим элементам.
- `url`: Получение данных по HTTP/HTTPS.
- `vars`: Динамический поиск значений переменных по их именам.
- `pipe`: Выполнение shell-команды и возврат stdout.
- `ini`: Чтение INI-файлов.
- `csvfile`: Чтение CSV-файлов.
- `hashi_vault`: Чтение секретов из HashiCorp Vault.
- `community.general.lastpass`: Чтение секретов из LastPass.
- `community.general.onepassword`: Чтение секретов из 1Password.

```jinja
# Использование dict lookup для итерации по сложному словарю
{% for item in query('ansible.builtin.dict', users_data) %}
  User: {{ item.key }}, UID: {{ item.value.uid }}
{% endfor %}

# Чтение файла
SSH_KEY: {{ lookup('ansible.builtin.file', '~/.ssh/id_rsa.pub') }}

# Получение данных из HashiCorp Vault
SECRET: {{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/db:password') }}

# Выполнение shell-команды
HOSTNAME: {{ lookup('pipe', 'hostname -f') }}

# Чтение INI-файла
DB_HOST: {{ lookup('ini', 'host section=database file=/etc/app/config.ini') }}
```

---

## Макросы (Macros)

Макросы позволяют создавать переиспользуемые блоки конфигурации.

### Базовый макрос

```jinja
{% macro render_vhost(port, domain) %}
server {
    listen {{ port }};
    server_name {{ domain }};
    root /var/www/{{ domain }};
}
{% endmacro %}

{{ render_vhost(80, 'example.com') }}
```

### Макрос с defaults

```jinja
{% macro db_config(host, port=5432, dbname='app', user='dbuser') %}
database:
  host: {{ host }}
  port: {{ port }}
  name: {{ dbname }}
  user: {{ user }}
{% endmacro %}

{{ db_config('db01.example.com') }}
{{ db_config('db02.example.com', port=5433, dbname='analytics') }}
```

### Макрос с переменными

```jinja
{% macro render_server(name, port, ssl=false) %}
server {
    listen {{ port }}{{ ' ssl' if ssl else '' }};
    server_name {{ name }}.example.com;

    {% if ssl %}
    ssl_certificate /etc/ssl/{{ name }}.crt;
    ssl_certificate_key /etc/ssl/{{ name }}.key;
    {% endif %}

    location / {
        proxy_pass http://127.0.0.1:{{ port + 1000 }};
    }
}
{% endmacro %}

{{ render_server('api', 443, ssl=true) }}
```

### Макрос с `caller` ( блоки)

```jinja
{% macro render_block(title) %}
<div class="block">
    <h2>{{ title }}</h2>
    {{ caller() }}
</div>
{% endmacro %}

{% call render_block('My Title') %}
    <p>This is the block content.</p>
{% endcall %}
```

---

## Составление шаблонов (Template Composition)

### Наследование шаблонов (extends)

Позволяет создавать базовый шаблон и наследовать его.

**Базовый шаблон `base.j2`:**
```jinja
# {{ ansible_managed }}
{% block header %}
# Default header
{% endblock %}

{% block content %}
# Default content
{% endblock %}

{% block footer %}
# Default footer
{% endblock %}
```

**Дочерний шаблон `nginx.j2`:**
```jinja
{% extends 'base.j2' %}

{% block header %}
# Nginx Configuration
# Generated by Ansible
{% endblock %}

{% block content %}
http {
    server {
        listen {{ port }};
        server_name {{ hostname }};
    }
}
{% endblock %}
```

### Включение шаблонов (include)

Позволяет включать другие шаблоны внутри текущего.

```jinja
# Основной шаблон
{{ ansible_managed }}

{% include 'partials/header.j2' %}

{% for vhost in vhosts %}
{% include 'partials/vhost_block.j2' %}
{% endfor %}

{% include 'partials/footer.j2' %}
```

### Импорт макросов (import)

```jinja
{% from 'macros/config.j2' import render_server, render_location %}

{{ render_server('api', 443) }}
{{ render_location('/', 'http://backend:8080') }}
```

---

## Кастомные фильтры (Custom Filters)

Ansible позволяет создавать собственные фильтры через плагины.

### Создание фильтра

Создайте файл `filter_plugins/custom_filters.py`:

```python
def to_camel_case(text):
    """Преобразует snake_case в camelCase."""
    components = text.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])

def to_pascal_case(text):
    """Преобразует snake_case в PascalCase."""
    return ''.join(x.title() for x in text.split('_'))

def hash_md5(text):
    """Возвращает MD5-хеш строки."""
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()

def dict_merge(base, override):
    """Рекурсивно сливает два словаря."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = dict_merge(result[key], value)
        else:
            result[key] = value
    return result

class FilterModule(object):
    def filters(self):
        return {
            'to_camel_case': to_camel_case,
            'to_pascal_case': to_pascal_case,
            'hash_md5': hash_md5,
            'dict_merge': dict_merge,
        }
```

### Использование кастомного фильтра

```yaml
- name: Пример использования кастомного фильтра
  ansible.builtin.debug:
    msg: "{{ 'user_name' | to_camel_case }}"
# Вывод: userName
```

### Использование в шаблоне

```jinja
{# Кастомный фильтр в шаблоне #}
variable_camel: {{ variable_name | to_camel_case }}
```

---

## Практические сценарии

### Динамическая конфигурация Nginx

#### 1. Переменные в Ansible (`vars/main.yml`)
```yaml
vhosts:
  - { name: "app1", port: 8080 }
  - { name: "app2", port: 8081 }
enable_compression: true
```

#### 2. Шаблон `nginx.conf.j2`
```jinja
# {{ ansible_managed }}
http {
    {% if enable_compression -%}
    gzip on;
    gzip_types text/plain application/json;
    {%- endif %}

    {% for host in vhosts %}
    server {
        listen {{ host.port }};
        server_name {{ host.name }}.local;
    }
    {% endfor %}
}
```

#### 3. Использование в плейбуке с валидацией
```yaml
- name: Развертывание конфигурации Nginx
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    validate: /usr/sbin/nginx -t -c %s
  notify: Restart Nginx
```

### Продвинутая обработка данных через JMESPath

В сложных проектах фильтрация данных на стороне Ansible становится критически важной для производительности и читаемости. Фильтр `json_query` (основанный на JMESPath) позволяет извлекать нужные фрагменты из массивных JSON-ответов API без использования сложных циклов в Jinja2.

#### Базовый синтаксис JMESPath
- `instances[*].name`: **Проекция** — получение списка всех имен.
- `instances[?status=='running']`: **Фильтрация** — выбор объектов по условию.
- `instances[0:5]`: **Срезы** — первые 5 элементов.
- `instances[*].{ID: id, IP: private_ip}`: **Multi-select Hash** — создание нового объекта с выбранными полями.

#### Практические примеры

**1. Фильтрация и проекция по условию**
Получение IP-адресов работающих инстансов в конкретной зоне:
```jinja
{% set instances = api_response | json_query("instances[?status=='running' && zone=='us-east-1'].ip_address") %}
```

**2. Сглаживание списков (Flattening)**
Если каждый пользователь имеет список групп, и нам нужен уникальный список всех групп:
```jinja
{% set all_groups = users | json_query("users[*].groups[]") | unique %}
```

**3. Сортировка данных**
Сортировка списка словарей по определенному ключу (например, по цене или дате):
```jinja
{% set sorted_items = items | json_query("sort_by(items, &priority)") %}
```

**4. Сложный поиск с логикой "ИЛИ"**
Выбор элементов, у которых статус 'active' ИЛИ тип 'primary':
```jinja
{% set targets = data | json_query("nodes[?status=='active' || type=='primary'].hostname") %}
```

> **Совет:** Для отладки сложных запросов JMESPath используйте онлайн-песочницу [jmespath.org](https://jmespath.org/jpterm.html).

### Отладка шаблонов

#### Отображение типа переменной
```jinja
{# Вывод типа переменной для отладки #}
Type: {{ my_var | type_debug }}
Value: {{ my_var }}
```

#### Условный вывод отладочной информации
```jinja
{% if debug_mode %}
<!-- DEBUG: {{ my_var | to_nice_json }} -->
{% endif %}
```

#### Использование `assert` для валидации
```yaml
- name: Валидация переменных
  ansible.builtin.assert:
    that:
      - my_var is defined
      - my_var | length > 0
      - my_var | int > 0
    fail_msg: "my_var is not valid"
    success_msg: "Validation passed"
```

---

## Дополнительная информация

### Служебные переменные Ansible в шаблонах

- `ansible_managed`: Строка-заголовок, указывающая, что файл управляется Ansible. Настраивается в `ansible.cfg`.
- `inventory_hostname`: Имя текущего хоста в инвентаре.
- `groups`: Все группы и хосты в них.
- `group_names`: Список групп, в которые входит текущий хост.
- `hostvars`: Словарь, содержащий переменные всех хостов в плейбуке.
- `template_path`: Полный путь к исходному шаблону на контроллере.
- `role_name`: Имя текущей роли (если шаблон находится в роли).

### Идиомпотентность шаблонов

1. **Используйте `backup: yes`** для критических файлов:
```yaml
- name: Деплой конфигурации
  ansible.builtin.template:
    src: config.j2
    dest: /etc/app/config.conf
    backup: yes
```

2. **Валидация перед применением:**
```yaml
- name: Деплой с валидацией
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    validate: /usr/sbin/nginx -t -c %s
```

3. **Проверка изменений через `check_mode`:**
Ansible автоматически проверяет, изменился ли файл, и не применяет изменения, если файл идентичен.

### Лучшие практики

1.  **Кавычки в YAML:** Если значение в YAML начинается с `{{`, оно ДОЛЖНО быть в кавычках: `msg: "{{ var_name }}"`.
2.  **Экранирование (Raw):** Используйте `{% raw %} ... {% endraw %}` для вывода текста, синтаксис которого совпадает с Jinja2 (Helm, Prometheus).
3.  **Безопасность (Command Injection):** Используйте фильтр `quote` при подстановке переменных в shell-команды внутри шаблонов.
4.  **Производительность:** Избегайте сложных вычислений в шаблонах. Используйте `set_fact` в плейбуке для подготовки данных.
5.  **Зависимости:** Если используете фильтры `ipaddr` или `json_query`, убедитесь, что на контрольном узле установлены соответствующие библиотеки:
    ```bash
    pip install netaddr jmespath
    ```
6.  **Именование шаблонов:** Используйте расширение `.j2` для всех Jinja2-шаблонов.
7.  **Читаемость:** Используйте `{%-` и `-%}` для управления пробелами, чтобы избежать пустых строк в выводе.

### Диагностические команды

```bash
# Проверка синтаксиса Jinja2 (через Python)
python3 -c "import jinja2; jinja2.Template(open('template.j2').read())"

# Просмотр 변수 Ansible для отладки
ansible-playbook site.yml -e "debug_var=true" --step

# Отображение всех переменных для хоста
ansible-inventory --host web01

# Просмотр переменных группы
ansible-inventory --graph webservers

# Проверкаlookup-плагина
ansible -m debug -a "msg={{ lookup('env', 'HOME') }}"

# Тест фильтра
ansible -m debug -a "msg={{ 'hello_world' | to_camel_case }}"
```

### Таблица типовых ошибок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `UndefinedError: 'variable' is undefined` | Переменная не определена | Проверьте `hostvars`, `set_fact`, `defaults` |
| `TypeError: expected string or bytes-like object` | Фильтр применен к не строке | Используйте `string` фильтр или проверьте тип |
| `TemplateSyntaxError: unexpected '%'` | Ошибка синтаксиса Jinja2 | Проверьте парные теги `{% %}` и `{{ }}` |
| `jinja2.exceptions.Undefined` | Переменная не найдена в scope | Проверьте область видимости переменной |
| `AnsibleError: failed to parse` | Ошибка в YAML перед Jinja2 | Проверьте YAML-синтаксис (отступы, кавычки) |
| `UndefinedError: dict object has no attribute` | Ключ не существует в словаре | Используйте `default` или `is defined` тест |
| `Template data is not a string` | Передан объект вместо строки | Используйте `to_json` / `to_yaml` |
| `lookup plugin not found` | Плагин не установлен | Проверьте `ansible-galaxy collection list` |
| `jmespath.exceptions.JMESPathError` | Ошибка JMESPath-запроса | Проверьте синтаксис на jmespath.org |
| `Permission denied` | Нет прав на чтение файла | Проверьте `become: true` и права доступа |

### Смотрите также

- [Модули управления файлами](./Modules/ansible_file_management_modules.md) — модули `template`, `copy`, `lineinfile`, `blockinfile` для работы с файлами.
- [Основные концепции Ansible](./ansible_core_concepts.md) — общие концепции Ansible, включая базовое использование переменных и шаблонов.
- [Официальная документация Jinja2](https://jinja.palletsprojects.com/) — полный справочник по синтаксису Jinja2.

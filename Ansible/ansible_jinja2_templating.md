# Ansible: Шаблонизация с Jinja2

## Определения

**Jinja2** — это популярный шаблонизатор для Python, используемый Ansible для динамического создания файлов. Он позволяет вставлять в текстовые файлы переменные, выполнять циклы и условные конструкции, обеспечивая гибкость в управлении конфигурациями. Шаблоны обрабатываются модулем `ansible.builtin.template`, и по соглашению, файлы шаблонов имеют расширение `.j2`.

## Основные концепции: Синтаксис и конструкции Jinja2

### Переменные
Если вы хотите использовать значения ранее определенных переменных в Jinja, вы просто указываете имя переменной в фигурных скобках, например `{{ myvar }}`.

Для переменных в словарях мы пишем значения через точку, например `{{ person.name }}`. Правилом хорошего тона является ставить отступы перед двойными фигурными скобками и после двойных фигурных скобок.

Если переменной не существует, то Jinja просто не выведет ничего. По умолчанию переменные приводятся к самому универсальному типу, то есть если переменной нет, будет использована пустая строка для вывода, что и даст нам “ничего" в шаблоне.

**ВНИМАНИЕ!** Для установки переменной внутри шаблона воспользуйтесь командой `{% set имя_переменной = значение %}`.

### Цикл `for`
Для вывода значений в цикле, либо отображения всех элементов списка, мы можем использовать конструкцию `for`.

В общем виде выглядит это следующим образом:
```jinja
{% for item in inventory %} - начало конструкции, inventory это список
{{ item.name }}:{{ item.value }} - указываем имена вложенных объектов через точку, если у вас список из примитивных типов, например строк, item выведет значение
{% endfor %} - обязательно закрываем for
```

**ВНИМАНИЕ!** При передаче строки в `for`, он разберет ее на символы. Например, строка “name” породит четыре элемента в цикле.

**ВНИМАНИЕ!** Для вывода индекса в цикле можно использовать конструкцию `{{ loop.index0 }}` (индекс начинается с 0) или `{{ loop.index }}` (индекс начинается с 1).

### Условия `if`
Для условного вывода блоков в Jinja вы можете воспользоваться конструкцией `if`.
```jinja
{% if showConfig %} - showConfig это переменная типа boolean
Here is config
{% else %} - опциональный параметр
Here is no config
{% endif %} - как и с for - закрываем конструкцию
```

В `if` можно так же использовать конструкцию `in` для проверки, что ключ есть в словаре:
```jinja
{% if 'priority' in data %}
Priority: {{ data['priority'] }}
{% endif %}
```

Для определения, что переменная определена, есть конструкция `is defined`, и `is not defined` в противоположном случае.
```jinja
{% if data is defined %}
// data goes wshhhhhh
{% endif %}
```

Условия в `if` можно комбинировать с помощью конструкций булевой алгебры - `and` и `or`:
```jinja
{% if data is defined and showConfig %} - showConfig должен быть true И data должна быть определена
// data goes wshhhhhh
{% endif %}

{% if data is defined or showConfig %} - showConfig должен быть true, ИЛИ data должна быть определена
// data goes wshhhhhh
{% endif %}
```

Эти выражения можно объединять в скобки для проверок выражений в правильном порядке.
```jinja
{% if (data is defined or showConfig) and 'priority' in config %}
// showConfig должен быть true, ИЛИ data должна быть определена И ПРИ ЭТОМ priroity в config
{% endif %}
```

### Фильтры

Фильтры — это специальные функции, применяемые к переменным. Фильтры применяются к переменным через служебный символ `|` и возвращают результат уже обработанных переменных.

#### `default`
Один из часто используемых фильтров в шаблонах.
```jinja
{{ first_name | default("there") }} - если first_name не определен, то выведется "there".
{{ first_name | default("there", true) }} - если first_name не определен ИЛИ определен как пустая строка, то выведется "there".
```

#### `replace`
Фильтр `replace` служит для замены подстроки в строковом значении, например:
```jinja
{{ department | replace("Personnel", "HR") }}
```
Если мы хотим ограничить количество замен, мы можем добавить аргумент, указывающий, сколько раз нам надо заменить подстроку:
```jinja
{{ department | replace("Personnel", "HR", 1) }}
```

Символ `|` служит не только для применения фильтров, но и для **цепочки фильтров**:
```jinja
Hello {{ name | default("family name") | replace("family","second") }}!
```
Результат: `Hello second name!`

## Практические сценарии

### Упражнение 1

**Вопрос:** Каким будет результат выполнения следующего Jinja шаблона?

**Шаблон:**
```jinja
storage:
  dbPath: {{ mongodb_storage_dbpath | default("./") }}
  directoryPerDB: {{ mongodb_storage_dirperdb | to_nice_json }}
  engine: {{ mongodb_storage_engine }}
  {% if mongodb_storage_engine == 'mmapv1' -%}
  mmapv1:
    quota:
      enforced: {{ mongodb_storage_quota_enforced | to_nice_json }}
      maxFilesPerDB: {{ mongodb_storage_quota_maxfiles }}
    smallFiles: {{ mongodb_storage_smallfiles | to_nice_json }}
  {% endif -%}
  {% if mongodb_storage_engine == 'wiredTiger' -%}
  wiredTiger:
    engineConfig:
    {% if mongodb_wiredtiger_cache_size is defined -%}
      cacheSizeGB: {{ mongodb_wiredtiger_cache_size }}
    {% endif -%}
      directoryForIndexes: {{ mongodb_wiredtiger_directory_for_indexes | to_nice_json }}
  {%- endif %}
```

**Переменные:**
```yaml
mongodb_storage_dirperdb: true
mongodb_storage_engine: "wiredTiger"
mongodb_wiredtiger_cache_size: "512G"
mongodb_wiredtiger_directory_for_indexes: "/usr/share/mongo/indexes"
```

<details>
<summary>Ответ</summary>

```yaml
storage:
  dbPath: ./
  directoryPerDB: true
  engine: wiredTiger
  wiredTiger:
    engineConfig:
      cacheSizeGB: 512G
      directoryForIndexes: "/usr/share/mongo/indexes"
```
</details>

### Упражнение 2

**Вопрос:** Напишите Jinja шаблон, генерирующий следующий код.

**Ожидаемый результат:**
```
#------ Server 01 ------#
Space_name = ranger
Software_list = ["ntp", "nginx", "http"]

#------ Server 02 ------#
Space_name = ranger
Software_list = ["postgres", "mysql"]

#------ Server 03 ------#
Space_name = hunter
Software_list = ["webapp", "loader"]
Calls = {"name": "argl", "values": ["run_main", "run_schedule"]}
```

**Переменные:**
```yaml
servers:
  - sname: ranger
    software:
      - ntp
      - nginx
      - http
  - sname: ranger
    software:
      - postgres
      - mysql
  - sname: hunter
    software:
      - webapp
      - loader
    calls:
      name: argl
      values:
        - run_main
        - run_schedule
```
> **Подсказка:** Эта задача потребует объявления переменной для обсчета цифр. В версиях Ansible до 2.9 достаточно написать `{% set variable = 0 %}` и использовать в цикле. Однако с новых версий придется объявлять `Namespace`, следующего вида `{% set variable = namespace(value=0) %}` и обращаться по ключу `variable.value`, иначе инкременты внутри циклов не заработают из-за изменений в областях видимости. В данной задаче используется версия 2.9.

<details>
<summary>Ответ</summary>

```jinja
{% for server in servers %}
#------ Server {{ loop.index }} ------#
Space_name = {{ server.sname }}
Software_list = {{ server.software | to_json }}
{% if server.calls is defined %}
Calls = {{ server.calls | to_json }}
{% endif %}
{% endfor %}
```
</details>

### Упражнение 3

**Вопрос:** Каким будет результат выполнения следующего Jinja шаблона?

**Шаблон:**
```jinja
{% for key in agent.names %}
{{key}} = {{ agent.vals[loop.index0] }}
{% endfor %}

policy = {{ network_policy | upper }}
procedures = {{ agent.names | zip(agent.vals) | list | to_json }}
```

**Переменные:**
```yaml
network_policy: strict
agent:
  names:
    - host
    - port
    - group
    - gate
  vals:
    - agent.web.internal
    - 8081
    - net
    - disabled
```

<details>
<summary>Ответ</summary>

```
host = agent.web.internal
port = 8081
group = net
gate = disabled

policy = STRICT
procedures = [["host", "agent.web.internal"], ["port", 8081], ["group", "net"], ["gate", "disabled"]]
```
</details>
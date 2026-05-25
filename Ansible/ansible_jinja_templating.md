# Шаблонизация Jinja2 в Ansible

## Определения

**Jinja2** — шаблонизатор для языка программирования Python, используемый Ansible для динамического создания файлов. Он позволяет вставлять переменные, выполнять циклы и условные конструкции внутри текстовых файлов. Шаблоны обрабатываются модулем `ansible.builtin.template`, а файлы шаблонов обычно имеют расширение `.j2`.

## Основные концепции

### Переменные

Вывод значения переменной осуществляется с помощью двойных фигурных скобок: `{{ my_variable }}`. Доступ к элементам словаря: `{{ my_dict.key }}` или `{{ my_dict['key'] }}`.

Для обработки неопределенных переменных рекомендуется использовать фильтр `default`:

```jinja
Hello, {{ user | default("guest") }}
```

Определение локальной переменной непосредственно в шаблоне: `{% set my_variable = "value" %}`.

### Цикл `for`

Используется для итерации по элементам списка:

```jinja
{% for item in inventory %}
Сервер {{ loop.index }}: {{ item.name }} (IP-адрес (Internet Protocol): {{ item.ip }})
{% endfor %}
```

- `loop.index` — текущий индекс итерации (начинается с 1).
- `loop.index0` — индекс итерации (начинается с 0).

### Условия `if`

Позволяют включать или исключать блоки текста в зависимости от условий:

```jinja
{% if enable_ssl %}
server {
    listen 443 ssl; {# SSL (Secure Sockets Layer) #}
{% else %}
server {
    listen 80;
{% endif %}
}
```

Основные проверки:
- Проверка существования: `{% if my_var is defined %}`.
- Вхождение в список: `{% if 'db' in server_roles %}`.
- Комбинирование условий: операторы `and`, `or`, `not`.

### Фильтры

Фильтры позволяют преобразовывать значения переменных с помощью символа конвейера `|`.

**`default`** — установка значения по умолчанию:
```jinja
{{ first_name | default("there") }}
{# Если значение пустое или False, использовать default: #}
{{ first_name | default("there", true) }}
```

**`replace`** — замена подстроки в строке:
```jinja
{{ department | replace("Personnel", "HR") }}
```

Фильтры можно объединять в цепочки: `{{ my_var | filter1 | filter2 }}`.

## Практические сценарии

### Пример: Шаблон конфигурации Nginx

#### 1. Определение переменных в Ansible (например, в `group_vars/all.yml`)

```yaml
nginx_worker_processes: 4
nginx_http_port: 80
enable_nginx_status_page: true
allowed_status_ips:
  - 192.168.1.10
  - 10.0.0.5
```

#### 2. Шаблон `nginx.conf.j2`

```jinja
# /etc/nginx/nginx.conf

worker_processes {{ nginx_worker_processes | default(2) }};

events {
    worker_connections 1024;
}

http {
    server {
        listen {{ nginx_http_port }};
        server_name _;

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
        
        {# Условие для добавления опционального блока статуса #}
        {% if enable_nginx_status_page %}
        location /nginx_status {
            stub_status;
            allow 127.0.0.1;
            
            {# Цикл для генерации списка разрешенных IP-адресов #}
            {% for ip in allowed_status_ips %}
            allow {{ ip }};
            {% endfor %}
            
            deny all;
        }
        {% endif %}
    }
}
```

#### 3. Задача в плейбуке (Playbook)

Для применения шаблона используется модуль `ansible.builtin.template`.

```yaml
- name: Generate nginx configuration from template
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
    # Проверка синтаксиса перед применением
    validate: /usr/sbin/nginx -t -c %s
    # Создание резервной копии при изменении
    backup: yes
  notify: Restart nginx
```

## Дополнительная информация

### Лучшие практики

- **Расширение `.j2`**: Всегда используйте суффикс `.j2` для файлов шаблонов. Это позволяет четко отличить их от статических файлов конфигурации.
- **Кавычки в YAML (YAML Ain't Markup Language)**: Обязательно заключайте выражения Jinja2 в кавычки, если они являются началом значения в YAML-файле.
  - **Плохо:** `my_var: {{ some_value }}/path`
  - **Хорошо:** `my_var: "{{ some_value }}/path"`
- **Валидация**: Используйте параметр `validate` в модуле `template` для проверки корректности генерируемого конфига перед его сохранением на целевой хост.
- **Резервное копирование**: Включайте `backup: yes` для критически важных конфигурационных файлов, чтобы иметь возможность быстрого отката.
- **Минимизация логики**: Не перегружайте шаблоны сложной логикой. Если преобразования слишком объемные, лучше подготовить данные заранее в плейбуке с помощью модуля `ansible.builtin.set_fact`.

См. также:
- [Модули управления файлами](Modules/ansible_file_management_modules.md)
- [Управление потоком выполнения](PlaybookStructure/flow_control.md)
- [Структура ролей](Roles/structure.md)

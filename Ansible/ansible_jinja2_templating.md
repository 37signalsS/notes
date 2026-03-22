# Ansible Jinja2 Templating

## Определения

**Jinja2** — шаблонизатор для Python, используемый Ansible для динамического создания файлов. Позволяет вставлять переменные, выполнять циклы и условные конструкции. Шаблоны обрабатываются модулем `ansible.builtin.template`, файлы имеют расширение `.j2`.

## Основные концепции

### Переменные

Вывод значения: `{{ my_variable }}`. Доступ к элементам словаря: `{{ my_dict.key }}`.

Для неопределенных переменных используйте фильтр `default`:

```jinja
Hello, {{ user | default("guest") }}
```

Определение переменной в шаблоне: `{% set my_variable = "value" %}`.

### Цикл `for`

Итерация по элементам списка:

```jinja
{% for item in inventory %}
Сервер {{ loop.index }}: {{ item.name }} (IP: {{ item.ip }})
{% endfor %}
```

- `loop.index` — текущий индекс (с 1)
- `loop.index0` — индекс (с 0)

### Условия `if`

Вывод блоков в зависимости от условия:

```jinja
{% if enable_ssl %}
server {
    listen 443 ssl;
{% else %}
server {
    listen 80;
{% endif %}
}
```

- Проверка существования: `{% if my_var is defined %}`
- Вхождение в список: `{% if 'db' in server_roles %}`
- Комбинация: `and`, `or`

### Фильтры

Преобразование переменных через `|`:

**`default`** — значение по умолчанию:

```jinja
{{ first_name | default("there") }}
{{ first_name | default("there", true) }}
```

**`replace`** — замена подстроки:

```jinja
{{ department | replace("Personnel", "HR") }}
```

Фильтры объединяются: `{{ my_var | filter1 | filter2 }}`.

## Практические сценарии

### Пример: Шаблон конфигурации Nginx

#### 1. Переменные в Ansible (например, в `group_vars/all.yml`)

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
        
        {# Используем условие 'if' для добавления опционального блока #}
        {% if enable_nginx_status_page %}
        location /nginx_status {
            stub_status;
            allow 127.0.0.1;
            
            {# Используем цикл 'for' для генерации списка разрешенных IP #}
            {% for ip in allowed_status_ips %}
            allow {{ ip }};
            {% endfor %}
            
            deny all;
        }
        {% endif %}
    }
}
```

#### 3. Задача в плейбуке

```yaml
- name: Generate nginx configuration from template
  ansible.builtin.template:
    src: nginx.conf.j2  # Путь к файлу шаблона
    dest: /etc/nginx/nginx.conf # Путь для сгенерированного файла на целевом хосте
    owner: root
    group: root
    mode: '0644'
  notify: Restart nginx # Уведомляем обработчик для перезапуска сервиса
```

Эта задача возьмет шаблон `nginx.conf.j2`, подставит в него значения переменных `nginx_worker_processes`, `nginx_http_port` и т.д., и создаст на целевом хосте готовый файл `/etc/nginx/nginx.conf`.

## Дополнительная информация

### Лучшие практики

- **Используйте суффикс `.j2`**: Всегда называйте файлы шаблонов с расширением `.j2`, чтобы их было легко отличить от статичных файлов.
- **Кавычки для выражений**: В YAML-файлах Ansible заключайте Jinja2-выражения в кавычки, чтобы избежать ошибок парсинга.
  - **Плохо:** `my_var: {{ some_value }}/path`
  - **Хорошо:** `my_var: "{{ some_value }}/path"`
- **Не усложняйте шаблоны**: Избегайте слишком длинных и сложных цепочек фильтров или вложенной логики. Если логика становится сложной, лучше подготовить данные заранее в плейбуке (например, с помощью `set_fact`) или вынести логику в кастомный фильтр.
- **Используйте `default`**: Всегда используйте фильтр `default` для переменных, которые могут отсутствовать, чтобы сделать плейбуки более предсказуемыми и отказоустойчивыми.

См. также [официальную документацию Jinja2](https://jinja.palletsprojects.com/en/latest/templates/), [модули управления файлами](Modules/ansible_file_management_modules.md), [управление потоком](PlaybookStructure/flow_control.md).

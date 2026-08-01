# Паттерн "Utility Role" в Ansible

## Определения

**Паттерн "Utility Role" (Служебная роль)** — методология проектирования [ролей Ansible](../ansible_roles.md), при которой создается специализированная роль-библиотека. Она не предназначена для прямого назначения хостам в секции `roles:` плейбука. Её единственная цель — инкапсуляция и предоставление общих компонентов (задач, обработчиков, переменных, плагинов) для других ролей проекта.

**Общие компоненты (Shared Components)** — атомарные и переиспользуемые фрагменты кода, вынесенные в отдельную структуру для реализации принципа DRY (Don't Repeat Yourself) и обеспечения единообразия инфраструктуры.

---

## Основные концепции

### Преимущества и архитектурная роль

1.  **Библиотека функций:** Utility Role выступает в роли "стандартной библиотеки" проекта.
2.  **Изоляция сложности:** Сложная логика (например, вычисление сложных фактов или работа с API) скрыта внутри служебной роли.
3.  **Глобальные плагины:** Пользовательские фильтры и модули, размещенные в служебной роли, становятся доступными всему проекту при её подключении.

### Механизмы подключения и область видимости

Выбор метода подключения критически влияет на доступность данных:

*   **`ansible.builtin.import_role` (Статический):**
    *   Переменные из `defaults/` и `vars/` служебной роли становятся доступными для всего остального плейбука.
    *   Идеально для ролей-инициализаторов.
*   **`ansible.builtin.include_role` (Динамический):**
    *   По умолчанию переменные роли изолированы (Private scope).
    *   Для экспорта переменных во внешний контекст необходимо использовать **`public: true`**.
    *   Позволяет использовать циклы и условия при вызове служебных задач.

---

## Практические сценарии

### Сценарий 1: Централизованные обработчики (Shared Handlers)

Вместо дублирования `restart nginx` в пяти разных ролях, используйте `listen`.

**`roles/lib_common/handlers/main.yml`:**
```yaml
---
- name: global restart webserver
  ansible.builtin.service:
    name: "{{ web_service_name | default('nginx') }}"
    state: restarted
  listen: "restart_webserver"
```

**Подключение в прикладной роли (`roles/app/handlers/main.yml`):**
```yaml
---
- name: Import global handlers
  ansible.builtin.import_tasks:
    file: "../../lib_common/handlers/main.yml"
```
*В задачах прикладной роли:* `notify: "restart_webserver"`.

### Сценарий 2: Общие факты и "Library Interface"

Использование `meta/argument_specs.yml` (Ansible 2.11+) для строгого определения интерфейса служебной роли.

**`roles/util_facts/meta/argument_specs.yml`:**
```yaml
argument_specs:
  main:
    short_description: "Сбор корпоративных фактов"
    options:
      target_env:
        type: str
        choices: ['prod', 'stage', 'dev']
        required: true
```

**`roles/util_facts/tasks/main.yml`:**
```yaml
---
- name: Set global environment facts
  ansible.builtin.set_fact:
    is_production: "{{ target_env == 'prod' }}"
    app_registry: "reg.corp.example.com/{{ target_env }}"
```

### Сценарий 3: Общие плагины (Filters/Lookups)

Размещение кастомного Python-кода, который будет доступен всем ролям.

```text
roles/lib_utils/
└── filter_plugins/
    └── net_utils.py  # Содержит фильтр 'to_internal_ip'
```

При подключении `lib_utils` через `include_role` в начале плейбука, фильтр `my_var | to_internal_ip` будет работать во всех последующих задачах.

### Современная альтернатива: Ansible Collections

В крупных проектах Utility Roles эволюционируют в **Collections**. 
*   Вместо `include_tasks` из роли используется вызов задач по FQCN: `include_tasks: myorg.infra.shared_tasks`.
*   Служебные Python-скрипты переносятся в `plugins/` коллекции, что делает их доступными без явного импорта роли.

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Именование:** Используйте префиксы `lib_`, `util_` или `shared_` (например, `lib_system`), чтобы в списке ролей сразу видеть служебные компоненты.
2.  **Избегайте "God Role":** Не создавайте одну роль `common`, в которую сваливается всё. Разделяйте их по смыслу: `util_monitoring`, `util_auth`, `util_network`.
3.  **Пути к файлам:** При вызове `include_tasks` из другой роли используйте переменную `{{ playbook_dir }}`, чтобы избежать проблем с относительными путями:
    ```yaml
    - name: Load shared tasks
      ansible.builtin.include_tasks:
        file: "{{ playbook_dir }}/roles/lib_common/tasks/setup.yml"
    ```

### См. также

*   [Стратегии проектирования ролей](strategies.md) — выбор архитектуры (Layered vs Component).
*   [Структура роли](structure.md) — детали каталогов и `argument_specs`.
*   [Кроссплатформенность](../CrossPlatform/concepts.md) — использование Utility Role для разных ОС.
*   [Антипаттерны](../ansible_bad_practices.md) — почему "God Role" — это плохо.
*   [Продвинутые возможности плейбуков](../PlaybookStructure/advanced.md) — детали `import` vs `include`.

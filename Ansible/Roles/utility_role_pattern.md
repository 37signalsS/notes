# Паттерн "Utility Role" в Ansible

## Определения

**Паттерн "Utility Role" (Служебная роль)** — подход к проектированию [ролей Ansible](../ansible_roles.md), при котором создается роль-библиотека, не предназначенная для прямого назначения хостам в плейбуке. Её единственная цель — хранение и предоставление общих компонентов (задач, обработчиков, переменных) для других ролей проекта.

**Общие компоненты (Shared Components)** — повторяющиеся фрагменты кода (например, настройка репозиториев, создание пользователей, перезапуск стандартных сервисов), вынесенные в отдельную структуру для исключения дублирования (DRY — Don't Repeat Yourself).

---

## Основные концепции

### Зачем использовать Utility Role?

1.  **Централизация логики:** Изменение в одном месте (например, URL корпоративного репозитория) автоматически применяется ко всем ролям, использующим этот компонент.
2.  **Упрощение основных ролей:** Основные роли (Nginx, PostgreSQL) фокусируются на своей специфике, импортируя инфраструктурную обвязку из служебной роли.
3.  **Снижение вероятности ошибок:** Протестированный один раз "Utility"-компонент гарантированно работает во всех зависимых ролях.

### Механизмы подключения

Для использования компонентов Utility Role применяются следующие модули:
*   `ansible.builtin.import_tasks` / `ansible.builtin.import_role`: Статическое включение (на этапе парсинга).
*   `ansible.builtin.include_tasks` / `ansible.builtin.include_role`: Динамическое включение (во время выполнения).

Подробное сравнение методов включения приведено в [Продвинутых возможностях плейбуков](../PlaybookStructure/advanced.md).

---

## Практические сценарии

### Сценарий 1: Централизованные обработчики (Shared Handlers)

Вместо того чтобы в каждой роли описывать `restart nginx`, создайте общую роль `common`.

**`roles/common/handlers/main.yml`:**
```yaml
---
- name: restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
  listen: "restart webserver"  # Использование ключевого слова listen для группировки

- name: reload systemd
  ansible.builtin.systemd:
    daemon_reload: true
```

**Подключение в роли Nginx (`roles/nginx/handlers/main.yml`):**
```yaml
---
- name: Import common handlers
  ansible.builtin.import_tasks:
    file: "../../common/handlers/main.yml"
```
Теперь в задачах роли Nginx можно использовать `notify: "restart webserver"`.

### Сценарий 2: Общие инфраструктурные задачи

Настройка репозиториев или базовых пакетов, необходимых для большинства сервисов.

**`roles/common/tasks/setup_repos.yml`:**
```yaml
---
- name: Add corporate YUM repository
  ansible.builtin.yum_repository:
    name: corp-repo
    description: Corporate repository
    baseurl: "https://repo.example.com/yum/$releasever"
    gpgcheck: true
    enabled: true
```

**Использование в прикладной роли (`roles/myapp/tasks/main.yml`):**
```yaml
---
- name: Setup repositories before installation
  ansible.builtin.include_tasks:
    file: "../../common/tasks/setup_repos.yml"

- name: Install myapp
  ansible.builtin.package:
    name: myapp
    state: present
```

### Сценарий 3: Роль-инициализатор (Bootstrap Role)

Служебная роль, которая выполняется первой для установки глобальных фактов или подготовки окружения.

**`roles/bootstrap/tasks/main.yml`:**
```yaml
---
- name: Determine environment type
  ansible.builtin.set_fact:
    env_type: "{{ 'prod' if 'production' in group_names else 'dev' }}"
    cacheable: true
```

### Современный подход: Ansible Collections

В современных проектах вместо Utility Roles рекомендуется использовать **Ansible Collections**. Это позволяет упаковать роли, модули и плагины в единый неймспейс. Общие задачи в коллекции доступны по пути `my_namespace.my_collection.my_shared_tasks`.

---

## Дополнительная информация

### Рекомендации по именованию и путям

1.  **Избегайте циклической зависимости:** Utility Role не должна зависеть от ролей, которые её импортируют.
2.  **Пути к файлам:** При использовании `import_tasks` внутри ролей, пути разрешаются относительно текущего файла. Рекомендуется использовать относительные пути `../../` или полные пути через переменную `{{ playbook_dir }}/roles/...`.
3.  **Валидация параметров:** Используйте `meta/argument_specs.yml` (см. [Структуру роли](structure.md)) для описания ожидаемых переменных в служебных задачах.

### См. также

*   [Основы ролей](../ansible_roles.md) — базовые понятия.
*   [Структура роли](structure.md) — описание каталогов и meta-файлов.
*   [Кроссплатформенность](../CrossPlatform/concepts.md) — использование Utility Role для разных ОС.
*   [Антипаттерны](../ansible_bad_practices.md) — как не превратить Utility Role в "God Role".

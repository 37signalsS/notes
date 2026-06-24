# Ansible: Управление ходом выполнения плейбука

## Определения

**Управление ходом выполнения** — это механизмы Ansible, позволяющие контролировать, какие задачи выполняются, когда и при каких условиях. К ним относятся условные конструкции, циклы, обработчики и теги.

## Основные концепции

- **Условные конструкции (`when`)**: Позволяют выполнять задачу только при выполнении определенного условия.
- **Циклы (`loop`)**: Позволяют выполнять одну и ту же задачу несколько раз с разными данными.
- **Регистрация результатов (`register`)**: Сохраняет результат выполнения задачи в переменную для последующего использования.
- **Обработка ошибок**: Механизмы `block`, `rescue`, `always`, `ignore_errors` для управления ошибками.
- **Теги (Tags)**: Позволяют выборочно запускать или пропускать части плейбука.

## Условные конструкции (when)

Директива `when` позволяет выполнять задачу только при выполнении определенного условия.

- **Логическое "И" (AND):** Список условий.
- **Логическое "ИЛИ" (OR):**

```yaml
- name: "Перезагрузить сервис только если включено и были изменения"
  ansible.builtin.systemd:
    name: my_service
    state: reloaded
  when:
    - my_service_enabled
    - config_result is changed
```

## Циклы (loop)

Позволяют выполнять одну и ту же задачу несколько раз с разными данными. `loop` является современным стандартом, заменяя `with_items`.

```yaml
- name: Установка нескольких пакетов
  ansible.builtin.apt:
    name: "{{ item.name }}"
    state: "{{ item.state }}"
  loop:
    - { name: 'nginx', state: 'present' }
    - { name: 'htop', state: 'latest' }
```

## Регистрация результатов (register)

Сохраняет результат выполнения задачи в переменную. Часто используется с `when` для условного выполнения.

```yaml
- name: "Сгенерировать конфигурационный файл"
  ansible.builtin.template:
    src: whitelist.j2
    dest: /etc/myapp/whitelist.conf
  register: whitelist_config

- name: "Перезагрузить сервис, только если конфиг изменился"
  ansible.builtin.service:
    name: myapp
    state: reloaded
  when: whitelist_config is changed
```

## Обработка ошибок

- `ignore_errors: true`: Продолжить выполнение, даже если задача завершилась сбоем.
- `block, rescue, always`: Аналог `try...catch...finally` для обработки ошибок на уровне задач. Пример с rollback: [сценарий 8 в advanced.md](advanced.md#сценарий-8-block--rescue--always--rollback).
- `failed_when`: Переопределить условия, при которых задача считается проваленной.
- `changed_when: false`: Сделать команду идемпотентной в отчетах.

## Теги (Tags)

Теги позволяют выборочно запускать или пропускать части плейбука, что крайне полезно для отладки, ускорения выполнения и разделения сложных плейбуков на логические части. Теги можно применять к отдельным задачам, блокам, ролям и даже целым `include` или `import`.

#### Применение тегов

```yaml
tasks:
  - name: Install base packages
    ansible.builtin.apt:
      name: "{{ item }}"
    loop:
      - htop
      - git
    tags:
      - packages
      - base

  - name: Configure firewall
    community.general.ufw:
      rule: allow
      port: '80'
      proto: tcp
    tags:
      - firewall
      - security
```

#### Запуск с тегами

- **Выполнить только задачи с определенными тегами:**

    ```bash
    # Выполнить задачи с тегом 'packages' ИЛИ 'firewall'
    ansible-playbook my_playbook.yml --tags packages,firewall
    ```

- **Пропустить задачи с определенными тегами:**

    ```bash
    # Выполнить все, КРОМЕ задач с тегом 'security'
    ansible-playbook my_playbook.yml --skip-tags security
    ```

#### Специальные теги

Ansible имеет несколько встроенных тегов с особым поведением:

- `always`: Задача с этим тегом **всегда** будет выполняться, если только она не была явно пропущена с помощью `--skip-tags always`. Это полезно для критически важных задач (например, проверка конфигурации).

    ```yaml
    - name: "Always run this check"
      ansible.builtin.ping:
      tags:
        - always
    ```

- `never`: Задача с этим тегом **никогда** не будет выполняться по умолчанию. Ее можно запустить, только если явно указать тег с помощью `--tags never`. Это удобно для отладочных или опасных задач.

    ```yaml
    - name: "Debug task"
      ansible.builtin.debug:
        msg: "This is a debug message."
      tags:
        - never
    ```

- `tagged`: Выполняет только те задачи, у которых есть хотя бы один тег.

    ```bash
    ansible-playbook my_playbook.yml --tags tagged
    ```

- `untagged`: Выполняет только те задачи, у которых **нет ни одного** тега.

    ```bash
    ansible-playbook my_playbook.yml --tags untagged
    ```

- `all`: Выполняет все задачи (поведение по умолчанию).

## Дополнительная информация

Основы структуры плейбуков (обработчики и уведомления) описаны в [basics.md](basics.md). Продвинутые возможности плейбуков (делегирование, статическое и динамическое включение) — в [advanced.md](advanced.md). Переменные и их приоритеты — в [variables.md](variables.md).

Примеры использования `when` с `ansible_os_family` — в [CrossPlatform/concepts.md](../CrossPlatform/concepts.md). Обработка ошибок с `block/rescue` на практике — в [examples/example_postgresql_setup.md](../examples/example_postgresql_setup.md) и [examples/example_docker_management.md](../examples/example_docker_management.md). Использование `changed_when` и `failed_when` — в [Modules/ansible_command_execution_modules.md](../Modules/ansible_command_execution_modules.md).

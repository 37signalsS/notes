# Ansible: Управление ходом выполнения плейбука

## Условные конструкции (when)

Директива `when` позволяет выполнять задачу только при выполнении определенного условия.

* **Логическое "И" (AND):** Список условий.
* **Логическое "ИЛИ" (OR):**

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

* `ignore_errors: true`: Продолжить выполнение, даже если задача завершилась сбоем.
* `block, rescue, always`: Аналог `try...catch...finally` для обработки ошибок на уровне задач.
* `failed_when`: Переопределить условия, при которых задача считается проваленной.
* `changed_when: false`: Сделать команду идемпотентной в отчетах.

## Теги (Tags)

Теги позволяют выборочно запускать или пропускать части плейбука.

```yaml
tasks:
  - name: Install base packages
    ansible.builtin.apt:
      name: htop
    tags: [packages, base]

# Запустить только задачи с тегом 'packages'
ansible-playbook my_playbook.yml --tags packages
# Запустить все, КРОМЕ задач с тегом 'base'
ansible-playbook my_playbook.yml --skip-tags base
```

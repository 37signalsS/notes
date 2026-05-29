# Ansible: Модули выполнения команд

## Определения

**Модули выполнения команд** — это группа инструментов Ansible (`command`, `shell`, `raw`, `script`, `expect`), предназначенных для запуска произвольных команд и скриптов на управляемых хостах. В отличие от декларативных модулей (например, `apt` или `service`), они работают императивно и используются как «последнее средство», когда нет специализированного модуля для конкретной задачи.

## Основные концепции

### Сравнение модулей

| Модуль | Среда выполнения | Особенности |
| :--- | :--- | :--- |
| **`command`** | Напрямую (без shell) | Самый безопасный, не поддерживает конвейеры (`|`), переменные окружения и перенаправления. |
| **`shell`** | Через `/bin/sh` | Поддерживает все возможности оболочки, но уязвим для инъекций команд при использовании переменных. |
| **`raw`** | SSH напрямую | Не требует наличия Python на хосте. Используется для "bootstrapping" (установки Python). |
| **`script`** | Скрипт с контрольного узла | Копирует скрипт с локальной машины на хост и выполняет его (не требует ручного переноса). |
| **`expect`** | Через `pexpect` | Для автоматизации интерактивных команд, запрашивающих ввод (пароли, подтверждения). |

### Идемпотентность и статус `changed`

Эти модули **не являются идемпотентными по умолчанию**. Ansible всегда помечает задачу как `changed`, если не указано иное.

- **`creates`**: Задача выполняется, только если указанный файл **отсутствует**.
- **`removes`**: Задача выполняется, только если указанный файл **присутствует**.
- **`changed_when`**: Позволяет вручную определить, когда команда действительно внесла изменения (например, на основе вывода или кода возврата).

## Практические сценарии

### Модуль `ansible.builtin.command` (Стандартный запуск)

Используется для большинства простых задач.

```yaml
- name: Проверка версии утилиты
  ansible.builtin.command:
    cmd: /usr/bin/custom-tool --version
  register: tool_version
  changed_when: false # Чтение версии не изменяет систему
```

### Модуль `ansible.builtin.shell` (Конвейеры и переменные)

Используется только когда нужны возможности оболочки.

```yaml
- name: Очистка старых логов через конвейер
  ansible.builtin.shell:
    cmd: ls -t /var/log/app/*.log | tail -n +5 | xargs rm -f
  when: cleanup_enabled | bool
```

### Модуль `ansible.builtin.raw` (Установка Python)

Единственный модуль, работающий без Python на целевом хосте.

```yaml
- name: Установка Python3 на "голую" систему
  ansible.builtin.raw: apt-get update && apt-get install -y python3
  become: true
  gather_facts: false # Факты нельзя собрать без Python
```

### Модуль `ansible.builtin.script` (Локальные скрипты)

Позволяет хранить сложные скрипты на контрольном узле.

```yaml
- name: Запуск сложной диагностики
  ansible.builtin.script:
    cmd: scripts/analyze_system.sh --full-report
    creates: /var/log/last_analysis.json
```

### Модуль `ansible.builtin.expect` (Интерактивный ввод)

Требует наличия библиотеки `pexpect` на хосте.

```yaml
- name: Обновление пароля БД (интерактивно)
  ansible.builtin.expect:
    command: passwd dbuser
    responses:
      (?i)password: "my-safe-password"
  no_log: true # Скрытие пароля из логов
```

## Дополнительная информация

- **Приоритет выбора**: Всегда ищите специализированный модуль (например, `lineinfile` вместо `sed` через `shell`). См. [Обзор модулей Ansible](ansible_modules_overview.md).
- **Безопасность**: При использовании `shell` с переменными применяйте фильтр `quote` для предотвращения инъекций: `cmd: "ls {{ dir_name | quote }}"`.
- **Антипаттерны**: Подробнее о том, почему не стоит злоупотреблять `shell`, в [Антипаттерны Ansible](../ansible_bad_practices.md).
- **Официальная документация**: [command](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/command_module.html), [shell](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/shell_module.html), [raw](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/raw_module.html).

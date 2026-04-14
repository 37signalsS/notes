# Ansible: Модули для управления пользователями и безопасностью

## Определения

**Модули управления пользователями и безопасностью** — это инструменты Ansible для создания, изменения и удаления учетных записей пользователей, генерации паролей и управления доступом к системе.

## Основные концепции

- **`user`**: Управление учетными записями пользователей (создание, удаление, настройка параметров, управление группами).
- **`password`**: Генерация безопасных паролей с поддержкой различных алгоритмов хеширования.
- **Идемпотентность**: Оба модуля идемпотентны — повторный запуск не приведет к изменениям, если система уже в нужном состоянии.
- **Безопасность**: При работе с паролями используйте хеши и избегайте хранения в открытом виде. Для задач с чувствительными данными добавляйте `no_log: true` — подробности в [Лучшие практики Vault](../Vault/best_practices.md#сценарий-1-предотвращение-утечек-в-логах-no_log-true).

## Практические сценарии

### Модуль `ansible.builtin.password`

**Назначение**: Генерация паролей для учетных записей пользователей, баз данных, а также для создания ключей.

- **Идемпотентность**: Модуль идемпотентен. Если пароль уже был сгенерирован и сохранен (например, в файле, указанном в `path`), он не будет генерироваться повторно при следующих запусках, если это не будет принудительно указано.

```yaml
- name: Generate a random password for a database user
  ansible.builtin.password:
    length: 20
    chars: ascii_letters,digits,punctuation
    # path: /path/to/vaulted_password_file # Укажите путь к файлу, который будет зашифрован Vault
    # Чтобы сгенерировать хеш пароля (для хранения в БД, например):
    # algorithm: sha512crypt # Алгоритм хеширования (например, 'sha512crypt', 'bcrypt')
    # Эти параметры (`path`, `algorithm`) являются взаимоисключающими и необязательными,
    # их использование зависит от способа хранения и применения пароля.
  register: db_password_result # Результат генерации пароля будет доступен в этой переменной

- name: Create database user with generated password
  community.mysql.mysql_user:
    name: my_app_user
    password: "{{ db_password_result.password }}"
    host: localhost
    priv: '*.*:ALL'
    state: present
  no_log: true # Важно скрывать пароли в логах!
```

### Модуль `ansible.builtin.user`

**Назначение**: Создание, изменение, удаление учетных записей пользователей. Управление группами пользователей.

- **Идемпотентность**: Модуль идемпотентен. Он создаст пользователя, только если его нет, и изменит параметры, только если они отличаются от заданных.

**Пример 1: Создание нового пользователя**

```yaml
- name: Create a new user 'peter_parker'
  ansible.builtin.user:
    name: peter_parker
    comment: "Peter Parker, Web Developer"
    shell: /bin/bash
    home: /home/peter_parker
    state: present
```

**Ad-hoc команда для создания пользователя:**

```bash
ansible <hostname> -m user -a "name=ansible_user shell=/bin/bash state=present" --become
```

**Пример 2: Добавление пользователя в группу sudo**

Для добавления пользователя в группу `sudo` (или `wheel` в RHEL-подобных системах) используйте параметр `groups` и `append: yes`.

```yaml
- name: Add 'peter_parker' to the sudo group
  ansible.builtin.user:
    name: peter_parker
    groups: sudo
    append: yes
    state: present
```

**Пример 3: Установка пароля для пользователя**

Для установки пароля используется параметр `password`. **Важно**: Пароль должен быть в виде хеша. Ansible не принимает пароли в открытом виде. Вы можете сгенерировать хеш пароля с помощью утилиты `mkpasswd` (в Linux) или Python.

```bash
# Пример генерации хеша пароля (для Linux, нужен пакет `whois` или `passwd`)
# python -c 'import crypt; print(crypt.crypt("MySecretPassword", crypt.METHOD_SHA512))'
```

```yaml
- name: Set password for 'peter_parker'
  ansible.builtin.user:
    name: peter_parker
    password: "$6$rounds=656000$q1w2e3r4t5y6u7i8$aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789./ABCDEFGHIJKLMNOPQRSTUVW" # Замените на сгенерированный хеш
    update_password: always # Всегда обновлять пароль, если хеш изменился
    state: present
  no_log: true # Скрывать пароль в логах
```

> **Лучшая практика**: Всегда используйте [Ansible Vault](../Vault/basics.md) для хранения хешей паролей и других чувствительных данных.

## Дополнительная информация

Официальная документация: [user](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/user_module.html), [password](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/password_module.html). Шифрование чувствительных данных — в [Ansible Vault](../Vault/basics.md).

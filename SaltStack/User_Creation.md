# Управление пользователями и группами в SaltStack

## Определения

- **`user.present`**: Функция состояния (state function), обеспечивающая декларативное управление пользователями. Гарантирует наличие пользователя с заданными атрибутами.
- **`user.absent`**: Гарантирует отсутствие пользователя в системе. Поддерживает `purge` (удаление домашнего каталога и почтового ящика) и `force` (удаление даже вошедшего в систему пользователя).
- **`group.present`**: Управляет созданием, параметрами и членством системных групп (`addusers`, `delusers`, `members`).
- **`group.absent`**: Гарантирует отсутствие группы в системе.
- **`ssh_auth.present`**: Управляет авторизованными SSH-ключами для конкретного пользователя.
- **`ssh_auth.absent`**: Удаляет SSH-ключ из файла `authorized_keys`.
- **`ssh_auth.manage`**: Декларативное приведение набора SSH-ключей пользователя к заданному списку — удаляет ключи, отсутствующие в конфигурации (доступно с версии 3000).
- **Массовое управление пользователями**: Отдельного state `user.manage` не существует — массовое создание учётных записей реализуется шаблонизацией SLS-файлов (Jinja) поверх структуры данных Pillar.

---

## Основные концепции

SaltStack реализует модель идемпотентного управления пользователями:
1.  **Создание**: Если пользователя нет, он будет создан с указанными параметрами.
2.  **Сверка (Reconciliation)**: Если пользователь существует, Salt проверит его атрибуты (UID, GID, домашний каталог, оболочка, GECOS-данные).
3.  **Обновление**: При обнаружении расхождений Salt применит изменения (например, сменит оболочку или добавит в группы).

**Взаимосвязь компонентов:**
Обычно создание пользователя сопровождается созданием его основной группы (`group.present`) и добавлением SSH-ключей (`ssh_auth.present`). Для обеспечения безопасности пароли никогда не хранятся в SLS-файлах в открытом виде — для этого используется [Pillar и секреты](Security_Approaches.md).

### Управление группами и членством

`group.present` может не только создать группу, но и управлять её членством. Важно различать два режима:
- `addusers` / `delusers` — аддитивные операции: добавить перечисленных пользователей в группу или исключить их из неё.
- `members` — заменить весь состав группы заданным списком (несовместим с `addusers`/`delusers`).

Дополнительно параметр `remove_groups` в `user.present` (по умолчанию `True`) удаляет пользователя из групп, не указанных в списке `groups`; значение `False` оставляет текущее членство без изменений.

### Пароли и политика истечения

- `password` принимает только **хэш** пароля (Linux, FreeBSD, NetBSD, OpenBSD, Solaris); для Windows — открытый текст.
- Атрибуты `date`, `mindays`, `maxdays`, `inactdays`, `warndays`, `expire` реализуют политику истечения паролей на Linux (аналог утилиты `chage`).
- `password_lock` (с версии 3006) блокирует (`True`) или разблокирует (`False`) пароль учётной записи; на Windows разблокирует учётную запись.
- `empty_password: True` включает вход без пароля (например, для служебных учётных записей).
- `hash_password: True` позволяет передать открытый пароль, который Salt зашифрует сам.

### SSH-ключи

- `ssh_auth.present` — добавить ключ (параметры `enc`, `options`, `comment`, `config` позволяют настроить тип ключа, опции и нестандартный путь к `authorized_keys`).
- `ssh_auth.absent` — удалить ключ.
- `ssh_auth.manage` (с версии 3000) — привести `authorized_keys` к заданному набору, удалив лишние ключи (удобно при ротации ключей).

### Массовое управление пользователями

Единая структура данных в Pillar и цикл Jinja в SLS-файле позволяют декларативно описать произвольное число учётных записей без дублирования кода — см. практический сценарий 3.

---

## Практические сценарии

### 1. Комплексное создание пользователя (User + Group + SSH)

Этот пример демонстрирует создание пользователя `deployer` с выделенной группой и SSH-ключом.

```yaml
# /srv/salt/users/deployer.sls

deployer_group:
  group.present:
    - name: deployer
    - system: True

deployer_user:
  user.present:
    - name: deployer
    - fullname: Deploy Automation User
    - shell: /bin/bash
    - home: /home/deployer
    - createhome: True
    - gid: deployer
    - groups:
      - docker
    - require:
      - group: deployer_group

deployer_ssh_key:
  ssh_auth.present:
    - user: deployer
    - name: ssh-ed25519 AAAAC3Nza... user@workstation
    - require:
      - user: deployer_user
```

> **Примечание:** параметр `gid_from_name` удалён из `user.present` (3001, окончательно — в 3004). Вместо него используется `usergroup: True` (автоматическое создание одноимённой группы) либо явный `gid` — как в примере выше, где группа создана заранее через `group.present`.

### 2. Использование Pillar для управления паролями

Безопасный подход с использованием зашифрованных данных или внешних хранилищ (Vault).

```yaml
# /srv/pillar/users.sls
users:
  admin:
    password: $6$rounds=656000$salt$hash... # Хэш пароля
```

```yaml
# /srv/salt/users/admins.sls
admin_user:
  user.present:
    - name: admin
    - password: {{ salt['pillar.get']('users:admin:password') }}
```

**Применение:**
```bash
salt '*' state.apply users.admins
```

### 3. Массовое создание пользователей (Pillar + Jinja)

Единая структура данных в Pillar и цикл Jinja в SLS-файле. Пользователи описываются декларативно, а `user.present` и `ssh_auth.present` применяются для каждого из них:

```yaml
# /srv/pillar/users.sls
users:
  alice:
    fullname: Alice Smith
    groups:
      - wheel
      - docker
    ssh_key: ssh-ed25519 AAAA... alice@laptop
  bob:
    fullname: Bob Johnson
    groups:
      - wheel
    ssh_key: ssh-ed25519 BBBB... bob@desktop
```

```jinja
# /srv/salt/users/init.sls
{% for name, attrs in salt['pillar.get']('users', {}).items() %}
{{ name }}:
  user.present:
    - fullname: {{ attrs.fullname }}
    - groups: {{ attrs.groups }}
  ssh_auth.present:
    - user: {{ name }}
    - name: {{ attrs.ssh_key }}
    - require:
      - user: {{ name }}
{% endfor %}
```

**Применение:**
```bash
salt '*' state.apply users
```

### 4. Управление членством в группах

Привести состав группы к заданному набору (режим `members` — полная замена состава):

```yaml
# /srv/salt/groups/ops.sls
ops_members:
  group.present:
    - name: ops
    - members:
      - alice
      - bob
      - carol
```

Аддитивное добавление/исключение конкретных пользователей (`addusers`/`delusers`, несовместимы с `members`):

```yaml
add_bob_to_deployers:
  group.present:
    - name: deployers
    - addusers:
      - bob

remove_tmpuser_from_ops:
  group.present:
    - name: ops
    - delusers:
      - tmpuser
```

### 5. Политика паролей и блокировка учётной записи

Задание параметров истечения пароля (атрибуты shadow, Linux) и блокировка служебной учётной записи:

```yaml
# /srv/salt/users/policy.sls
enforce_password_policy:
  user.present:
    - name: app-user
    - mindays: 7
    - maxdays: 90
    - warndays: 14
    - expire: 20818    # дата истечения аккаунта, дни с 01.01.1970 (2026-12-31)

lock_tmp_account:
  user.present:
    - name: temp-account
    - password_lock: True   # с версии 3006
```

### 6. Аудит пользователей и групп

Проверка фактического состояния учётных записей с помощью модулей выполнения:

```bash
salt '*' user.info alice          # все атрибуты учётной записи
salt '*' user.list_users          # список всех пользователей системы
salt '*' user.list_groups alice   # группы пользователя
salt '*' group.info ops           # информация о группе и её членах
salt '*' shadow.info alice        # политика паролей и даты (Linux)
```

---

## Дополнительная информация

### Расширенные параметры `user.present`

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `uid` | Числовой ID пользователя | `uid: 2000` |
| `gid` | Основной GID или имя группы | `gid: 2000` / `gid: deployer` |
| `usergroup` | Автоматически создать группу с именем пользователя (GNU/Linux, с 3001) | `usergroup: True` |
| `groups` | Список дополнительных групп; отсутствующая группа — ошибка состояния | `groups: [sudo, wheel]` |
| `optional_groups` | Список групп; несуществующие молча игнорируются (с 3001) | `optional_groups: [docker]` |
| `remove_groups` | Удалять из групп, не указанных в списке (по умолчанию `True`) | `remove_groups: False` |
| `fullname` | Полное имя (GECOS) | `fullname: Ivan Ivanov` |
| `roomnumber` | Номер комнаты (GECOS; не поддерживается в macOS) | `roomnumber: 404` |
| `workphone` | Рабочий телефон (GECOS; не поддерживается в macOS) | `workphone: 555-0101` |
| `homephone` | Домашний телефон (GECOS; не поддерживается в macOS) | `homephone: 555-0102` |
| `other` | Дополнительный GECOS-атрибут (не поддерживается в macOS) | `other: 777-777-7777` |
| `createhome` | Создавать домашний каталог при отсутствии (не поддерживается в Windows/macOS; родительский каталог должен существовать) | `createhome: True` |
| `persist_home` | Перенести содержимое домашнего каталога при смене пути | `persist_home: True` |
| `system` | Создать системного пользователя (UID из системного диапазона) | `system: True` |
| `unique` | Требовать уникальный UID (по умолчанию `True`) | `unique: False` |
| `allow_uid_change` | Разрешить изменение UID существующего пользователя | `allow_uid_change: True` |
| `allow_gid_change` | Разрешить изменение основного GID существующего пользователя | `allow_gid_change: True` |
| `password` | Хэш пароля (Linux/BSD/Solaris) или открытый текст (Windows) | `password: $6$rounds=656000$...` |
| `hash_password` | Зашифровать переданный открытый пароль | `hash_password: True` |
| `enforce_password` | Менять пароль, если текущий хэш отличается (по умолчанию `True`) | `enforce_password: False` |
| `empty_password` | Разрешить вход без пароля | `empty_password: True` |
| `password_lock` | Заблокировать/разблокировать пароль; на Windows — учётную запись (с 3006) | `password_lock: True` |
| `nologinit` | Не добавлять пользователя в базы `lastlog`/`faillog` | `nologinit: True` |
| `local` | Локальное создание учётной записи в обход глобальных каталогов (с 3007, только при наличии `luseradd`) | `local: True` |

**Атрибуты политики паролей (shadow, только Linux):** `date`, `mindays`, `maxdays`, `inactdays`, `warndays`, `expire` — задаются целыми числами (`date` и `expire` — в днях с 01.01.1970).

**Параметры Windows:** `win_homedrive` (буква диска, например `'U:'`), `win_profile`, `win_logonscript`, `win_description`.

### Специфика операционных систем

- **Linux**: Использует стандартные утилиты `useradd`/`usermod`. Пароли должны передаваться в виде хэша (совместимого с `crypt`); поддерживаются атрибуты политики shadow (`mindays`, `maxdays`, `expire` и др.). Основы хэширования и политики паролей: [хэширование паролей](../../Linux/SystemAdministration/Users/password_hashing.md) и [политика паролей (chage)](../../Linux/SystemAdministration/Users/password_policy_chage.md).
- **macOS**: Использует `dscl`. `createhome` и `persist_home` не поддерживаются; GECOS-поля `roomnumber`, `workphone`, `homephone`, `other` не применяются; основная группа по умолчанию — `staff`.
- **Windows**: Управляет локальными пользователями. `password` передаётся в открытом виде, используются параметры `win_*`; `createhome` и `shell` не поддерживаются; `password_lock: False` разблокирует учётную запись.

### Версии Salt

Описание параметров актуально для **Salt 3008**. Версионные параметры: `optional_groups` и `usergroup` (3001), `password_lock` (3006), `local` (3007). В более ранних версиях указанные параметры недоступны и приведут к ошибке рендеринга состояния.

### Удаление ресурсов

```yaml
cleanup_user:
  user.absent:
    - name: tempuser
    - purge: True # Удалить домашний каталог и почтовый ящик
    - force: True # Удалить, даже если пользователь в системе

cleanup_group:
  group.absent:
    - name: oldgroup
```

**Связанные темы:**
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md) — автоматизация применения.
- [Подходы к безопасности](Security_Approaches.md) — шифрование паролей и интеграция с Vault.
- [Официальная документация user.present](https://docs.saltproject.io/en/latest/ref/states/all/salt.states.user.html)

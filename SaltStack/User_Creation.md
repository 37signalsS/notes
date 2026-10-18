# Управление пользователями и группами в SaltStack

**Актуально для:** Salt 3008.x

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

**Жизненный цикл состояния пользователя:**
- **Компиляция**: Master читает SLS-файл, рендерит Jinja-шаблоны и получает финальные параметры.
- **Таргетинг**: Master определяет, на какие миньоны применить состояние (по ID, Grains, Pillar, compound-матчеры).
- **Публикация**: Master отправляет задание в шину ZeroMQ (порт 4505), миньоны получают его и передают в Execution Module.
- **Исполнение**: Execution Module вызывает утилиту ОС (`useradd`, `usermod`, `userdel` на Linux; `dscl` на macOS; `net user` на Windows).
- **Сверка**: Модуль проверяет текущее состояние атрибутов и вычисляет необходимые изменения.
- **Применение**: Изменения применяются, результаты возвращаются мастеру.
- **Возврат**: Результат записывается в Job Cache (master_job_cache) и/или во внешний returner.

**Параметры, требующие пояснений:**
- **`local`** (с версии 3007): Создаёт локальную учётную запись в обход глобальных каталогов (LDAP, NIS, AD). Требует наличия утилиты `luseradd` (не на всех дистрибутивах). Полезен для служебных аккаунтов на конкретном узле.
- **`enforce_password`** (по умолчанию `True`): Если текущий хэш пароля отличается от указанного, Salt принудительно меняет пароль. Установите `False`, чтобы изменить пароль только при его полном отсутствии.
- **`allow_uid_change` / `allow_gid_change`**: Разрешают изменение UID/GID существующего пользователя. По умолчанию `False` — Salt игнорирует расхождения в UID/GID для безопасности (изменение UID может привести к сбою владения файлами).
- **`nologinit`**: Не добавляет пользователя в базы `lastlog` и `faillog`. Полезно для системных учётных записей, на которых никогда не будет выполняться вход.

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

### 7. Соответствие стандартам безопасности (Compliance)

Автоматизация проверок соответствия CIS Benchmark, PCI-DSS, HIPAA через декларативные состояния Salt. Salt не только проверяет дрифт, но и может исправлять несоответствия в рамках одного запуска.

**Проверка:**
```yaml
# /srv/salt/compliance/users.sls
check_empty_passwords:
  user.present:
    - name: test
    - password: '!'
    - test: True  # только проверка, не создание

check_duplicate_uids:
  cmd.run:
    - name: "awk -F: '(\$3 == 0) {print \$1}' /etc/passwd | grep -v '^root$'"
    - unless: "awk -F: '(\$3 == 0) {print \$1}' /etc/passwd | grep -v '^root$' | wc -l | xargs -I {} test {} -eq 0"

check_weak_password_hashes:
  cmd.run:
    - name: "grep -E '^\\$1\\b' /etc/shadow || true"
    - unless: "grep -E '^\\$1\\b' /etc/shadow | wc -l | xargs -I {} test {} -eq 0"
    - require:
      - check_empty_passwords
```

**Исправление (режим enforce):**
```yaml
# /srv/salt/compliance/users_enforce.sls
enforce_password_hashing:
  user.present:
    - name: app-user
    - password: $6$rounds=656000$new$hash  # yescrypt/yescrypt
    - enforce_password: True

enforce_password_aging:
  user.present:
    - name: app-user
    - mindays: 1
    - maxdays: 90
    - warndays: 14
    - inactdays: 14
```

**Возврат результатов в SIEM:**
```yaml
# /etc/salt/master.d/returner.conf
returner: sqlite  # или PostgreSQL, Elasticsearch
```

```bash
salt '*' state.apply compliance.users saltenv=prod  # проверка
salt '*' state.apply compliance.users_enforce saltenv=prod  # исправление
```

**Валидация:**
```bash
salt '*' state.apply compliance.users saltenv=prod --return sqlite
# → в returner записаны результаты проверок
salt-run jobs.lookup_jid <jid>  # просмотр результатов задания
```

### 8. Break-glass и временные учётные записи

Break-glass-аккаунты — аварийные учётные записи с ограниченным сроком жизни и повышенным контролем. Временные аккаунты — для подрядчиков или краткосрочных задач.

**Break-glass-аккаунт:**
```yaml
# /srv/salt/users/breakglass.sls
breakglass_user:
  user.present:
    - name: breakglass
    - fullname: "Break-glass Emergency Account"
    - shell: /bin/bash
    - groups:
      - wheel
    - expire: 20818  # 2026-12-31 (дни с 01.01.1970)
    - password_lock: True  # заблокирован до использования
    - password: $6$rounds=656000$salt$hash  # сложный пароль хранится в Vault
    - require:
      - group: wheel_group
```

**Использование break-glass:**
```bash
# В экстренной ситуации администратор разблокирует аккаунт
salt 'master' state.apply users.breakglass_unlock saltenv=prod
```

```yaml
# /srv/salt/users/breakglass_unlock.sls
breakglass_user:
  user.present:
    - name: breakglass
    - password_lock: False
    - enforce_password: False
```

**Временный аккаунт подрядчика (с автоматическим удалением):**
```yaml
# /srv/salt/users/contractor.sls
contractor_user:
  user.present:
    - name: contractor_jdoe
    - fullname: "John Doe (Contractor)"
    - shell: /bin/bash
    - groups:
      - developers
    - expire: 18993  # 2026-03-01 (дни с 01.01.1970)
    - password_lock: False
    - password: $6$rounds=656000$salt$hash
    - require:
      - group: developers_group
```

**Автоматическая очистка по истечении срока:**
```bash
# Запускать по cron или через Salt Schedule
salt '*' state.apply users.cleanup_expired saltenv=prod
```

```yaml
# /srv/salt/users/cleanup_expired.sls
cleanup_expired_accounts:
  user.absent:
    - names:
      - contractor_jdoe
      - temp_intern
    - purge: True
    - require:
      - cmd: check_expired_accounts

check_expired_accounts:
  cmd.run:
    - name: "salt '*' user.list_users | grep -E '^(contractor_|temp_)' | wc -l"
    - unless: "salt '*' user.list_users | grep -E '^(contractor_|temp_)' | wc -l | xargs -I {} test {} -eq 0"
```

### 9. Интеграция с HashiCorp Vault для хранения паролей

Загрузка хэшей паролей из Vault через `ext_pillar` или SDB позволяет хранить секреты централизованно без дублирования в Git.

**Настройка Vault на мастере:**
```yaml
# /etc/salt/master.d/vault.conf
vault:
  server:
    url: https://vault.example.com:8200
  auth:
    method: token
    token: <master-token>
  policies:
    assign:
      - saltstack/minions
```

**Загрузка паролей в Pillar:**
```yaml
# /etc/salt/master.d/ext_pillar.conf
ext_pillar:
  - vault:
      url: https://vault.example.com:8200
      token: <master-token>
      path: secret/salt/users
```

```bash
# В Vault создаём секрет
vault kv put secret/salt/users admin password='$6$rounds=656000$salt$hash...'
```

**Использование в состоянии:**
```yaml
# /srv/salt/users/vault_user.sls
admin_user:
  user.present:
    - name: admin
    - password: {{ salt['pillar.get']('users:admin:password') }}
    - fullname: "Administrator"
    - shell: /bin/bash
    - groups:
      - sudo
```

**Динамическое получение пароля через SDB:**
```yaml
# /etc/salt/master.d/sdb.conf
myvault:
  driver: vault
  url: https://vault.example.com:8200
  token: <master-token>
  path: secret/salt/users
```

```yaml
# /srv/salt/users/sdb_user.sls
app_user:
  user.present:
    - name: app
    - password: {{ salt['sdb.get']('sdb://myvault/users/app/password') }}
    - shell: /bin/bash
    - createhome: True
```

### 10. Аудит изменений пользователей через Returner

Отслеживание изменений учётных записей во времени для комплаенса и расследований. Returner отправляет результаты выполнения состояний в PostgreSQL, Elasticsearch или SIEM.

**Настройка PostgreSQL Returner:**
```yaml
# /etc/salt/master.d/returner.conf
postgres:
  host: localhost
  user: salt
  passwd: <password>
  db: salt
  port: 5432
```

```sql
-- Создание таблицы для результатов user.present
CREATE TABLE salt_returns (
  jid varchar(255),
  fun varchar(255),
  id varchar(255),
  return text,
  success bool
);
```

**Просмотр истории изменений пользователя:**
```bash
salt-run jobs.lookup_jid <jid>  # результаты конкретного задания
salt '*' state.apply users.admins saltenv=prod  # применение
salt-run jobs.list_jobs  # список всех заданий
```

**Поиск изменений конкретного пользователя:**
```bash
salt-run jobs.list_jobs search='*'  # все задания
salt-run jobs.list_jobs search='salt/*'  # только Salt задания
salt '*' state.apply users.admins --return postgres  # отправка в PostgreSQL
```

### 11. Управление пользователями через Salt-API

Выполнение операций создания/удаления пользователей через REST-интерфейс для интеграции с CI/CD-пайплайнами или порталами самообслуживания.

**Получение токена eAuth:**
```bash
curl -sSk https://salt-master:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"devops","password":"***","eauth":"pam"}'
# → {"return": [{"token": "eyJhbGciOi...", "start": 1729286400.0, "expire": 1729300800.0, "user": "devops"}]}
```

**Создание пользователя:**
```bash
TOKEN=$(curl -sSk https://salt-master:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"devops","password":"***","eauth":"pam"}' | jq -r '.return[0].token')

curl -sSk https://salt-master:8000/run \
  -H "X-Auth-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client": "local",
    "tgt": "web-01",
    "fun": "state.apply",
    "arg": ["users.deployer"],
    "kwarg": {"saltenv": "prod"}
  }'
```

**Удаление пользователя:**
```bash
curl -sSk https://salt-master:8000/run \
  -H "X-Auth-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client": "local",
    "tgt": "web-01",
    "fun": "state.apply",
    "arg": ["users.cleanup_tmp"],
    "kwarg": {"saltenv": "prod"}
  }'
```

**Проверка результата:**
```bash
# Получение статуса задания по JID
curl -sSk https://salt-master:8000/jobs/<jid> \
  -H "X-Auth-Token: $TOKEN"
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

## Troubleshooting

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `User already exists` с неверными атрибутами | Существующий пользователь имеет отличные UID/GID/оболочку | Установите `allow_uid_change: True` / `allow_gid_change: True` или приведите параметры в соответствие с существующим пользователем |
| `Group not found` при добавлении в `groups` | Группа не существует на целевом узле | Создайте группу через `group.present` или используйте `optional_groups` (3001+) |
| `Permission denied` при создании домашнего каталога | Родительский каталог не существует или права недостаточные | Создайте родительский каталог заранее или установите `createhome: False` и создавайте каталоги через `file.directory` |
| `SSH key not applied` | Неправильные права на `.ssh` или `authorized_keys` | Убедитесь, что права на домашний каталог `755`, на `.ssh` — `700`, на `authorized_keys` — `600` |
| `Password not changed` | `enforce_password: False` или хэш пароля совпадает | Установите `enforce_password: True` или измените значение `password` |
| `State не идемпотентен` | Изменение параметров во время выполнения состояния | Выполняйте состояния в CI/CD-пайплайнах с изолированными окружениями |
| `Salt-SSH: connection refused` | SSH-доступ не настроен или порт закрыт | Проверьте `roster`-файл, доступность порта 22, права доступа ключей |
| `Pillar не подгружается` | Ошибка синтаксиса в SLS или отсутствие секрета в Vault | Выполните `salt '*' saltutil.refresh_pillar` и проверьте логи мастера |

**Диагностические команды:**
```bash
salt '*' state.apply users.deployer test=True  # Dry-run: показать изменения без применения
salt '*' state.apply users.deployer saltenv=prod  # Применение с явным окружением
salt '*' state.apply users.deployer pillar='{"users": {...}}'  # Переопределение Pillar
salt-run state.event  # Наблюдение за событиями шины при применении
salt-run jobs.lookup_jid <jid>  # Просмотр результатов задания
```

## Ограничения и edge cases

1. **Дубликаты UID**: Если пользователь с UID уже существует, `unique: False` позволяет создать пользователя с тем же UID. Используйте с осторожностью — это нарушает целостность владения файлами.
2. **Домашний каталог на NFS**: Создание пользователя через NFS может завершиться ошибкой из-за прав root squash. Используйте `createhome: False` и создавайте каталоги через `file.directory` с правильными правами.
3. **Одновременное изменение пользователя**: Salt идемпотентен, но если несколько пайплайнов изменяют одного пользователя параллельно, возможна гонка. Используйте `state.apply` с явным `saltenv` и изолируйте изменения.
4. **Пользователи с истёкшим паролем**: `expire` блокирует вход, но не удаляет пользователя. Для автоматической очистки используйте `user.absent` с условием `if shadow.info <user>.expire < now()`.
5. **Служебные аккаунты с `empty_password`**: `empty_password: True` позволяет вход без пароля. Используйте только для аккаунтов, защищённых другими средствами (например, SSH-ключами без пароля).
6. **Конфликтующие группы**: Если пользователь добавляется в группу через `groups`, но группа не существует, состояние завершится ошибкой. Используйте `optional_groups` (3001+) для игнорирования несуществующих групп.

## Лучшие практики

1. **Break-glass аккаунты**: Создавайте аварийные учётные записи с `password_lock: True` и `expire` в ближайшую дату. Разблокируйте только в экстренных ситуациях и логируйте каждое использование через `event_return`.
2. **Временные аккаунты**: Для подрядчиков используйте `expire` и автоматическую очистку через `schedule` или CI/CD-пайплайны. Никогда не оставляйте временные аккаунты без срока истечения.
3. **Ротация паролей**: Применяйте политику `mindays`/`maxdays`/`warndays` и отслеживайте предупреждения через Returner. Используйте `enforce_password: True` для принудительной смены при компрометации.
4. **Централизованное хранение секретов**: Храните хэши паролей в Vault или GPG-шифрованном Pillar. Никогда не коммитьте пароли в Git, даже зашифрованные, без согласованного процесса ротации ключей.
5. **Аудит изменений**: Настройте `event_return` или внешний returner (PostgreSQL, Elasticsearch) для отслеживания всех изменений пользователей. Сопоставляйте изменения с JID и инициатором (eAuth-пользователь).
6. **Идемпотентность**: Пишите состояния так, чтобы их можно было безопасно применять многократно. Избегайте `force: True` в `user.absent` без явной необходимости.
7. **Изоляция окружений**: Используйте `saltenv`/`pillarenv` для dev/staging/prod. Никогда не применяйте production-состояния в dev-среде без явного указания окружения.
8. **Валидация перед применением**: Используйте `test=True` (dry-run) для проверки изменений перед применением в production. Интегрируйте валидацию в CI/CD-пайплайны.

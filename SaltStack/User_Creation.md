---
**Надёжность:** 10 (SSoT + Проектный контекст 2026)
**Свежесть:** Актуально на июль 2026
---

# Управление пользователями и группами в SaltStack

## Определения

- **`user.present`**: Функция состояния (state function), обеспечивающая декларативное управление пользователями. Гарантирует наличие пользователя с заданными атрибутами.
- **`user.absent`**: Гарантирует отсутствие пользователя в системе.
- **`group.present`**: Управляет созданием и параметрами системных групп.
- **`ssh_auth.present`**: Управляет авторизованными SSH-ключами для конкретного пользователя.
- **`user.manage`**: Продвинутый метод для массового управления пользователями на основе структуры данных.

---

## Основные концепции

SaltStack реализует модель идемпотентного управления пользователями:
1.  **Создание**: Если пользователя нет, он будет создан с указанными параметрами.
2.  **Сверка (Reconciliation)**: Если пользователь существует, Salt проверит его атрибуты (UID, GID, домашний каталог, оболочка, GECOS-данные).
3.  **Обновление**: При обнаружении расхождений Salt применит изменения (например, сменит оболочку или добавит в группы).

**Взаимосвязь компонентов:**
Обычно создание пользователя сопровождается созданием его основной группы (`group.present`) и добавлением SSH-ключей (`ssh_auth.present`). Для обеспечения безопасности пароли никогда не хранятся в SLS-файлах в открытом виде — для этого используется [Pillar и секреты](Security_Approaches.md).

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
    - gid_from_name: True
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

---

## Дополнительная информация

### Расширенные параметры `user.present`

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `uid` | Числовой ID пользователя | `uid: 2000` |
| `gid` | Основной GID или имя группы | `gid: 2000` |
| `groups` | Список дополнительных групп | `groups: [sudo, wheel]` |
| `remove_groups` | Удалять из групп, не указанных в списке | `remove_groups: False` |
| `fullname` | Полное имя (GECOS) | `fullname: Ivan Ivanov` |
| `roomnumber` | Номер комнаты (GECOS) | `roomnumber: 404` |
| `workphone` | Рабочий телефон (GECOS) | `workphone: 555-0101` |
| `createhome` | Создавать `/home` при отсутствии | `createhome: True` |
| `system` | Создать системного пользователя | `system: True` |
| `unique_uid` | Гарантировать уникальность UID | `unique_uid: True` |

### Специфика операционных систем

- **Linux**: Использует стандартные утилиты `useradd`/`usermod`. Пароли должны передаваться в виде хэша (совместимого с `crypt`).
- **macOS**: Использует `dscl`. Некоторые параметры (например, `uid`) Salt обрабатывает специфично для Open Directory.
- **Windows**: Управляет локальными пользователями. Параметры `shell` и `home` могут интерпретироваться иначе.

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

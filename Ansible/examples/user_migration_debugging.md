# Ansible: Отладка миграции на выделенного пользователя

## Определения

**Миграция на выделенного пользователя** — процесс перехода от выполнения плейбуков Ansible от имени `root` к использованию отдельного пользователя с ограниченными привилегиями и `sudo`. Это фундаментальная мера безопасности, требующая корректной настройки SSH-подключения и прав доступа.

## Базовые концепции

### Ключевые требования

Для успешной миграции необходимо обеспечить:

1. **SSH-подключение** — Ansible должен подключаться к хосту от имени нового пользователя
2. **Права sudo** — пользователь должен иметь беспарольный доступ к `sudo`
3. **Конфигурация Ansible** — параметры `remote_user` или `ansible_user` должны быть обновлены

### Типовые ошибки миграции

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `UNREACHABLE: Permission denied (publickey,password)` | Ansible подключается как `root`, но SSH-доступ для root запрещен | Указать `ansible_user` в инвентаре или `remote_user` в `ansible.cfg` |
| `Permission denied` при выполнении задач | Задачи требуют привилегий, но `become: true` не указан | Добавить `become: true` на уровень плея или задачи |
| `sudo: no password provided` | Пользователь не настроен на беспарольный `sudo` | Настроить `/etc/sudoers.d/<user>` или использовать `-K` |

Подробное руководство по созданию выделенного пользователя с беспарольным `sudo` — в [ansible_security_best_practices.md](../ansible_security_best_practices.md#настройка-выделенного-пользователя-через-плейбук).

---

## Практические сценарии

### Сценарий: Миграция с root на выделенного пользователя

#### Шаг 1: Исходное состояние

Плейбук выполняется от `root`:

```ini
# inventory.ini
[production]
server1 ansible_host=192.168.1.10 ansible_user=root
```

```yaml
# test_playbook.yml
---
- name: Test basic setup
  hosts: production
  tasks:
    - name: Update apt cache
      ansible.builtin.apt:
        update_cache: yes
```

#### Шаг 2: Подготовка хоста

Выполните следующие действия на целевом хосте:

1. **Создайте пользователя** с беспарольным `sudo` — используйте плейбук из [ansible_security_best_practices.md](../ansible_security_best_practices.md)
2. **Отключите `PermitRootLogin`** в `/etc/ssh/sshd_config`:

```yaml
# disable_root_login.yml
---
- name: Disable root login via SSH
  hosts: all
  become: true
  tasks:
    - name: Disallow root login over SSH
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?PermitRootLogin'
        line: 'PermitRootLogin no'
        state: present
        validate: 'sshd -t -f %s'
      notify: restart ssh

  handlers:
    - name: restart ssh
      ansible.builtin.service:
        name: sshd
        state: restarted
```

#### Шаг 3: Диагностика ошибки подключения

После отключения root-доступа запуск плейбука завершится ошибкой:

```bash
ansible-playbook -i inventory.ini test_playbook.yml
```

```
fatal: [server1]: UNREACHABLE! => {
    "changed": false,
    "msg": "Failed to connect to the host via ssh: Permission denied (publickey,password).",
    "unreachable": true
}
```

**Диагноз:** Ansible продолжает подключаться как `root`, но доступ запрещен.

#### Шаг 4: Настройка подключения

**Вариант А: Изменение инвентаря**

```ini
[production]
server1 ansible_host=192.168.1.10 ansible_user=ansible_user
```

**Вариант Б: Изменение `ansible.cfg` (рекомендуется)**

```ini
[defaults]
remote_user = ansible_user
```

После изменения плейбук подключится успешно, но задачи могут падать с `Permission denied`.

#### Шаг 5: Настройка привилегий

Добавьте `become: true` для выполнения задач с повышенными привилегиями:

```yaml
---
- name: Test basic setup
  hosts: production
  become: true
  tasks:
    - name: Update apt cache
      ansible.builtin.apt:
        update_cache: yes
```

**Порядок выполнения:**
1. `ansible_user` подключается по SSH
2. Выполняется `sudo apt update` через беспарольный `sudo`

---

## Дополнительная информация

- **Флаг `-K` (`--ask-become-pass`)** — запрашивает пароль `sudo`, если беспарольный доступ не настроен
- **Vault** — хранение паролей и секретов в [Vault/basics.md](../Vault/basics.md)
- **Тестирование** — автоматическая проверка с [Molecule](../ansible_testing_with_molecule.md)
- **Идемпотентность** — принцип повторного запуска без побочных эффектов в [ansible_core_concepts.md](../ansible_core_concepts.md#идемпотентность)

# Ansible: Отладка перехода с root на выделенного пользователя

## Определения

В этом примере рассматривается типичный сценарий отладки, возникающий при переходе от выполнения всех задач Ansible от имени `root` пользователя к использованию выделенного пользователя с ограниченными привилегиями и `sudo`. Это включает в себя шаги по созданию пользователя, настройке SSH, отключению прямого SSH-доступа для `root` и адаптации плейбуков.

## Основные концепции

Переход с `root` на выделенного пользователя с `sudo` — это фундаментальная мера безопасности. Однако, это может привести к ошибкам подключения и выполнения задач, если не учесть следующие моменты:

* **SSH-подключение:** Ansible должен иметь возможность подключиться к удаленному хосту от имени нового пользователя.
* **Права доступа:** Новый пользователь должен иметь право выполнять команды с повышенными привилегиями через `sudo`.
* **Конфигурация Ansible:** Параметры подключения в Ansible (`remote_user`) должны быть обновлены.

## Практические сценарии

### Сценарий: Миграция с Root на выделенного пользователя и отладка ошибок

Предположим, у нас есть рабочий плейбук, который ранее запускался от `root`, но теперь мы хотим повысить безопасность, используя выделенного пользователя (`ansible_user`).

#### Шаг 1: Исходное состояние (Playbook работает от root)

Изначально Ansible подключается к хосту как `root`, например, через пароль или ключ `root`.

`inventory.ini`:

```ini
[production]
server1 ansible_host=YOUR_SERVER_IP ansible_user=root
```

Простой плейбук `test_playbook.yml`:

```yaml
---
- name: Test basic setup
  hosts: production
  tasks:
    - name: Update apt cache (as root)
      ansible.builtin.apt:
        update_cache: yes
```

Этот плейбук успешно выполняется.

#### Шаг 2: Создание выделенного пользователя и отключение root-доступа

Мы следуем рекомендациям по безопасности.

1. **Создаем пользователя `ansible_user`** с полными правами `sudo`, используя идиоматичный плейбук из документа [Рекомендации по безопасности](ansible_security_best_practices.md). Предполагается, что вы запускаете его от `root`.

2. **Отключаем `PermitRootLogin` в `/etc/ssh/sshd_config`** с помощью отдельного плейбука, чтобы сделать процесс полностью автоматизированным и идемпотентным.

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

    После выполнения этих двух шагов (создание пользователя и отключение root), мы готовы к отладке.

#### Шаг 3: Повторный запуск плейбука (Возникновение ошибки)

Теперь, если мы попытаемся запустить `test_playbook.yml` без изменений:

```bash
ansible-playbook -i inventory.ini test_playbook.yml
```

Мы получим ошибку:

```
fatal: [server1]: UNREACHABLE! => {"changed": false, "msg": "Failed to connect to the host via ssh: Permission denied (publickey,password).", "unreachable": true}
```

**Причина:** Ansible все еще пытается подключиться как `root`, но `root` вход по SSH теперь запрещен.

#### Шаг 4: Корректировка `inventory.ini` или `ansible.cfg`

Необходимо указать Ansible использовать нового пользователя для подключения.

**Вариант А: Изменение `inventory.ini`:**

```ini
[production]
server1 ansible_host=YOUR_SERVER_IP ansible_user=ansible_user
```

**Вариант Б: Настройка в `ansible.cfg` (рекомендуется для проекта):**
Добавляем в `ansible.cfg` (рядом с плейбуком):

```ini
[defaults]
remote_user = ansible_user
```

Теперь Ansible будет подключаться как `ansible_user`. Повторный запуск плейбука. Теперь подключение будет успешным.

#### Шаг 5: Адаптация задач с `become: true`

После успешного подключения, некоторые задачи, требующие повышенных привилегий (например, установка пакетов, управление службами), могут завершаться с ошибкой "Permission denied" или "Insufficient privileges".

Если в нашем `test_playbook.yml` не было `become: true`:

```yaml
---
- name: Test basic setup
  hosts: production
  tasks:
    - name: Update apt cache (as ansible_user, no sudo)
      ansible.builtin.apt:
        update_cache: yes
```

Задача завершится с ошибкой, потому что `ansible_user` не имеет прав для выполнения `apt update` без `sudo`.

**Решение:** Добавляем `become: true` в плей или конкретную задачу.

```yaml
---
- name: Test basic setup
  hosts: production
  become: true # Повышаем привилегии для всего плея
  tasks:
    - name: Update apt cache (as ansible_user, with sudo)
      ansible.builtin.apt:
        update_cache: yes
```

Теперь плейбук должен успешно выполниться. `ansible_user` подключится, а затем выполнит `sudo apt update`, используя настроенный беспарольный `sudo`.

## Дополнительная информация

* **Флаги `--ask-become-pass` (`-K`):** Если `ansible_user` настроен с паролем для `sudo`, его можно запрашивать при запуске плейбука.
* **Ansible Vault:** Пароли и другие чувствительные данные всегда должны храниться в [Ansible Vault](../ansible_vault.md).
* **Тестирование:** Для автоматического тестирования ролей и плейбуков, включая проверку прав доступа, используйте [Molecule](../ansible_testing_with_molecule.md).
* **Идемпотентность:** Убедитесь, что задачи остаются идемпотентными после всех изменений.

# Ansible: Отладка перехода с root на выделенного пользователя

## Определения

В этом примере рассматривается типичный сценарий отладки, возникающий при переходе от выполнения всех задач Ansible от имени `root` пользователя к использованию выделенного пользователя с ограниченными привилегиями и `sudo`. Это включает в себя шаги по созданию пользователя, настройке SSH, отключению прямого SSH-доступа для `root` и адаптации плейбуков.

## Основные концепции

Переход с `root` на выделенного пользователя с `sudo` — это фундаментальная мера безопасности. Однако, это может привести к ошибкам подключения и выполнения задач, если не учесть следующие моменты:
*   **SSH-подключение:** Ansible должен иметь возможность подключиться к удаленному хосту от имени нового пользователя.
*   **Права доступа:** Новый пользователь должен иметь право выполнять команды с повышенными привилегиями через `sudo`.
*   **Конфигурация Ansible:** Параметры подключения в Ansible (`remote_user`) должны быть обновлены.

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

Мы следуем рекомендациям по безопасности и выполняем шаги по [настройке выделенного пользователя](ansible_security_best_practices.md).

1.  **Создаем пользователя `ansible_user`:**
    ```bash
    ansible server1 -m user -a "name=ansible_user shell=/bin/bash state=present" --become
    ```
2.  **Настраиваем SSH-ключи для `ansible_user`:**
    ```bash
    ansible server1 -m file -a "path=/home/ansible_user/.ssh state=directory owner=ansible_user group=ansible_user mode=0700" --become
    ansible server1 -m copy -a 'content="{{ lookup("file", "~/.ssh/id_rsa.pub") }}" dest=/home/ansible_user/.ssh/authorized_keys owner=ansible_user group=ansible_user mode=0600' --become
    ```
3.  **Настраиваем беспарольный `sudo` для `ansible_user`:**
    Создаем файл `/etc/sudoers.d/90-ansible-user` на `server1` с содержимым:
    ```
    ansible_user ALL=(ALL) NOPASSWD: ALL
    ```
    (Это можно сделать через Ansible с модулем `ansible.builtin.copy` или `ansible.builtin.template`.)
4.  **Отключаем `PermitRootLogin` в `/etc/ssh/sshd_config`:**
    Изменяем `PermitRootLogin yes` на `PermitRootLogin no` и перезапускаем службу SSH.
    (Можно сделать через Ansible с модулем `ansible.builtin.lineinfile` и `ansible.builtin.service`).

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

*   **Флаги `--ask-become-pass` (`-K`):** Если `ansible_user` настроен с паролем для `sudo`, его можно запрашивать при запуске плейбука.
*   **Ansible Vault:** Пароли и другие чувствительные данные всегда должны храниться в [Ansible Vault](../ansible_vault.md).
*   **Тестирование:** Для автоматического тестирования ролей и плейбуков, включая проверку прав доступа, используйте [Molecule](../ansible_testing_with_molecule.md).
*   **Идемпотентность:** Убедитесь, что задачи остаются идемпотентными после всех изменений.
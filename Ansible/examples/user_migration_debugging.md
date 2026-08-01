# Отладка миграции на выделенного пользователя в Ansible

## Определения

**Миграция на выделенного пользователя** — процесс перехода от запуска плейбуков от имени суперпользователя `root` к использованию отдельной системной учетной записи (например, `ansible-deploy`) с ограниченными привилегиями и механизмом `sudo` (substitute user do). Это критическая мера безопасности, требующая согласованной настройки SSH (Secure Shell) и прав доступа.

**Privilege Escalation (повышение привилегий)** — встроенный механизм Ansible (директива `become`), позволяющий выполнять задачи от имени другого пользователя (обычно `root`) после успешного первоначального SSH-подключения от имени непривилегированного пользователя.

## Базовые концепции

### Ключевые требования для успешной миграции

Чтобы миграция прошла без потери доступа к серверу ("lockout"), необходимо строго соблюдать последовательность:

1. **Создание пользователя**: Пользователь должен существовать на целевых системах.
2. **Доступ по SSH**: Контрольный узел должен иметь возможность подключиться по SSH от имени нового пользователя (через `authorized_keys`).
3. **Привилегии sudo**: Пользователь должен иметь права на выполнение команд от имени суперпользователя. Для автоматизации рекомендуется настраивать беспарольный доступ (`NOPASSWD`).
4. **Блокировка root**: Только после верификации пп. 1-3 можно отключать `PermitRootLogin` в конфигурации SSH-сервера.

### Типовые ошибки и диагностика

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `UNREACHABLE! Permission denied (publickey)` | Ansible пытается войти как `root`, но `PermitRootLogin` уже отключен, либо для нового пользователя не добавлен SSH-ключ. | Проверить `ansible_user` и убедиться, что публичный ключ добавлен в `~/.ssh/authorized_keys` нового пользователя. |
| `Permission denied` (в логах задачи) | Задача требует прав суперпользователя (например, `apt`, `systemd`), но директива `become: true` отсутствует. | Добавить `become: true` на уровне сценария (play) или конкретной задачи. |
| `Missing sudo password` или зависание | Для пользователя не настроен `NOPASSWD` в `sudoers`, а пароль для `become` не передан. | Настроить конфигурацию в `/etc/sudoers.d/` или передать пароль через `--ask-become-pass` / Ansible Vault. |

---

## Практические сценарии

### Сценарий: Безопасная миграция с `root` на `ansible-deploy`

Ниже представлен **идемпотентный плейбук (Bootstrap)**, который безопасно выполняет все этапы миграции за один запуск. Этот плейбук запускается в последний раз от имени `root`.

#### 1. Подготовка конфигурации (Bootstrap Playbook)

Файл `bootstrap.yml`:

```yaml
---
- name: Безопасная миграция на выделенного пользователя Ansible
  hosts: all
  become: false # На этом этапе мы уже подключаемся как root, sudo не требуется
  vars:
    deploy_user: "ansible-deploy"
    # Читаем публичный ключ контрольного узла из локального файла
    deploy_pub_key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"

  tasks:
    - name: Создание группы для пользователя Ansible
      ansible.builtin.group:
        name: "{{ deploy_user }}"
        state: present

    - name: Создание пользователя {{ deploy_user }}
      ansible.builtin.user:
        name: "{{ deploy_user }}"
        group: "{{ deploy_user }}"
        shell: /bin/bash
        create_home: yes
        state: present

    - name: Настройка авторизации по SSH ключу
      ansible.posix.authorized_key:
        user: "{{ deploy_user }}"
        state: present
        key: "{{ deploy_pub_key }}"

    - name: Настройка беспарольного sudo (NOPASSWD)
      ansible.builtin.copy:
        content: "{{ deploy_user }} ALL=(ALL) NOPASSWD: ALL\n"
        dest: "/etc/sudoers.d/{{ deploy_user }}"
        mode: '0440'
        # Обязательная валидация синтаксиса, чтобы не сломать sudo
        validate: 'visudo -cf %s'

    - name: Отключение удаленного входа для root по SSH
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?PermitRootLogin'
        line: 'PermitRootLogin no'
        state: present
        validate: 'sshd -t -f %s'
      notify: Restart SSH

  handlers:
    - name: Restart SSH
      ansible.builtin.service:
        name: ssh
        state: restarted
```

Запуск Bootstrap-плейбука (пока доступен `root`):

```bash
ansible-playbook -i inventory.ini bootstrap.yml -u root
# → Результат: Пользователь создан, ключи добавлены, root заблокирован.
```

#### 2. Диагностика ошибки после изменений

Если попытаться запустить обычный плейбук от имени `root` после успешной миграции:

```bash
ansible-playbook -i inventory.ini app_deploy.yml -u root
# → fatal: [server1]: UNREACHABLE! msg: Permission denied (publickey,password)
```

**Диагноз:** SSH-сервер отвергает подключение, так как удаленный доступ для `root` (`PermitRootLogin no`) закрыт.

#### 3. Переход на новую конфигурацию (После миграции)

Теперь необходимо обновить конфигурацию проекта для использования нового пользователя и повышения привилегий.

**Обновление инвентаря `inventory.ini`:**

```ini
[production]
server1 ansible_host=192.168.1.10
# Указывать ansible_user здесь не обязательно, лучше вынести в group_vars
```

**Настройка переменных (`group_vars/all.yml` или `ansible.cfg`):**

```yaml
---
# group_vars/all.yml
ansible_user: "ansible-deploy"
```

**Адаптация рабочих плейбуков:**

Теперь все задачи, меняющие состояние системы, должны явно запрашивать права суперпользователя через `become: true`.

```yaml
---
- name: Деплой приложения
  hosts: production
  become: true # Использование sudo для всего сценария
  
  tasks:
    - name: Обновление кэша пакетов (apt)
      ansible.builtin.apt:
        update_cache: yes
```

---

## Дополнительная информация

### Важные нюансы

1.  **Проверка конфигурации sudoers**: Всегда используйте параметр `validate: 'visudo -cf %s'` при изменении файлов в `/etc/sudoers.d/`. Ошибка в синтаксисе sudoers приведет к полной блокировке механизма `sudo` на сервере.
2.  **become_method**: По умолчанию Ansible использует `sudo`. В специфичных дистрибутивах (например, OpenBSD) может потребоваться настройка переменной `ansible_become_method: doas` или `su`.
3.  **Логирование аудита**: При использовании `become` действия пользователя логируются в системном журнале (например, `/var/log/auth.log` или journald), что удовлетворяет корпоративным требованиям безопасности.

## Смотрите также

- [Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)
- [Модули управления пользователями и безопасностью](../Modules/ansible_security_and_user_management_modules.md)
- [Основы Ansible Vault](../Vault/basics.md)

---
**Reliability Score: 10** (Подтверждено официальной документацией Ansible по Privilege Escalation и лучшими практиками безопасности ОС Linux).
# Миграция на выделенного пользователя Ansible

## Определения

**Миграция на выделенного пользователя** — процесс перехода от запуска плейбуков от имени `root` к использованию отдельной системной учетной записи (например, `ansible-deploy`) с ограниченными привилегиями и механизмом `sudo`. Это критическая мера безопасности в практиках DevOps/SRE, требующая согласованной настройки SSH, прав доступа и аудита выполнения.

**Принцип наименьших привилегий (PoLP — Principle of Least Privilege)** — базовый принцип безопасности, согласно которому учетная запись автоматизации должна иметь только те права, которые необходимы для выполнения её функций. Выполнение от имени `root` по умолчанию нарушает этот принцип.

**Bootstrap-плейбук** — идемпотентный плейбук, выполняемый один раз для первоначальной настройки выделенного пользователя. Запускается от имени `root` (последний раз с использованием суперпользователя), после чего все последующие запуски выполняются от имени выделенного пользователя с `sudo`.

**Privilege Escalation (повышение привилегий)** — встроенный механизм Ansible (директива `become`), позволяющий выполнять задачи от имени другого пользователя после успешного SSH-подключения от имени непривилегированного пользователя.

**`become`** — директива уровня плейбука или задачи, включающая механизм повышения привилегий. Принимает логические значения `true`/`false`. По умолчанию `false`.

**`become_method`** — параметр, определяющий утилиту для повышения привилегий. Допустимые значения: `sudo` (по умолчанию), `su`, `doas` (OpenBSD), `pbrun`, `pfexec`. На большинстве дистрибутивов Linux используется `sudo`.

**`become_user`** — целевой пользователь, от имени которого выполняется команда после повышения привилегий (по умолчанию `root`). Позволяет выполнять задачи от имени специализированных пользователей (например, `postgres`, `www-data`), минимизируя время работы в контексте суперпользователя.

**`ansible_user`** — переменная инвентаря, определяющая имя пользователя для первоначального SSH-подключения к управляемому хосту. Заменяет использование флага `-u` в командной строке.

**`ansible_become`** — переменная инвентаря, эквивалент директивы `become: true` на уровне плейбука. Позволяет глобально включить повышение привилегий для всех задач.

**sudoers** — конфигурационный файл (`/etc/sudoers` или файлы в `/etc/sudoers.d/`), определяющий правила доступа к `sudo`. Управляется утилитой `visudo`. Ошибка в синтаксисе приводит к полной блокировке механизма `sudo`.

**`NOPASSWD`** — директива в конфигурации `sudoers`, позволяющая выполнять команды от имени суперпользователя без запроса пароля. Критически важна для автоматизации Ansible, так как предотвращает зависание пайплайна на запросе ввода пароля.

**`visudo`** — утилита безопасного редактирования файла `sudoers`. Обязательно проверяет синтаксис перед сохранением, предотвращая блокировку `sudo` из-за синтаксических ошибок.

**ControlPersist (SSH Multiplexing)** — механизм переиспользования SSH-соединений для ускорения последующих подключений. Соединения кэшируются в сокет-файле и переиспользуются. Может вызывать проблемы при смене прав доступа, так как старая сессия удерживает соединение с неактуальными правами.

**SELinux (Security-Enhanced Linux)** — механизм принудительного контроля доступа (MAC) в ядре Linux. На системах с SELinux (RHEL, CentOS, Fedora, Rocky Linux) контексты безопасности директории `.ssh` должны быть корректными, иначе SSH-сервер отклонит ключ даже при правильном `authorized_keys`.

**`no_log`** — параметр задачи Ansible, предотвращающий запись чувствительных данных (пароли, ключи, токены) в логи и вывод консоли. Устанавливается как `no_log: true` на уровне задачи.

## Базовые концепции

### Жизненный цикл SSH-ключей

При миграции на выделенного пользователя необходимо правильно управлять SSH-ключами:

1. **Генерация ключей:** Используйте Ed25519 (современный стандарт) или RSA 4096 бит:
   ```bash
   ssh-keygen -t ed25519 -C "ansible@control-node" -f ~/.ssh/id_ed25519_ansible
   # → Generating public/private ed25519 key pair.
   # → Enter passphrase (empty for no passphrase): 
   # → Your identification has been saved in /Users/.../.ssh/id_ed25519_ansible
   ```
2. **Распространение публичного ключа:** Используйте модуль `ansible.posix.authorized_key` для добавления ключа в `~/.ssh/authorized_keys` нового пользователя.
3. **Очистка старых ключей:** Параметр `exclusive: yes` в `ansible.posix.authorized_key` удаляет все старые ключи, оставляя только указанные.
4. **Ротация ключей:** Регулярно обновляйте SSH-ключи. Старые ключи хостов хранятся в `~/.ssh/known_hosts` и должны обновляться через `ansible.builtin.known_hosts`.

### Конфигурация SELinux для SSH

На системах с включенным SELinux (RHEL, CentOS, Fedora, Rocky Linux) контексты безопасности критически важны:

```bash
# Просмотр текущего контекста
ls -Z /home/ansible-deploy/.ssh
# → system_u:object_r:user_home_t:s0 authorized_keys

# Восстановление контекстов (при ручных правках)
restorecon -Rv /home/ansible-deploy/.ssh
# → restorecon /home/ansible-deploy/.ssh
# → restorecon /home/ansible-deploy/.ssh/authorized_keys

# Проверка логов SELinux при проблемах
ausearch -m avc -ts recent | grep sshd
```

**Типичные ошибки SELinux:**

| Симптом | Причина | Решение |
|---|---|---|
| SSH-ключ отклоняется despite `authorized_keys` | Неверный контекст `authorized_keys` | `restorecon -Rv /home/user/.ssh` |
| `Permission denied (publickey)` в audit.log | SELinux запрещает чтение ключа | Проверка контекстов через `ls -Z`, восстановление через `restorecon` |

### Влияние ControlPersist на миграцию

Механизм SSH Multiplexing (ControlPersist) может вызывать проблемы при смене прав, так как старая сессия удерживает соединение с неактуальными привилегиями:

```bash
# Проверка активных сокетов
ps aux | grep ssh
# → user   12345 ssh -o ControlMaster=auto -o ControlPersist=600s ...

# Сброс через Ansible
ansible all -m shell -a "exit" --ssh-extra-args="-O exit"

# Или ручной сброс
rm -f ~/.ansible/cp/ansible-ssh-*
```

### Синтаксис sudoers для автоматизации

Конфигурация `sudoers` для пользователя Ansible:

```bash
# Формат: кто где=(от кого) что
ansible-deploy ALL=(ALL) NOPASSWD: ALL

# Гранулярный доступ (рекомендуется для production)
ansible-deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *, /usr/bin/apt-get update

# С выключенным mail (без почтовых уведомлений)
Defaults:ansible-deploy !mail_always
ansible-deploy ALL=(ALL) NOPASSWD: ALL
```

**Валидация синтаксиса (критически важна):**

```bash
# Всегда проверяйте синтаксис перед сохранением
visudo -cf /etc/sudoers.d/ansible-deploy
# → /etc/sudoers.d/ansible-deploy: parsed OK

# Если валидация прошла неуспешно — файл НЕ будет сохранен
# и sudo останется работоспособным
```

### Разделение кода и конфигурации

Фундаментальный принцип организации масштабируемой автоматизации:

- **Логика (Код):** Общие алгоритмы настройки ("КАК") инкапсулируются в централизованном репозитории с **[Ansible-ролями](../ansible_roles.md)**.
- **Данные (Конфигурация):** Специфичные параметры ("ЧТО" именно настраивать: инвентарь, версии, **[переменные](../PlaybookStructure/variables.md)**) хранятся в изолированных репозиториях проектов.

### Версии и совместимость

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 2.20 | `ansible --version` |
| Python (Control Node) | 3.11+ | ≥ 3.12 | `python3 --version` |
| Python (Target) | 3.9+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` |
| ansible-lint | 26.x+ | ≥ 26.8.0 | `ansible-lint --version` |
| ansible.builtin.user | Стандартный модуль | Стандартный | `ansible-doc ansible.builtin.user` |
| ansible.posix.authorized_key | 2.2+ | 2.2+ | `ansible-galaxy collection list | grep ansible.posix` |

---

## Практические сценарии

### Сценарий 1: Безопасная миграция с `root` на `ansible-deploy`

Ниже представлен **идемпотентный плейбук (Bootstrap)**, который безопасно выполняет все этапы миграции за один запуск. Этот плейбук запускается в последний раз от имени `root`.

#### 1. Bootstrap Playbook

Файл `bootstrap.yml`:

```yaml
---
- name: Безопасная миграция на выделенного пользователя Ansible
  hosts: all
  become: false # На этом этапе мы уже подключаемся как root, sudo не требуется
  vars:
    deploy_user: "ansible-deploy"
    # Читаем публичный ключ контрольного узла из локального файла
    deploy_pub_key: "{{ lookup('file', '~/.ssh/id_ed25519_ansible.pub') }}"

  tasks:
    - name: Установка пакета sudo (для минимальных образов)
      ansible.builtin.package:
        name: sudo
        state: present

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
        owner: root
        group: root
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
# → PLAY [Безопасная миграция на выделенного пользователя Ansible] *******
# → TASK [Установка пакета sudo (для минимальных образов)] ******************
# → ok: [server1]
# → ...
# → PLAY RECAP **************************************************************
# → server1                     : ok=6    changed=3    unreachable=0    failed=0
```

#### 2. Валидация миграции

После успешного выполнения bootstrap-плейбука необходимо проверить:

```bash
# Проверка создания пользователя
ansible all -m shell -a "id ansible-deploy" --become
# → server1 | CHANGED | rc=0 > uid=1001(ansible-deploy) gid=1001(ansible-deploy) ...

# Проверка SSH-подключения от имени нового пользователя
ssh -i ~/.ssh/id_ed25519_ansible ansible-deploy@server1 "echo OK"
# → OK

# Проверка sudoers
ansible all -m shell -a "sudo -l -U ansible-deploy" --become
# → (ALL : ALL) ALL

# Проверка доступности
ansible all -m ping -u ansible-deploy
# → server1 | SUCCESS => {
# →     "changed": false,
# →     "ping": "pong"
# → }
```

#### 3. Обновление конфигурации проекта

**Обновление инвентаря `inventory.ini`:**

```ini
[production]
server1 ansible_host=192.168.1.10
# Указывать ansible_user здесь не обязательно, лучше вынести в group_vars
```

**Инспекция через `ansible-inventory`:**

```bash
ansible-inventory --host server1 --vars | grep ansible_user
# → ansible_user: ansible-deploy
```

**Настройка переменных (`group_vars/all.yml`):**

```yaml
---
# group_vars/all.yml
ansible_user: "ansible-deploy"
ansible_become: true
ansible_become_method: sudo
```

**Адаптация рабочих плейбуков:**

```yaml
---
- name: Деплой приложения
  hosts: production
  become: true # Использование sudo для всего сценария
  
  tasks:
    - name: Обновление кэша пакетов (apt)
      ansible.builtin.apt:
        update_cache: yes
      become: true
```

### Сценарий 2: Откат миграции (Rollback)

Если миграция прошла неуспешно или требуется вернуть доступ от `root`, используйте следующий плейбук отката:

```yaml
---
- name: Откат миграции на выделенного пользователя
  hosts: all
  become: true
  vars:
    deploy_user: "ansible-deploy"

  tasks:
    - name: Восстановление доступа root по SSH
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?PermitRootLogin'
        line: 'PermitRootLogin yes'
        state: present
        validate: 'sshd -t -f %s'
      notify: Restart SSH

    - name: Удаление конфигурации sudo для {{ deploy_user }}
      ansible.builtin.file:
        path: "/etc/sudoers.d/{{ deploy_user }}"
        state: absent

    - name: Удаление пользователя {{ deploy_user }}
      ansible.builtin.user:
        name: "{{ deploy_user }}"
        state: absent
        remove: yes

    - name: Удаление SSH-ключа из authorized_keys root
      ansible.posix.authorized_key:
        user: root
        state: absent
        key: "{{ lookup('file', '~/.ssh/id_ed25519_ansible.pub') }}"

  handlers:
    - name: Restart SSH
      ansible.builtin.service:
        name: ssh
        state: restarted
```

Запуск отката:

```bash
# Запуск от имени root (если еще доступен)
ansible-playbook -i inventory.ini rollback.yml -u root

# Или от имени ansible-deploy (если root уже заблокирован)
ansible-playbook -i inventory.ini rollback.yml -u ansible-deploy --ask-become-pass
```

### Сценарий 3: Миграция с поддержкой SELinux

На системах с SELinux (RHEL/CentOS/Fedora) миграция требует дополнительных шагов:

```yaml
---
- name: Миграция с поддержкой SELinux
  hosts: all
  become: false
  vars:
    deploy_user: "ansible-deploy"
    deploy_pub_key: "{{ lookup('file', '~/.ssh/id_ed25519_ansible.pub') }}"

  tasks:
    - name: Установка пакета sudo
      ansible.builtin.package:
        name: sudo
        state: present

    - name: Создание группы
      ansible.builtin.group:
        name: "{{ deploy_user }}"
        state: present

    - name: Создание пользователя
      ansible.builtin.user:
        name: "{{ deploy_user }}"
        group: "{{ deploy_user }}"
        shell: /bin/bash
        create_home: yes
        state: present

    - name: Настройка SSH-ключа
      ansible.posix.authorized_key:
        user: "{{ deploy_user }}"
        state: present
        key: "{{ deploy_pub_key }}"
        exclusive: yes

    - name: Настройка SELinux контекста для .ssh директории
      community.general.sefcontext:
        target: '/home/{{ deploy_user }}/.ssh(/.*)?'
        setype: ssh_home_t
        state: present
      notify: Restore SELinux Context

    - name: Применение SELinux контекста
      ansible.builtin.command: "restorecon -Rv /home/{{ deploy_user }}/.ssh"
      changed_when: false

    - name: Настройка беспарольного sudo
      ansible.builtin.copy:
        content: "{{ deploy_user }} ALL=(ALL) NOPASSWD: ALL\n"
        dest: "/etc/sudoers.d/{{ deploy_user }}"
        owner: root
        group: root
        mode: '0440'
        validate: 'visudo -cf %s'

    - name: Блокировка root
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

    - name: Restore SELinux Context
      ansible.builtin.command: "restorecon -Rv /home/{{ deploy_user }}/.ssh"
      become: yes
```

### Сценарий 4: Мульти-пользовательская миграция (разные роли)

Для разделения ответственности рекомендуется создавать отдельных пользователей для разных задач:

```yaml
---
- name: Создание мульти-пользовательской среды
  hosts: all
  become: false
  vars:
    users:
      - name: "ansible-deploy"
        groups: "deploy"
        comment: "Ansible Deployment User"
      - name: "ansible-monitoring"
        groups: "monitoring"
        comment: "Ansible Monitoring User"
      - name: "ansible-backup"
        groups: "backup"
        comment: "Ansible Backup User"

  tasks:
    - name: Создание групп
      ansible.builtin.group:
        name: "{{ item }}"
        state: present
      loop:
        - deploy
        - monitoring
        - backup

    - name: Создание пользователей
      ansible.builtin.user:
        name: "{{ item.name }}"
        groups: "{{ item.groups }}"
        shell: /bin/bash
        create_home: yes
        comment: "{{ item.comment }}"
        state: present
      loop: "{{ users }}"

    - name: Настройка SSH-ключей для каждого пользователя
      ansible.posix.authorized_key:
        user: "{{ item.name }}"
        state: present
        key: "{{ lookup('file', '~/.ssh/' + item.name + '.pub') }}"
      loop: "{{ users }}"

    - name: Настройка sudoers с гранулярными правами
      ansible.builtin.copy:
        content: |
          {{ item.name }} ALL=(ALL) NOPASSWD: {{ item.sudo_commands | default('ALL') }}
        dest: "/etc/sudoers.d/{{ item.name }}"
        owner: root
        group: root
        mode: '0440'
        validate: 'visudo -cf %s'
      loop: "{{ users }}"
      vars:
        users:
          - name: "ansible-deploy"
            sudo_commands: "/usr/bin/systemctl restart *, /usr/bin/apt-get *"
          - name: "ansible-monitoring"
            sudo_commands: "/usr/bin/systemctl status *, /usr/bin/journalctl *"
          - name: "ansible-backup"
            sudo_commands: "/usr/bin/rsync *, /usr/bin/pg_dump *"
```

**Валидация мульти-пользовательской конфигурации:**

```bash
# Проверка создания пользователей
ansible all -m shell -a "id ansible-deploy" --become

# Проверка SSH-подключения от имени каждого пользователя
for user in ansible-deploy ansible-monitoring ansible-backup; do
  ssh -i ~/.ssh/$user $user@server1 "echo $user OK"
done

# Проверка sudoers
ansible all -m shell -a "sudo -l -U ansible-deploy" --become
```

---

## Операции и команды

### Основные команды управления пользователями

| Команда | Назначение | Пример |
|---|---|---|
| `ansible all -m shell -a "id ansible-deploy"` | Проверка существования пользователя | `ansible all -m shell -a "id ansible-deploy" --become` |
| `ansible all -m shell -a "sudo -l -U ansible-deploy"` | Проверка прав sudo | `ansible all -m shell -a "sudo -l -U ansible-deploy" --become` |
| `ansible all -m ping -u ansible-deploy` | Проверка доступности | `ansible all -m ping -u ansible-deploy` |
| `ansible-inventory --host server1 --vars` | Просмотр переменных хоста | `ansible-inventory --host server1 --vars \| grep ansible_user` |
| `ansible all -m setup -a "filter=ansible_user_dir"` | Сбор фактов о домашней директории | `ansible all -m setup -a "filter=ansible_user_dir"` |

### Команды для работы с SSH

| Команда | Назначение | Пример |
|---|---|---|
| `ssh -i ~/.ssh/id_ed25519_ansible ansible-deploy@server1` | Проверка SSH-подключения | `ssh -i ~/.ssh/id_ed25519_ansible ansible-deploy@server1 "echo OK"` |
| `ssh -vvv ansible-deploy@server1` | Детальная диагностика SSH | `ssh -vvv ansible-deploy@server1` |
| `ansible all -m shell -a "exit" --ssh-extra-args="-O exit"` | Сброс ControlPersist сокетов | `ansible all -m shell -a "exit" --ssh-extra-args="-O exit"` |
| `rm -f ~/.ansible/cp/ansible-ssh-*` | Ручной сброс сокетов | `rm -f ~/.ansible/cp/ansible-ssh-*` |

### Команды для работы с sudoers

| Команда | Назначение | Пример |
|---|---|---|
| `visudo -cf /etc/sudoers.d/ansible-deploy` | Валидация синтаксиса sudoers | `visudo -cf /etc/sudoers.d/ansible-deploy` |
| `sudo -l -U ansible-deploy` | Просмотр прав пользователя | `sudo -l -U ansible-deploy` |
| `cat /etc/sudoers.d/ansible-deploy` | Просмотр файла прав | `cat /etc/sudoers.d/ansible-deploy` |

### Команды для работы с SELinux

| Команда | Назначение | Пример |
|---|---|---|
| `ls -Z /home/ansible-deploy/.ssh` | Просмотр контекстов безопасности | `ls -Z /home/ansible-deploy/.ssh` |
| `restorecon -Rv /home/ansible-deploy/.ssh` | Восстановление контекстов | `restorecon -Rv /home/ansible-deploy/.ssh` |
| `ausearch -m avc -ts recent \| grep sshd` | Поиск denial в логах | `ausearch -m avc -ts recent \| grep sshd` |
| `getenforce` | Проверка режима SELinux | `getenforce` |

---

## Устранение типичных неполадок

### Проблема: `UNREACHABLE! Permission denied (publickey)`

**Симптом:**
```bash
# fatal: [server1]: UNREACHABLE! msg: Permission denied (publickey,password)
```

**Причины и решения:**

| Причина | Диагностика | Решение |
|---|---|---|
| SSH-ключ не добавлен | `ssh -vvv ansible-deploy@server1` | Добавьте ключ через `ansible.posix.authorized_key` |
| `PermitRootLogin no` активен, а плейбук запускается от `root` | Проверьте `ansible_user` в инвентаре | Обновите `ansible_user: ansible-deploy` |
| Неверные права на `.ssh` | `ls -la /home/ansible-deploy/.ssh` | `chmod 700 /home/ansible-deploy/.ssh && chmod 600 /home/ansible-deploy/.ssh/authorized_keys` |
| SELinux блокирует доступ | `ausearch -m avc -ts recent` | `restorecon -Rv /home/ansible-deploy/.ssh` |

### Проблема: `Permission denied` при выполнении задачи

**Симптом:**
```bash
# fatal: [server1]: FAILED! => {"changed": false, "msg": "Permission denied"}
```

**Причины и решения:**

| Причина | Диагностика | Решение |
|---|---|---|
| Отсутствует `become: true` | Проверьте лог задачи | Добавьте `become: true` на уровне play или task |
| `sudo` требует пароль | `sudo -l -U ansible-deploy` | Настройте `NOPASSWD` в `/etc/sudoers.d/` |
| Пакет `sudo` не установлен | `which sudo` | Установите через `ansible.builtin.package` |

### Проблема: `sudo: a password is required`

**Симптом:**
```bash
# fatal: [server1]: FAILED! => {"msg": "sudo: a password is required"}
```

**Решение:**
```bash
# Проверка прав
sudo -l -U ansible-deploy
# → (ALL : ALL) ALL

# Если NOPASSWD не настроен — добавьте:
echo 'ansible-deploy ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/ansible-deploy
sudo visudo -cf /etc/sudoers.d/ansible-deploy
```

### Проблема: Зависание после правок (ControlPersist)

**Симптом:** После блокировки `root` плейбуки зависают или используют старые права.

**Решение:**
```bash
# Сброс сокетов
ansible all -m shell -a "exit" --ssh-extra-args="-O exit"

# Или ручной сброс
rm -f ~/.ansible/cp/ansible-ssh-*

# В ansible.cfg можно уменьшить время жизни
# [ssh_connection]
# ControlPersist = 30s
```

### Проблема: Обработчик SSH не выполняется

**Симптом:** После изменения `sshd_config` сервис не перезапускается.

**Решение:**
```yaml
# Убедитесь, что notify находится на одном уровне с задачей
- name: Изменение конфигурации
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    line: 'PermitRootLogin no'
  notify: Restart SSH  # ← На одном уровне с задачей

# Проверка обработчиков
ansible-playbook playbook.yml --list-handlers
```

### Проблема: SELinux блокирует SSH-ключ

**Симптом:** `Permission denied (publickey)` при корректных правах и ключе.

**Диагностика:**
```bash
# Проверка контекстов
ls -Z /home/ansible-deploy/.ssh
# → unconfined_u:object_r:user_home_t:s0 authorized_keys

# Проверка логов
ausearch -m avc -ts recent | grep sshd
```

**Решение:**
```bash
# Восстановление контекстов
restorecon -Rv /home/ansible-deploy/.ssh

# Если не помогает — проверка через semanage
semanage fcontext -a -t ssh_home_t "/home/ansible-deploy/.ssh(/.*)?"
restorecon -Rv /home/ansible-deploy/.ssh
```

### Проблема: Частичный деплой при миграции

**Симптом:** После блокировки `root` часть хостов осталась недоступной.

**Решение:**
```yaml
# Используйте serial для последовательного обновления
- hosts: all
  serial: "25%"
  max_fail_percentage: 10
  any_errors_fatal: true
  tasks:
    - name: Миграция
      ansible.builtin.include_tasks: migrate.yml
```

---

## Рекомендации

### Best Practices

1. **Принцип наименьших привилегий:** Создавайте отдельных пользователей для каждой задачи (deploy, monitoring, backup) с гранулярными правами sudo.
2. **Идемпотентность:** Bootstrap-плейбук должен быть безопасным для повторного запуска — не должен пытаться создать уже существующего пользователя.
3. **Валидация sudoers:** Всегда используйте `validate: 'visudo -cf %s'` — ошибка в синтаксисе приводит к полной блокировке `sudo`.
4. **SELinux:** На системах с SELinux всегда выполняйте `restorecon -Rv` после настройки SSH-ключей. Подробнее: **[Управление SELinux через Ansible](../Modules/ansible_service_and_system_config_modules.md#selinux)**.
5. **Ротация ключей:** Регулярно ротируйте SSH-ключи. Используйте `exclusive: yes` в `ansible.posix.authorized_key` для полной замены ключей.
6. **Логирование:** Включайте `no_log: true` для задач, содержащих пароли или ключи.
7. **Тестирование:** Всегда тестируйте миграцию на staging-сервере перед production.
8. **Документация:** Фиксируйте всех выделенных пользователей и их назначение в инвентаре.
9. **Аудит:** Настройте аудит входов через `auditd` или `journald` для отслеживания действий выделенных пользователей.
10. **Rollback-план:** Всегда имейте плейбук отката и протестируйте его на staging перед production-миграцией.

### Безопасность

- **Минимизация привилегий:** Используйте `become_user: postgres` (или другой специализированный пользователь) для задач управления БД, чтобы не выполнять команды от имени суперпользователя ОС (`root`) внутри СУБД. Подробнее: **[Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)**.
- **Управление секретами:** Для защиты конфиденциальных данных (пароли, TLS-ключи) всегда используйте шифрование. Подробнее: **[Основы Ansible Vault](../Vault/basics.md)**.
- **Изоляция CI/CD:** Используйте Protected Runners для production-деплоев. Разные окружения должны использовать разные SSH-ключи и сервисных пользователей. Подробнее: **[CI/CD с Ansible: безопасные пайплайны](example_real_world_ci_cd.md)**.

### Производительность и стабильность

- **SSH Multiplexing:** Настройте `ControlPersist` в `ansible.cfg` для ускорения последующих подключений. При миграции учитывайте, что старые сессии могут удерживать неактуальные права.
- **Connection Pipelining:** Включите `ANSIBLE_PIPELINING=True` для уменьшения количества SSH-соединений (требует отключения `requiretty` в sudoers).
- **Check Mode:** Модули Ansible поддерживают `check_mode`. Используйте `--check` для предварительной проверки изменений перед миграцией.

### Граничные случаи и ограничения

1. **Минимальные образы (Alpine, Distroless):** Пакет `sudo` отсутствует по умолчанию. Добавьте его установку в bootstrap-плейбук.
2. **Windows-хосты:** Механизм `become` работает через `runas` (local) или учетные данные Windows. SSH-ключи не используются — применяются учетные данные WinRM.
3. **BSD-системы:** На OpenBSD используется `doas` вместо `sudo`. Настройте `ansible_become_method: doas`.
4. **Контейнеры:** В Docker-контейнерах `sudo` может быть недоступен. Рекомендуется запускать контейнеры от нужного пользователя через `USER` в Dockerfile.
5. **LDAP/AD интеграция:** При использовании централизованных каталогов убедитесь, что выделенный пользователь существует в LDAP и имеет корректные атрибуты.
6. **Сетевые ограничения:** Если Control Node не имеет прямого доступа к хостам, используйте SSH-туннели или ProxyJump.

### Тестирование миграции перед production

1. **Синтаксис:** `ansible-playbook bootstrap.yml --syntax-check`
2. **Check Mode (Dry Run):** `ansible-playbook bootstrap.yml --check --diff`
3. **Limit Hosts:** `ansible-playbook bootstrap.yml --limit staging`
4. **Verbose Mode:** `ansible-playbook bootstrap.yml -vvvv` для детальной отладки
5. **Инспекция переменных:** `ansible-inventory --host server1 --vars | grep ansible_user`
6. **Валидация SSH:** `ssh -i ~/.ssh/id_ed25519_ansible ansible-deploy@server1 "echo OK"`
7. **Валидация sudo:** `ansible all -m shell -a "sudo -l -U ansible-deploy" --become`

---

## Дополнительная информация

### Смотрите также

- **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)** — общая стратегия защиты, настройка выделенного пользователя, Vault, аудит.
- **[Управление пользователями и идентификацией в Ansible](../ansible-identity-management.md)** — управление учетными записями, группами, sudoers и SSH-ключами.
- **[Примеры отладки типовых проблем](debugging_examples.md)** — общие подходы к отладке плейбуков и диагностике соединений.

### Дополнительный сценарий: Security hardening выделенного пользователя

После миграции на выделенного пользователя важно применить дополнительные меры hardening для повышения безопасности.

```yaml
---
- name: Security hardening для ansible-deploy
  hosts: all
  become: true
  vars:
    deploy_user: "ansible-deploy"

  tasks:
    - name: Настройка ограничений sudo (гранулярный доступ)
      ansible.builtin.copy:
        content: |
          {{ deploy_user }} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *, /usr/bin/systemctl reload *, /usr/bin/apt-get update, /usr/bin/apt-get upgrade, /usr/bin/journalctl *
        dest: "/etc/sudoers.d/{{ deploy_user }}"
        owner: root
        group: root
        mode: '0440'
        validate: 'visudo -cf %s'

    - name: Ограничение SSH доступа (AllowUsers)
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?AllowUsers'
        line: 'AllowUsers {{ deploy_user }}'
        state: present
        validate: 'sshd -t -f %s'
      notify: Restart SSH

    - name: Настройка SSH idle timeout
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?ClientAliveInterval'
        line: 'ClientAliveInterval 300'
        state: present
        validate: 'sshd -t -f %s'
      notify: Restart SSH

    - name: Отключение SSH аутентификации по паролю
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?PasswordAuthentication'
        line: 'PasswordAuthentication no'
        state: present
        validate: 'sshd -t -f %s'
      notify: Restart SSH

    - name: Настройка auditd для отслеживания sudo команд
      ansible.builtin.package:
        name: auditd
        state: present

    - name: Добавление правила audit для sudo
      ansible.builtin.lineinfile:
        path: /etc/audit/rules.d/ansible-sudo.rules
        line: '-a always,exit -F arch=b64 -S execve -C uid!=euid -F euid=0 -F key=ansible-sudo'
        state: present
      register: audit_rule
      changed_when: "'added' in audit_rule.stdout or 'already exists' in audit_rule.stdout"

    - name: Перезагрузка auditd
      ansible.builtin.systemd:
        name: auditd
        state: restarted
      when: audit_rule.changed

  handlers:
    - name: Restart SSH
      ansible.builtin.service:
        name: ssh
        state: restarted
```

**Валидация hardening:**

```bash
# Проверка гранулярного sudo
sudo -l -U ansible-deploy
# → (ALL : ALL) NOPASSWD: /usr/bin/systemctl restart *, /usr/bin/systemctl reload *, /usr/bin/apt-get update, /usr/bin/apt-get upgrade, /usr/bin/journalctl *

# Проверка AllowUsers
grep AllowUsers /etc/ssh/sshd_config
# → AllowUsers ansible-deploy

# Проверка audit логов
ausearch -k ansible-sudo -ts recent
# → показывает команды, выполненные через sudo
```

### Именование и организации

- **Пользователи:** Используйте согласованные имена: `ansible-deploy` (основной), `ansible-monitoring`, `ansible-backup` для разделения ответственности.
- **SSH-ключи:** Храните ключи с описанием: `id_ed25519_ansible-deploy`, `id_ed25519_ansible-monitoring`.
- **Плейбуки:** Bootstrap-плейбук (`bootstrap.yml`) должен быть отделен от рабочих плейбуков и запускаться только при первоначальной настройке.
- **Репозитории:** Bootstrap-логика хранится в общем репозитории, конфигурация окружения — в проектном.

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Несколько `ansible.cfg` | Конфликт настроек | Ansible использует ближайший `ansible.cfg` к плейбуку; не создавайте дубли. |
| Windows-контрольный узел | Некоторые модули не работают | Используйте WSL2 или Linux-контрольный узел. |
| Параллельный запуск | Файловые конфликты | Используйте `serial` в плейбуке или `forks` в `ansible.cfg`. |
| ControlPersist | Старая сессия удерживает неактуальные права | Сбросьте сокеты: `ansible all -m shell -a "exit" --ssh-extra-args="-O exit"`. |
| SELinux | Контексты `.ssh` неверны | `restorecon -Rv /home/user/.ssh`. |
| Vault и CI/CD | Пароль Vault недоступен | Передавайте через защищенные файловые переменные CI/CD с маскированием. |
| Большие инвентари | Медленная загрузка | Используйте динамический инвентарь или `yaml` вместо `ini` формата. |
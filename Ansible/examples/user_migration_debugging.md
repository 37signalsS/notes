# Отладка миграции на выделенного пользователя в Ansible

## Определения

**Миграция на выделенного пользователя** — архитектурный процесс перехода от запуска плейбуков от имени суперпользователя `root` к использованию отдельной системной учетной записи (например, `ansible-deploy`) с ограниченными привилегиями и механизмом `sudo` (substitute user do). Это критическая мера безопасности, требующая согласованной настройки SSH (Secure Shell) и прав доступа.

**Privilege Escalation (повышение привилегий)** — встроенный механизм Ansible (директива `become`), позволяющий выполнять задачи от имени другого пользователя (обычно `root`) после успешного первоначального SSH-подключения от имени непривилегированного пользователя.

**`become`** — директива уровня плейбука или задачи, включающая механизм повышения привилегий. Принимает логическое значение `true`/`false`. По умолчанию `false`.

**`become_method`** — параметр, определяющий утилиту для повышения привилегий. Допустимые значения: `sudo` (по умолчанию), `su`, `pbrun`, `pfexec`, `doas`, `ksu`. На OpenBSD рекомендуется `doas`.

**`become_user`** — целевой пользователь, от имени которого выполняется команда после повышения привилегий (по умолчанию `root`). Позволяет выполнять задачи от имени любого пользователя, а не только суперпользователя.

**`ansible_user`** — переменная инвентаря, определяющая имя пользователя для первоначального SSH-подключения к управляемому хосту. Заменяет использование флага `-u` в командной строке.

**`ansible_become`** — переменная инвентаря, эквивалент директивы `become: true` на уровне плейбука. Позволяет глобально включить повышение привилегий для всех задач.

**`sudoers`** — конфигурационный файл (`/etc/sudoers` или файлы в `/etc/sudoers.d/`), определяющий правила доступа к `sudo`. Управляется утилитой `visudo`. Ошибка в синтаксисе приводит к полной блокировке механизма `sudo`.

**`NOPASSWD`** — директива в конфигурации `sudoers`, позволяющая выполнять команды от имени суперпользователя без запроса пароля. Критически важна для автоматизации Ansible, так как предотвращает зависание пайплайна на запросе ввода пароля.

**`visudo`** — утилита безопасного редактирования файла `sudoers`. Обязательно проверяет синтаксис перед сохранением, предотвращая блокировку `sudo` из-за синтаксических ошибок.

**`ControlPersist` (SSH Multiplexing)** — механизмreuse SSH-соединений для ускорения последующих подключений. Соединения кэшируются в сокет-файле и переиспользуются. Может вызывать проблемы при смене прав доступа, так как старая сессия удерживает соединение с неактуальными правами.

**SELinux (Security-Enhanced Linux)** — механизм强制ного контроля доступа (MAC) в ядре Linux. На системах с SELinux (RHEL, CentOS, Fedora) контексты безопасности директории `.ssh` должны быть корректными, иначе SSH-сервер отклонит ключ даже при правильном `authorized_keys`.

**`no_log`** — параметр задачи Ansible, предотвращающий запись чувствительных данных (пароли, ключи, токены) в логи и вывод консоли. Устанавливается как `no_log: true` на уровне задачи.

## Базовые концепции

### Ключевые требования для успешной миграции

Чтобы миграция прошла без потери доступа к серверу ("lockout"), необходимо строго соблюдать последовательность:

1.  **Создание пользователя**: Пользователь должен существовать в ОС, иметь домашнюю директорию и корректную оболочку (shell).
2.  **Доступ по SSH**: Контрольный узел должен иметь возможность подключиться по SSH от имени нового пользователя. Публичный ключ должен быть добавлен в `~/.ssh/authorized_keys`.
3.  **SELinux и права**: На системах с SELinux (RHEL/CentOS) контексты безопасности директории `.ssh` должны быть корректными, иначе SSH-сервер отклонит ключ.
4.  **Привилегии sudo**: Пользователь должен иметь права на выполнение команд от имени суперпользователя. Для автоматизации рекомендуется настраивать беспарольный доступ (`NOPASSWD`). Пакет `sudo` должен быть установлен.
5.  **Блокировка root**: Только после верификации пп. 1-4 можно отключать `PermitRootLogin` в конфигурации SSH-сервера.

### Жизненный цикл SSH-ключей

При миграции на выделенного пользователя необходимо правильно управлять SSH-ключами:

1. **Генерация ключей**: Используйте Ed25519 (современный стандарт) или RSA 4096 бит:
   ```bash
   ssh-keygen -t ed25519 -C "ansible@control-node"
   ```
2. **Распространение публичного ключа**: Используйте модуль `ansible.posix.authorized_key` для добавления ключа в `~/.ssh/authorized_keys` нового пользователя.
3. **Очистка старых ключей**: Параметр `exclusive: yes` в `ansible.posix.authorized_key` удаляет все старые ключи, оставляя только указанные.
4. **Ротация ключей**: Регулярно обновляйте SSH-ключи. Старые ключи хостов хранятся в `~/.ssh/known_hosts` и должны обновляться через `ansible.builtin.known_hosts`.

### Конфигурация SELinux для SSH

На системах с включенным SELinux (RHEL, CentOS, Fedora, Rocky Linux) контексты безопасности критически важны:

```bash
# Просмотр текущего контекста
ls -Z /home/ansible-deploy/.ssh
# → system_u:object_r:user_home_t:s0 authorized_keys

# Восстановление контекстов (при ручных правках)
restorecon -Rv /home/ansible-deploy/.ssh
# → restoredcon /home/ansible-deploy/.ssh
# → restoredcon /home/ansible-deploy/.ssh/authorized_keys

# Проверка логов SELinux при проблемах
ausearch -m avc -ts recent | grep sshd
```

**Типичные ошибки SELinux:**

| Симптом | Причина | Решение |
|---|---|---|
| SSH-ключ отклоняется despite `authorized_keys` | Неверный контекст `authorized_keys` | `restorecon -Rv /home/user/.ssh` |
| `Permission denied (publickey)` в audit.log | SELinux запрещает чтение ключа | `setsebool -P ssh_sysadm_login on` (только для Trusted Endpoints) |

### Синтаксис sudoers для автоматизации

Конфигурация `sudoers` для пользователя Ansible:

```bash
# Формат: кто где=(от кого) что
ansible-deploy ALL=(ALL) NOPASSWD: ALL

# Гранулярный доступ (рекомендуется для production)
ansible-deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nginx, /usr/bin/apt-get update

# С выключенным mail (без почтовых уведомлений)
Defaults:ansible-deploy !mail_always
ansible-deploy ALL=(ALL) NOPASSWD: ALL
```

**Валидация синтаксиса (критически важно):**

```bash
# Всегда проверяйте синтаксис перед сохранением
visudo -cf /etc/sudoers.d/ansible-deploy
# → /etc/sudoers.d/ansible-deploy: parsed OK

# Если валидация прошла неуспешно — файл НЕ будет сохранен
# и sudo останется работоспособным
```

### Влияние ControlPersist на миграцию

Механизм SSH Multiplexing (ControlPersist) может вызывать проблемы при смене прав:

```bash
# Проверка активных сокетов
ps aux | grep ssh
# → ssh -o ControlPersist=600s -o ...
```

**Решение**: Сброс сокетов перед продолжением работы:

```bash
# Сброс через Ansible
ansible all -m shell -a "exit" --ssh-extra-args="-O exit"

# Или ручной сброс
rm -f ~/.ansible/cp/ansible-ssh-*
```

### Типовые ошибки и диагностика

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `UNREACHABLE! Permission denied (publickey)` | Ansible пытается войти как `root`, но `PermitRootLogin` уже отключен, либо для нового пользователя не добавлен SSH-ключ. | Проверить `ansible_user` в инвентаре. Убедиться, что публичный ключ добавлен в `authorized_keys` нового пользователя. |
| `Permission denied` (в логах задачи) | Задача требует прав суперпользователя (например, `apt`, `systemd`), но директива `become: true` отсутствует. | Добавить `become: true` на уровне сценария (play) или конкретной задачи. |
| `Missing sudo password` или зависание | Для пользователя не настроен `NOPASSWD` в `sudoers`, а пароль для `become` не передан. | Настроить конфигурацию в `/etc/sudoers.d/` (заканчивать файл новой строкой) или передать пароль через `--ask-become-pass`. |
| `sudo: command not found` | Пакет `sudo` не установлен в системе (характерно для минимальных образов Debian/Alpine). | Установить пакет `sudo` при последнем запуске от имени `root`. |
| Зависание (Timeout) после правок | Активен `ControlPersist` (SSH Multiplexing). Старая сессия удерживает соединение с неактуальными правами. | Сбросить сокеты: `ansible all -m shell -a "exit" --ssh-extra-args="-O exit"`. |

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
# → Результат: Пользователь создан, ключи добавлены, root заблокирован.
```

#### 2. Диагностика ошибки после изменений

Если попытаться запустить обычный плейбук от имени `root` после успешной миграции:

```bash
ansible-playbook -i inventory.ini app_deploy.yml -u root
# → fatal: [server1]: UNREACHABLE! msg: Permission denied (publickey,password)
```

**Диагноз:** SSH-сервер отвергает подключение, так как удаленный доступ для `root` (`PermitRootLogin no`) закрыт в `sshd_config`.

#### 3. Переход на новую конфигурацию (После миграции)

Теперь необходимо обновить конфигурацию проекта для использования нового пользователя и повышения привилегий.

**Обновление инвентаря `inventory.ini`:**

```ini
[production]
server1 ansible_host=192.168.1.10
# Указывать ansible_user здесь не обязательно, лучше вынести в group_vars
```

**Инспекция через `ansible-inventory`:**
Убедитесь, что переменные применились корректно:
```bash
ansible-inventory --host server1 --vars | grep ansible_user
```

**Настройка переменных (`group_vars/all.yml` или `ansible.cfg`):**

```yaml
---
# group_vars/all.yml
ansible_user: "ansible-deploy"
ansible_become: true
ansible_become_method: sudo
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

### Сценарий: Откат миграции (Rollback)

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
        key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"

  handlers:
    - name: Restart SSH
      ansible.builtin.service:
        name: ssh
        state: restarted
```

**Запуск отката:**

```bash
# Запуск от имени root (если еще доступен)
ansible-playbook -i inventory.ini rollback.yml -u root

# Или от имени ansible-deploy (если root уже заблокирован)
ansible-playbook -i inventory.ini rollback.yml -u ansible-deploy --ask-become-pass
```

### Сценарий: Миграция с поддержкой SELinux

На системах с SELinux (RHEL/CentOS/Fedora) миграция требует дополнительных шагов:

```yaml
---
- name: Миграция с поддержкой SELinux
  hosts: all
  become: false
  vars:
    deploy_user: "ansible-deploy"
    deploy_pub_key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"

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

### Сценарий: Мульти-пользовательская миграция (разные роли)

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

## Дополнительная информация

### Лучшие практики

1. **Принцип минимальных привилегий**: Создавайте отдельных пользователей для каждой задачи (deploy, monitoring, backup) с гранулярными правами sudo.
2. **Идемпотентность**: Bootstrap-плейбук должен быть безопасным для повторного запуска — не должен пытаться создать уже существующего пользователя.
3. **Валидация sudoers**: Всегда используйте `validate: 'visudo -cf %s'` — ошибка в синтаксисе приводит к полной блокировке `sudo`.
4. **SELinux**: На системах с SELinux всегда выполняйте `restorecon -Rv` после настройки SSH-ключей.
5. **Ротация ключей**: Регулярно ротируйте SSH-ключи. Используйте `exclusive: yes` в `ansible.posix.authorized_key` для полной замены ключей.
6. **Логирование**: Включайте `no_log: true` для задач, содержащих пароли или ключи.
7. **Тестирование**: Всегда тестируйте миграцию на staging-сервере перед production.
8. **Документация**: Фиксируйте всех выделенных пользователей и их назначение в инвентаре.
9. **Мониторинг**: Настройте аудит входов через `auditd` или `journald` для отслеживания действий выделенных пользователей.

### Граничные случаи и ограничения

1. **Минимальные образы (Docker, Alpine)**: Пакет `sudo` отсутствует по умолчанию. Добавьте его установку в bootstrap-плейбук.
2. **Windows-хосты**: Механизм `become` работает через `runas` (local) или凭据 Windows. SSH-ключи не используются — применяются凭据 WinRM.
3. **BSD-системы**: На OpenBSD используется `doas` вместо `sudo`. Настройте `ansible_become_method: doas`.
4. **Контейнеры**: В Docker-контейнерах `sudo` может быть недоступен. Рекомендуется запускать контейнеры от нужного пользователя через `USER` в Dockerfile.
5. **LDAP/AD интеграция**: При использовании централизованных каталогов убедитесь, что выделенный пользователь существует в LDAP и имеет корректные атрибуты.
6. **Сетевые ограничения**: Если Control Node не имеет прямого доступа к хостам, используйте SSH-туннели или ProxyJump.

### Типичные ошибки и устранение неполадок

| Проблема | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `UNREACHABLE! Permission denied (publickey)` | SSH-ключ не добавлен или `PermitRootLogin no` | `ssh -vvv user@host` для деталей | Добавьте ключ в `authorized_keys`, проверьте `sshd_config`. |
| `Missing sudo password` | `NOPASSWD` не настроен | `sudo -l -U user` | Настройте `/etc/sudoers.d/` с `NOPASSWD: ALL`. |
| `sudo: command not found` | Пакет `sudo` не установлен | `which sudo` | Установите `sudo` через `apt`/`yum`. |
| `Permission denied` (задача) | Отсутствует `become: true` | Проверьте лог задачи | Добавьте `become: true` на уровне play или task. |
| Зависание после правок | Активен `ControlPersist` | `ps aux \| grep ssh` | Сбросьте сокеты: `rm -f ~/.ansible/cp/ansible-ssh-*`. |
| SSH-ключ отклоняется (SELinux) | Неверный контекст `.ssh` | `ls -Z ~/.ssh` | `restorecon -Rv /home/user/.ssh`. |
| `sudo: a password is required` | Пароль не передан через `--ask-become-pass` | Проверьте переменную | Используйте `--ask-become-pass` или `ansible_become_password`. |
| `Connection reset by peer` | Сервис `sshd` перезапущен во время задачи | Проверьте `sshd` лог | Добавьте `delay` перед перезапуском SSH. |

### Тестирование миграции перед production

1. **Синтаксис**: `ansible-playbook bootstrap.yml --syntax-check`
2. **Check Mode (Dry Run)**: `ansible-playbook bootstrap.yml --check --diff`
3. **Limit Hosts**: `ansible-playbook bootstrap.yml --limit staging`
4. **Verbose Mode**: `ansible-playbook bootstrap.yml -vvv` для детальной отладки
5. **Инспекция переменных**: `ansible-inventory --host server1 --vars | grep ansible_user`
6. **Валидация SSH**: `ssh -i ~/.ssh/id_rsa ansible-deploy@server1 "echo OK"`
7. **Валидация sudo**: `ansible all -m shell -a "sudo -l -U ansible-deploy" --become`

## Смотрите также

- [Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)
- [Модули управления пользователями и безопасностью](../Modules/ansible_security_and_user_management_modules.md)
- [Основы Ansible Vault](../Vault/basics.md)
- [Примеры отладки типовых проблем](debugging_examples.md)
- [Управление политиками паролей в Linux (chage)](../../Linux/SystemAdministration/Users/password_policy_chage.md)
- [Управление пользователями и группами в Linux](../../Linux/SystemAdministration/users_management.md)
- [Автоматизация управления идентификацией (Identity Management)](../ansible-identity-management.md)
- [Закалка ОС и базовая безопасность](../ansible-os-hardening.md)
- [Типовая структура проекта Ansible](example_project_layout.md)
- [CI/CD с Ansible: безопасные пайплайны](example_real_world_ci_cd.md)

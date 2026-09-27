# Автоматизация управления идентификацией (Ansible Identity Management)

## Определения

**Identity Management (IdM)** — централизованная система управления жизненным циклом учетных записей, групп, полномочий и методов аутентификации в распределенной инфраструктуре.

**Ansible Identity Management** — использование декларативной автоматизации для развертывания IdM-решений, интеграции конечных узлов (Enrollment) и управления объектами каталогов через специализированные коллекции и API.

**Identity Provider (IdP)** — сервис, хранящий цифровые идентификаторы и подтверждающий подлинность субъектов (например, Active Directory, FreeIPA, Keycloak, OpenLDAP).

**Enrollment (Ввод в домен)** — процесс регистрации управляемого узла в IdM-системе с получением доверенных учетных данных (Keytab, сертификаты) и настройкой клиентских служб (SSSD, PAM).

**Kerberos** — сетевой протокол аутентификации с использованием тикетов (tickets), позволяющий подтверждать подлинность без передачи пароля по сети.

**SSSD (System Security Services Daemon)** — демон, предоставляющий единый интерфейс для доступа к каталогам (LDAP, FreeIPA, AD) и кэширования учетных данных.

**realmd** — служба Linux, упрощающая подключение хоста к домену Active Directory или FreeIPA.

**HBAC (Host-Based Access Control)** — правила контроля доступа, определяющие, какие пользователи или группы могут подключаться к конкретным хостам.

**SUDO-правило** — запись в конфигурации sudo, определяющая, какой пользователь или группа может выполнять какие команды от имени суперпользователя.

---

## Основные концепции

### 1. Архитектурные подходы к автоматизации

1.  **Управление клиентами (Client Side):**
    - Автоматизация установки `sssd`, `realmd`, `adcli` или специализированных агентов.
    - Настройка механизмов доверия (Kerberos, PAM stack).
    - Использование **System Roles** (`fedora.linux_system_roles.ad_integration`) для минимизации кастомного кода.
2.  **Управление объектами (Server Side / Directory Management):**
    - Создание и модификация пользователей, групп, OU прямо в каталоге.
    - Управление политиками доступа (HBAC, SUDO, RBAC).
    - Использование протоколов LDAP/LDAPS или нативных API (WinRM для AD, REST/JSON-RPC для FreeIPA).
3.  **Федеративная идентификация (Modern IdM):**
    - Автоматизация настройки протоколов SAML 2.0, OIDC и механизмов SCIM для синхронизации пользователей между локальными системами.

### 2. Компоненты безопасности

-   **Zero Trust Enrollment:** Использование временных токенов (One-Time Passwords, OTP) или динамических Principal для ввода хостов в домен без раскрытия пароля администратора.
-   **Управление сертификатами:** Интеграция с PKI через протоколы ACME или SCEP для автоматической выдачи и обновления SSL/SSH-сертификатов хостов. Детали см. в [Управление сертификатами в Ansible](./ansible_certificate_management.md).
-   **MFA-контекст:** Настройка политик многофакторной аутентификации на уровне IdM через Ansible для критических сегментов сети.

### 3. Сравнение IdM-систем

| Критерий | Active Directory | FreeIPA / Red Hat IdM | Keycloak |
| :--- | :--- | :--- | :--- |
| **Протоколы** | LDAP/Kerberos/WinRM | LDAP/Kerberos/REST | OIDC/SAML/LDAP |
| **Ansible коллекция** | `microsoft.ad` | `freeipa.ansible_freeipa` | REST API (`ansible.builtin.uri`) |
| **Платформа** | Windows Server | RHEL/CentOS/Fedora | Кроссплатформенный |
| **Модель лицензирования** | CAL лицензии | Бесплатный (open source) | Бесплатный (open source) |
| **Управление Linux-хостами** | Через SSSD/realmd | Нативная интеграция | Через SAML/OIDC |
| **HBAC / SUDO** | Ограниченно (GPO) | Полная поддержка | Через клиентские приложения |
| **LDAP-каталог** | Да (AD DS) | Да (389 DS) | Да (встроенный) |
| **Высокая доступность** | Репликация AD | Репликация IPA | Кластер |

### 4. Жизненный цикл идентификации

```
Создание → Включение → Активность → Изменение → Блокировка → Удаление
   │           │            │            │            │            │
   ▼           ▼            ▼            ▼            ▼            ▼
useradd    passwd -u    last/login   usermod    passwd -l     userdel
(или       (активация   (мониторинг) (смена     (блокировка   (удаление
 IdP API)   аккаунта)                ролей)      аккаунта)     аккаунта)
```

### 5. Протоколы аутентификации

| Протокол | Описание | Использование в Ansible |
| :--- | :--- | :--- |
| **Kerberos** | Токен-based аутентификация без передачи пароля | `kinit`, keytab, настройка через connection plugins |
| **LDAP/LDAPS** | Протокол доступа к каталогу (порт 389/636) | `ansible.builtin.ldap`, `microsoft.ad.user` |
| **SAML 2.0** | Федеративная аутентификация (SSO) | Настройка через `community.general.saml` |
| **OIDC** | OpenID Connect (REST-based) | Интеграция с Keycloak |
| **SSH Keys** | Аутентификация по публичному ключу | `ansible.posix.authorized_key` |
| **Certificates** | X.509 сертификаты для аутентификации | `community.crypto.openssl_certificate` |
| **OTP** | Одноразовые пароли (TOTP/HOTP) | Ввод в домен через FreeIPA |

---

## Практические сценарии

### Предварительные требования

1.  **Ansible Control Node:** ansible-core >= 2.17, Python 3.9+
2.  **Коллекции:** установите требуемые коллекции (см. ниже).
3.  **Сетевая связность:** Control Node должен иметь доступ к доменным контроллерам или IdM-серверам по требуемым портам (LDAP 389/636, Kerberos 88, WinRM 5985/5986).
4.  **Учетные данные:** сервисные аккаунты с минимально необходимыми правами (делегирование, а не Domain Admin).
5.  **Синхронизация времени:** NTP/Chrony настроен на всех узлах (Kerberos требует расхождения не более 5 минут).
6.  **Ansible Vault:** секреты (пароли, keytab) хранятся в зашифрованных файлах.

```bash
# Установка необходимых коллекций
ansible-galaxy collection install microsoft.ad
ansible-galaxy collection install freeipa.ansible_freeipa
ansible-galaxy collection install ansible.posix
ansible-galaxy collection install ansible.controller
ansible-galaxy collection install community.general
```

### 1. Интеграция с Microsoft Active Directory

Современная автоматизация AD включает как настройку клиентов на Linux, так и управление объектами в самом домене.

#### Ввод Linux-хоста в AD (System Roles)

Использование системных ролей обеспечивает поддержку вендором и корректную настройку SSSD/Kerberos.

```yaml
- name: "Интеграция Linux-узла с Active Directory"
  hosts: linux_servers
  vars:
    ad_integration_realm: "CORP.EXAMPLE.COM"
    ad_integration_user: "join_svc_account"
    ad_integration_password: "{{ vault_ad_join_password }}"
    ad_integration_sssd_settings:
      - section: domain/CORP.EXAMPLE.COM
        option: ad_gpo_access_control
        value: "enforcing"
  roles:
    - fedora.linux_system_roles.ad_integration
```

#### Управление объектами через `microsoft.ad`

Для прямого управления AD с Linux-контроллера (через WinRM на один из DC).

```yaml
- name: "Управление структурой Active Directory"
  hosts: domain_controllers
  tasks:
    - name: "Создание подразделения (OU)"
      microsoft.ad.ou:
        name: "Servers"
        path: "DC=corp,DC=example,DC=com"
        state: present

    - name: "Создание доменной группы"
      microsoft.ad.group:
        name: "LinuxAdmins"
        scope: global
        category: security
        path: "OU=Servers,DC=corp,DC=example,DC=com"
        state: present

    - name: "Создание пользователя в AD"
      microsoft.ad.user:
        name: "jdoe"
        display_name: "John Doe"
        sam_account_name: "jdoe"
        upn: "jdoe@corp.example.com"
        path: "OU=Users,DC=corp,DC=example,DC=com"
        enabled: true
        password: "{{ vault_user_password }}"
        password_never_expires: false
        state: present

    - name: "Добавление пользователя в группу"
      microsoft.ad.group:
        name: "LinuxAdmins"
        members:
          - jdoe
        state: present
```

#### Управление GPO через `microsoft.ad`

```yaml
- name: "Настройка Group Policy"
  hosts: domain_controllers
  tasks:
    - name: "Создание GPO для Linux-серверов"
      microsoft.ad.gpo:
        name: "Linux Server Policy"
        domain: "corp.example.com"
        state: present

    - name: "Назначение GPO на OU"
      microsoft.ad.gpo_link:
        gpo: "Linux Server Policy"
        target_ou: "OU=Servers,DC=corp,DC=example,DC=com"
        state: present
```

### 2. Управление FreeIPA / Red Hat IdM

Для FreeIPA используется коллекция `freeipa.ansible_freeipa`, которая полностью покрывает API сервера.

#### Регистрация клиента с OTP (Безопасный метод)

```yaml
- name: "Безопасный ввод в домен FreeIPA"
  hosts: new_nodes
  become: true
  roles:
    - role: freeipa.ansible_freeipa.ipaclient
      state: present
      vars:
        ipaclient_domain: "ipa.example.com"
        ipaclient_realm: "IPA.EXAMPLE.COM"
        # Пароль администратора не передается на клиент
        ipaadmin_keytab: "/etc/krb5.keytab.admin"
        ipaclient_use_otp: yes
```

#### Управление политиками доступа (HBAC и SUDO)

```yaml
- name: "Настройка политик доступа во FreeIPA"
  hosts: ipaserver
  tasks:
    - name: "Создание правила HBAC"
      freeipa.ansible_freeipa.ipahbacrule:
        name: "allow_ssh_devs"
        usercategory: all
        hostgroup: "dev_servers"
        servicecategory: all
        state: present

    - name: "Создание централизованного правила SUDO"
      freeipa.ansible_freeipa.ipasudorule:
        name: "admins_all_privileges"
        group: "admins"
        hostcategory: all
        cmdcategory: all
        runasusercategory: all
        state: present

    - name: "Создание SUDO-правила для DevOps"
      freeipa.ansible_freeipa.ipasudorule:
        name: "devops_deploy"
        group: "devops"
        hostgroup: "production_servers"
        cmdallow:
          - /usr/bin/systemctl restart nginx
          - /usr/bin/docker pull *
          - /usr/local/bin/deploy.sh
        options:
          - "!authenticate"
        state: present
```

#### Управление пользователями FreeIPA

```yaml
- name: "Управление пользователями FreeIPA"
  hosts: ipaserver
  tasks:
    - name: "Создание пользователя"
      freeipa.ansible_freeipa.ipauser:
        name: "asmith"
        givenname: "Alice"
        sn: "Smith"
        mail:
          - "asmith@example.com"
        telephonenumber:
          - "+1234567890"
        departmentnumber: "IT"
        employeenumber: "1001"
        state: present

    - name: "Создание HBAC-правила для пользователя"
      freeipa.ansible_freeipa.ipahbacrule:
        name: "allow_asmith_admin"
        user:
          - asmith
        hostgroup:
          - admin_servers
        service:
          - sshd
        state: present
```

### 3. Локальное управление пользователями и группами

Для сценариев, где централизованная IdM недоступна или не нужна. Детали работы с модулями `user`, `group`, `authorized_key` см. в [Модули управления пользователями](./Modules/ansible_security_and_user_management_modules.md).

```yaml
- name: "Управление локальными пользователями"
  hosts: all
  become: true
  vars:
    users:
      - name: jdoe
        comment: "John Doe"
        groups: wheel,developers
        shell: /bin/bash
        ssh_key: "ssh-rsa AAAA..."
      - name: asmith
        comment: "Alice Smith"
        groups: developers
        shell: /bin/bash
        ssh_key: "ssh-rsa BBBB..."
    groups:
      - name: developers
        gid: 2000
      - name: admins
        gid: 2001
  tasks:
    - name: "Создание групп"
      ansible.builtin.group:
        name: "{{ item.name }}"
        gid: "{{ item.gid }}"
        state: present
      loop: "{{ groups }}"

    - name: "Создание пользователей"
      ansible.builtin.user:
        name: "{{ item.name }}"
        comment: "{{ item.comment }}"
        groups: "{{ item.groups }}"
        append: true
        shell: "{{ item.shell }}"
        state: present
      loop: "{{ users }}"

    - name: "Установка SSH-ключей"
      ansible.posix.authorized_key:
        user: "{{ item.name }}"
        key: "{{ item.ssh_key }}"
        state: present
      loop: "{{ users }}"
```

### 4. Управление SSH-ключами и сертификатами

#### Жизненный цикл SSH-ключей

```yaml
- name: "Управление SSH-ключами"
  hosts: all
  become: true
  tasks:
    - name: "Генерация SSH-ключей для сервисных аккаунтов"
      ansible.builtin.command:
        cmd: >
          ssh-keygen -t ed25519
          -f /home/service_user/.ssh/id_ed25519
          -N ""
          -C "service_user@$(hostname)"
        creates: /home/service_user/.ssh/id_ed25519

    - name: "Распространение публичных ключей"
      ansible.posix.authorized_key:
        user: "{{ item.user }}"
        key: "{{ item.key }}"
        state: present
        exclusive: false
      loop:
        - { user: "admin", key: "ssh-ed25519 AAAA..." }
        - { user: "deploy", key: "ssh-ed25519 BBBB..." }

    - name: "Отключение парольной аутентификации"
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: "^#?PasswordAuthentication"
        line: "PasswordAuthentication no"
      notify: restart sshd
```

#### SSH-сертификаты (Certificate Authority)

```yaml
- name: "Настройка SSH Certificate Authority"
  hosts: all
  tasks:
    - name: "Установка sshd с поддержкой сертификатов"
      ansible.builtin.package:
        name: openssh-server
        state: present

    - name: "Настройка Trusted CA для SSH-сертификатов"
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        line: "TrustedUserCAKeys /etc/ssh/ca_key.pub"
      notify: restart sshd
```

### 5. Управление sudoers

#### Локальное управление sudoers

Детали настройки sudoers через шаблоны и валидацию см. в [Модули управления пользователями](./Modules/ansible_security_and_user_management_modules.md).

```yaml
- name: "Настройка sudoers"
  hosts: all
  become: true
  tasks:
    - name: "Настройка группы wheel/sudo"
      ansible.builtin.group:
        name: "{{ sudo_group }}"
        state: present
      vars:
        sudo_group: "{{ 'wheel' if ansible_facts['os_family'] == 'RedHat' else 'sudo' }}"

    - name: "Добавление пользователей в sudoers"
      ansible.builtin.user:
        name: "{{ item.name }}"
        groups: "{{ sudo_group }}"
        append: true
      loop:
        - { name: jdoe }
        - { name: asmith }

    - name: "Настройка парольного sudo"
      ansible.builtin.lineinfile:
        path: "/etc/sudoers.d/{{ item.user }}"
        line: "{{ item.user }} {{ item.host }}=(root) {{ item.commands }}"
        create: true
        validate: /usr/sbin/visudo -csf %s
        mode: "0440"
      loop:
        - { user: "jdoe", host: "ALL", commands: "ALL" }
        - { user: "asmith", host: "ALL", commands: "/usr/bin/systemctl restart nginx, /usr/bin/docker *" }

    - name: "Настройка беспарольного sudo для service accounts"
      ansible.builtin.lineinfile:
        path: "/etc/sudoers.d/90-ansible-worker"
        line: "service_user ALL=(ALL) NOPASSWD: ALL"
        create: true
        validate: /usr/sbin/visudo -csf %s
        mode: "0440"
```

### 6. Audit и комплаенс

```yaml
- name: "Аудит учетных записей"
  hosts: all
  become: true
  tasks:
    - name: "Сбор информации об учетных записях"
      ansible.builtin.shell: |
        echo "=== Пользователи с UID 0 ==="
        awk -F: '$3 == 0 {print $1}' /etc/passwd
        echo "=== Пользователи без пароля ==="
        awk -F: '($2 == "" || $2 == "!") {print $1}' /etc/shadow
        echo "=== Пользователи с интерактивным shell ==="
        awk -F: '$7 != "/sbin/nologin" && $7 != "/bin/false" {print $1}' /etc/passwd
      register: audit_result
      changed_when: false

    - name: "Вывод результатов аудита"
      ansible.builtin.debug:
        var: audit_result.stdout_lines

    - name: "Проверка SSH-ключей"
      ansible.builtin.find:
        paths: /home
        patterns: "authorized_keys"
        recurse: true
      register: ssh_keys

    - name: "Отчет о найденных SSH-ключах"
      ansible.builtin.debug:
        msg: >
          Найдено {{ ssh_keys.files | length }} файлов authorized_keys
          в домашних каталогах
```

### 7. Управление доступом в Ansible Automation Platform (RBAC)

Автоматизация прав доступа внутри самого инструмента автоматизации.

```yaml
- name: "Настройка RBAC в Ansible Controller"
  hosts: localhost
  tasks:
    - name: "Создание команды и назначение ролей"
      ansible.controller.team:
        name: "Security Ops"
        organization: "Default"
        state: present

    - name: "Назначение прав на Inventory"
      ansible.controller.role:
        user: "jdoe"
        role: "admin"
        target_team: "Security Ops"
        inventory: "Production_Inventory"
        state: present

    - name: "Создание Credentials"
      ansible.controller.credential:
        name: "Production SSH Key"
        credential_type: "Machine"
        organization: "Default"
        inputs:
          ssh_key_data: "{{ vault_ssh_private_key }}"
        state: present

    - name: "Настройка Workflow с Approval"
      ansible.controller.workflow_job_template:
        name: "Production Deploy"
        organization: "Default"
        state: present
```

---

## Операции и команды

| Команда / Модуль | Назначение | Пример использования |
| :--- | :--- | :--- |
| `ansible-galaxy collection install` | Установка коллекций IdM | `ansible-galaxy collection install microsoft.ad` |
| `realm join` / `realm leave` | Ввод хоста в домен AD / выход | `realm join corp.example.com -U join_svc` |
| `ipa-client-install` | Регистрация клиента FreeIPA | `ipa-client-install --domain ipa.example.com --server ipa01.ipa.example.com` |
| `kinit` / `kdestroy` | Получение / уничтожение Kerberos-тикета | `kinit -k -t /etc/krb5.keytab $(hostname -f)` |
| `klist` | Просмотр текущих Kerberos-тикетов | `klist -kt /etc/krb5.keytab` |
| `sssctl domain-status` | Статус домена SSSD | `sssctl domain-status corp.example.com` |
| `sss_cache -E` | Очистка кэша SSSD | `sss_cache -E` |
| `realm list` / `realm discover` | Просмотр / обнаружение домена | `realm list` |
| `ldapsearch` | Поиск в LDAP-каталоге | `ldapsearch -x -H ldap://dc01.corp.example.com -b "dc=corp,dc=example,dc=com"` |
| `ipa user-show` / `ipa host-show` | Информация о пользователе / хосте FreeIPA | `ipa user-show asmith` |
| `ipa hbacrule-find` | Поиск HBAC-правил | `ipa hbacrule-find` |
| `visudo -csf` | Проверка синтаксиса sudoers | `visudo -csf /etc/sudoers.d/custom` |
| `ssh-keygen` | Генерация SSH-ключей | `ssh-keygen -t ed25519 -f /home/user/.ssh/id_ed25519` |
| `ansible.builtin.user` | Управление локальными пользователями | `ansible.builtin.user: name=jdoe state=present` |
| `ansible.builtin.group` | Управление локальными группами | `ansible.builtin.group: name=developers state=present` |
| `ansible.posix.authorized_key` | Управление SSH-ключами | `ansible.posix.authorized_key: user=jdoe key="{{ lookup('file', 'jdoe.pub') }}"` |
| `ansible.builtin.template` + `validate` | Безопасное управление sudoers | `validate: '/usr/sbin/visudo -cf %s'` |
| `ansible.builtin.ldap` | LDAP-запросы | `ansible.builtin.ldap: dn="..." objectClass=person` |

---

## Диагностика и устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `kinit: Clock skew` | Расхождение времени > 5 минут | Настройте NTP/Chrony на обоих узлах |
| `realm join: Authentication failed` | Неверные учетные данные или OU | Проверьте логин/пароль и путь к OU |
| `SSSD: No such entry` | Кэш устарел или DNS не резолвится | Очистите кэш `sss_cache -E`, проверьте DNS |
| `sudo: unknown user` | Пользователь не существует в системе | Проверьте `getent passwd username` |
| `ldap_bind: Invalid credentials` | Неверный DN или пароль | Проверьте bind DN и пароль в конфиге |
| `authorized_key: key not found` | SSH-ключ не найден или неверный формат | Проверьте путь и формат ключа |
| `useradd: user already exists` | Пользователь уже создан | Проверьте `id username` и state: present |
| `No such file: /etc/shadow` | Нет прав на чтение | Убедитесь что become: true |
| `microsoft.ad.user: WinRM error` | Нет доступа к DC через WinRM | Проверьте WinRM-конфигурацию и сертификаты |
| `ipauser: already exists` | Пользователь уже существует в FreeIPA | Проверьте `ipa user-show name` |
| `realm: command not found` | `realmd` не установлен | Установите `realmd` и зависимости |
| `ipa: command not found` | FreeIPA клиент не установлен | Установите пакет `freeipa-client` |
| `sssctl: command not found` | SSSD не установлен или не запущен | Установите/запустите `sssd` |
| `visudo: syntax error` | Ошибка в синтаксисе sudoers | Проверьте файл через `visudo -cf /etc/sudoers.d/file` |

---

## Рекомендации и лучшие практики

1.  **Identity as Code:** Храните определения пользователей и групп в Git (YAML), используя Ansible Vault для паролей и Keytab-файлов.
2.  **Минимизация привилегий:** Используйте технические учетные записи с делегированными правами (например, право только на Join в конкретную OU) вместо `Domain Admin`.
3.  **Валидация (Post-enrollment):** Всегда проверяйте результат интеграции:
    ```yaml
    - name: "Верификация Kerberos-аутентификации"
      ansible.builtin.shell: kinit -k -t /etc/krb5.keytab $(hostname -f)
      changed_when: false
    ```
4.  **Синхронизация времени:** Kerberos требует расхождения не более 5 минут. Перед вводом в домен всегда запускайте роль настройки NTP/Chrony.
5.  **Ротация секретов:** Регулярно обновляйте пароли сервисных аккаунтов, keytab-файлы и SSH-ключи. Используйте `ansible.builtin.cron` для автоматической ротации.
6.  **Аудит доступа:** Ведите журнал всех операций управления идентификацией. Используйте callback-плагины для отправки событий в SIEM.
7.  **System Roles вместо кастомного кода:** Для стандартных сценариев (AD integration, ipaclient) используйте системные роли. Они поддерживаются вендором и покрывают edge cases.
8.  **Тестирование в изолированной среде:** Все плейбуки тестируйте в стенде перед применением к продакшену. Особенно критично для операций с GPO и глобальными политиками.
9.  **Throttle и serial:** При массовом развертывании используйте `throttle` и `serial` для защиты LDAP/SSSD от перегрузки.
10. **Документирование политик:** Каждое правило sudo, HBAC или RBAC должно иметь описание в коде (name, comment) и ссылку на тикет/политику.

---

## Дополнительная информация

### Диагностические команды

```bash
# Проверка Kerberos-аутентификации
klist -kt /etc/krb5.keytab
kinit -k -t /etc/krb5.keytab $(hostname -f)

# Проверка SSSD
sssctl domain-status corp.example.com
sss_cache -E  # Очистка кэша

# Проверка membership в домене
realm list
realm discover corp.example.com

# Проверка LDAP-каталога
ldapsearch -x -H ldap://dc01.corp.example.com \
  -D "cn=admin,dc=corp,dc=example,dc=com" \
  -W -b "dc=corp,dc=example,dc=com" \
  "(objectClass=user)" sAMAccountName

# Проверка sudoers
visudo -csf /etc/sudoers.d/custom
sudo -l -U username

# Проверка SSH-конфигурации
sshd -T | grep -E "^(passwordauthentication|pubkeyauthentication)"

# Проверка FreeIPA
ipa user-show username
ipa host-show $(hostname -f)
ipa hbacrule-find
```

### Смотрите также

- **[Модули управления пользователями](./Modules/ansible_security_and_user_management_modules.md)** — базовые модули `user`, `group`, `authorized_key`, `sudoers` для локальных систем.
- **[Интеграция SSSD с Active Directory](../Linux/SystemAdministration/Users/LDAP_SSSD/ad_integration.md)** — системные аспекты и отладка.
- **[Обзор FreeIPA](../LDAP/FreeIPA/freeipa_overview.md)** — архитектура IdM-решения.

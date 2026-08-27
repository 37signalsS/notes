# Автоматизация управления идентификацией (Ansible Identity Management)

## Определения

**Identity Management (IdM)** — централизованная система управления жизненным циклом учетных записей, групп, полномочий и методов аутентификации в распределенной инфраструктуре.

**Ansible Identity Management** — использование декларативной автоматизации для развертывания IdM-решений, интеграции конечных узлов (Enrollment) и управления объектами каталогов через специализированные коллекции и API.

**Identity Provider (IdP)** — сервис, хранящий цифровые идентификаторы и подтверждающий подлинность субъектов (например, Active Directory, FreeIPA, Keycloak, Azure AD/Entra ID).

**Enrollment (Ввод в домен)** — процесс регистрации управляемого узла в IdM-системе с получением доверенных учетных данных (Keytab, сертификаты) и настройкой клиентских служб (SSSD, PAM).

**SCIM (System for Cross-domain Identity Management)** — протокол автоматической синхронизации пользователей между IdP и целевыми системами.

---

## Основные концепции

### 1. Архитектурные подходы к автоматизации

1.  **Управление клиентами (Client Side):**
    - Автоматизация установки `sssd`, `realmd`, `adcli` или специализированных агентов.
    - Настройка механизмов доверия (Kerberos, PAM stack).
    - Использование **System Roles** (`fedora.linux_system_roles.ad_integration`) для минимизации кастомного кода.
2.  **Управление объектами (Server Side / Directory Management):**
    - Создание и модификация пользователей, групп, OUs прямо в каталоге.
    - Управление политиками доступа (HBAC, SUDO, RBAC).
    - Использование протоколов LDAP/LDAPS или нативных API (WinRM для AD, REST/JSON-RPC для FreeIPA).
3.  **Федеративная идентификация (Modern IdM):**
    - Автоматизация настройки протоколов SAML 2.0, OIDC и механизмов SCIM для синхронизации пользователей между облачными и локальными системами.

### 2. Компоненты безопасности (2026)

-   **Zero Trust Enrollment:** Использование временных токенов (One-Time Passwords, OTP) или динамических Principal для ввода хостов в домен без раскрытия пароля администратора.
-   **Управление сертификатами:** Интеграция с PKI через протоколы ACME или SCEP для автоматической выдачи и обновления SSL/SSH-сертификатов хостов.
-   **MFA-контекст:** Настройка политик многофакторной аутентификации на уровне IdM через Ansible для критических сегментов сети.

### 3. Сравнение IdM-систем

| Критерий | Active Directory | FreeIPA | Azure AD / Entra ID | Keycloak |
| :--- | :--- | :--- | :--- | :--- |
| **Протоколы** | LDAP/Kerberos/WinRM | LDAP/Kerberos/REST | REST/OIDC/SAML | OIDC/SAML/LDAP |
| **Ansible коллекция** | `microsoft.ad` | `freeipa.ansible_freeipa` | `azure.azcollection` | REST API (ansible.builtin.uri) |
| **Платформа** | Windows Server | RHEL/CentOS/Fedora | Azure Cloud | Кроссплатформенный |
| **Модель лицензирования** | CAL лицензии | Бесплатный (open source) | Pay-as-you-go | Бесплатный (open source) |
| **Управление Linux-хостами** | Через SSSD/realmd | Нативная интеграция | Через SSSD | Через SAML/OIDC |
| **HBAC / SUDO** | Ограниченно (GPO) | Полная поддержка | Нет | Через клиентские приложения |
| **LDAP-каталог** | Да (AD DS) | Да (389 DS) | Да (Azure AD DS) | Да (встроенный) |
| **Высокая доступность** | Репликация AD | Репликация IPA | Azure SLA 99.99% | Кластер |

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
| **Kerberos** | Токен-based аутентификация без передачи пароля | `kinit`, keytab, `ansible.builtin.kerberos` |
| **LDAP/LDAPS** | Протокол доступа к каталогу (порт 389/636) | `ansible.builtin.ldap`, `microsoft.ad.user` |
| **SAML 2.0** | Федеративная аутентификация (SSO) | Настройка через `community.general.saml` |
| **OIDC** | OpenID Connect (REST-based) | Интеграция с Keycloak, Azure AD |
| **SSH Keys** | Аутентификация по публичному ключу | `ansible.posix.authorized_key` |
| **Certificates** | X.509 сертификаты для аутентификации | `ansible.builtinertificate`, SCEP/ACME |
| **OTP** | Одноразовые пароли (TOTP/HOTP) | Ввод в домен через FreeIPA |

### 6. Синхронизация идентичностей

Для гибридных сред (облако + on-premise) важна синхронизация:

```yaml
# Схема синхронизации пользователей
# Local LDAP ←→ Azure AD ←→ Keycloak (SSO)
#
# Инструменты:
# - Azure AD Connect (лассическая синхронизация)
# - SCIM 2.0 (автоматическая синхронизация)
# - Custom Ansible playbooks (ручная синхронизация)
```

---

## Подготовка окружения

Для работы с современными IdM-системами необходимо установить соответствующие коллекции на Control Node:

```bash
# Управление Active Directory и Windows-сервисами
ansible-galaxy collection install microsoft.ad

# Управление FreeIPA / Red Hat IdM
ansible-galaxy collection install freeipa.ansible_freeipa

# Интеграция с Azure / Entra ID
ansible-galaxy collection install azure.azcollection

# Управление Ansible Automation Platform (Controller)
ansible-galaxy collection install ansible.controller

# Управление локальными пользователями и группами
ansible-galaxy collection install ansible.builtin

# Управление SSH-ключами
ansible-galaxy collection install ansible.posix
```

---

## Практические сценарии

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

### 3. Интеграция с облачными IdP (Azure AD / Entra ID)

Используется для гибридных облачных сред.

```yaml
- name: "Управление пользователями в Azure Entra ID"
  hosts: localhost
  tasks:
    - name: "Создание пользователя в Azure AD"
      azure.azcollection.azure_rm_aduser:
        display_name: "Cloud Admin"
        user_principal_name: "cadmin@example.onmicrosoft.com"
        password: "{{ vault_cloud_pass }}"
        mail_nickname: "cadmin"
        state: present

    - name: "Назначение лицензии"
      azure.azcollection.azure_rm_subscription_info:
        # Лицензирование через Graph API
```

#### Настройка SCIM-синхронизации
```yaml
- name: "Настройка SCIM-провайдера"
  hosts: localhost
  tasks:
    - name: "Настройка SCIM-эндпоинта"
      community.general.saml_idp:
        # Конфигурация SCIM для синхронизации пользователей
```

### 4. Управление доступом в Ansible Automation Platform (RBAC)

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

### 5. Локальное управление пользователями и группами

Для сценариев, где централизованная IdM недоступна или не нужна.

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

### 6. Управление SSH-ключами и сертификатами

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

### 7. Управление sudoers

#### Через FreeIPA (централизованно)
```yaml
# Уже покрыто в разделе 2 — FreeIPA ipasudorule
```

#### Локальное управление sudoers
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
        - { user: "asmith", host: "ALL", commands: "/usr/bin/systemctl restart nginx, /usr/bin/docker *"

    - name: "Настройка беспарольного sudo для service accounts"
      ansible.builtin.lineinfile:
        path: "/etc/sudoers.d/90-ansible-worker"
        line: "service_user ALL=(ALL) NOPASSWD: ALL"
        create: true
        validate: /usr/sbin/visudo -csf %s
        mode: "0440"
```

### 8. Audit и комплаенс

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

---

## Дополнительная информация

### Безопасность и лучшие практики

1.  **Identity as Code:** Храните определения пользователей и групп в Git (YAML), используя Ansible Vault для паролей и Keytab-файлов.
2.  **Минимизация привилегий:** Используйте технические учетные записи с делегированными правами (например, право только на Join в конкретную OU) вместо `Domain Admin`.
3.  **Валидация (Post-enrollment):** Всегда проверяйте результат интеграции:
    ```yaml
    - name: "Верификация Kerberos-аутентификации"
      ansible.builtin.shell: kinit -k -t /etc/krb5.keytab $(hostname -f)$
      changed_when: false
    ```
4.  **Синхронизация времени:** Kerberos требует расхождения не более 5 минут. Перед вводом в домен всегда запускайте роль настройки NTP/Chrony.
5.  **Ротация секретов:** Регулярно обновляйте пароли сервисных аккаунтов, keytab-файлы и SSH-ключи. Используйте `ansible.builtin.cron` для автоматической ротации.
6.  **Аудит доступа:** Ведите журнал всех операций управления идентификацией. Используйте callback-плагины для отправки событий в SIEM.

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

# Проверка_FreeIPA
ipa user-show username
ipa host-show $(hostname -f)
ipa hbacrule-find
```

### Таблица типовых ошибок

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

### Смотрите также

- **[Модули управления пользователями](./Modules/ansible_security_and_user_management_modules.md)** — базовые модули `user`, `group`, `authorized_key`, `sudoers` для локальных систем.
- **[Интеграция SSSD с Active Directory](../Linux/SystemAdministration/Users/LDAP_SSSD/ad_integration.md)** — системные аспекты и отладка.
- **[Обзор FreeIPA](../LDAP/FreeIPA/freeipa_overview.md)** — архитектура IdM-решения.

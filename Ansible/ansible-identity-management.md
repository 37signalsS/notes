# Автоматизация управления идентификацией (Ansible Identity Management)

## Определения

**Identity Management (IdM)** — централизованная система управления жизненным циклом учетных записей, групп, полномочий и методов аутентификации в распределенной инфраструктуре.

**Ansible Identity Management** — использование декларативной автоматизации для развертывания IdM-решений, интеграции конечных узлов (Enrollment) и управления объектами каталогов через специализированные коллекции и API.

**Identity Provider (IdP)** — сервис, хранящий цифровые идентификаторы и подтверждающий подлинность субъектов (например, Active Directory, FreeIPA, Keycloak, Azure AD/Entra ID).

**Enrollment (Ввод в домен)** — процесс регистрации управляемого узла в IdM-системе с получением доверенных учетных данных (Keytab, сертификаты) и настройкой клиентских служб (SSSD, PAM).

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
```

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

### См. также
- **[Интеграция SSSD с Active Directory](../Linux/SystemAdministration/Users/LDAP_SSSD/ad_integration.md)** — системные аспекты и отладка.
- **[Обзор FreeIPA](../LDAP/FreeIPA/freeipa_overview.md)** — архитектура IdM-решения.
- **[Модули управления пользователями](./Modules/ansible_security_and_user_management_modules.md)** — базовые модули `user` и `group`.

# Интеграция Authentik и Wazuh: SSO, 2FA и Аудит

## Определения

**Authentik** — современный Identity Provider (IdP) с открытым исходным кодом, обеспечивающий централизованное управление удостоверениями и доступом во всей инфраструктуре.

**Single Sign-On (SSO)** — технология единого входа, позволяющая пользователю один раз пройти аутентификацию в Authentik и получить прозрачный доступ к Wazuh, Grafana и другим сервисам без повторного ввода пароля.

**SAML 2.0 (Security Assertion Markup Language)** — протокол на базе XML для обмена данными аутентификации и авторизации между IdP (Authentik) и Service Provider (Wazuh Indexer).

**RBAC (Role-Based Access Control)** — модель управления доступом на основе ролей. В данной интеграции роли назначаются в Authentik и передаются через SAML-атрибуты для маппинга на внутренние права Wazuh.

## Основные концепции

### Задачи интеграции
1.  **Централизация управления**: Мгновенный отзыв доступа уволенного сотрудника ко всем системам через блокировку одной учетной записи.
2.  **Повышение безопасности (MFA)**: Принудительное использование TOTP или WebAuthn на уровне IdP защищает SIEM даже при компрометации пароля.
3.  **Аудит доступа**: Централизованный сбор логов об успешных и неуспешных входах, сменах паролей и изменениях политик.

### Механизмы взаимодействия (Flows)
*   **IdP-initiated flow**: Пользователь авторизуется на портале Authentik, нажимает на иконку приложения Wazuh и перенаправляется в дашборд уже авторизованным.
*   **SP-initiated flow**: Пользователь заходит по URL Wazuh Dashboard, система перенаправляет его в Authentik для ввода данных и возвращает обратно с SAML-ответом.

## Практические сценарии

### 1. Настройка SSO (SAML)

Настройка требует последовательных действий на обеих сторонах.

#### Шаг А: Настройка Authentik (IdP)

1.  **Создание групп**: Создайте группу (например, `wazuh-administrators`) и добавьте в нее соответствующих пользователей.
2.  **Property Mapping**: Создайте `SAML Provider Property Mapping` для передачи ролей:
    *   **Name**: Wazuh Roles Mapping
    *   **SAML Attribute Name**: `Roles`
    *   **Expression**:
        ```python
        if ak_is_group_member(request.user, name="wazuh-administrators"):
            yield "wazuh-admin"
        elif ak_is_group_member(request.user, name="wazuh-analysts"):
            yield "wazuh-readonly"
        ```
3.  **SAML Provider**: Создайте провайдер с параметрами:
    *   **Name**: Wazuh
    *   **ACS URL**: `https://<wazuh-dashboard-url>/_opendistro/_security/saml/acs`
    *   **Issuer**: `wazuh-saml`
    *   **Binding**: `Post`
    *   **Property Mappings**: Выберите созданный маппинг `Wazuh Roles Mapping`.
4.  **Application**: Создайте приложение, привяжите к нему Provider и скачайте `idp-metadata.xml` (раздел Metadata в объекте провайдера).

#### Шаг Б: Настройка Wazuh Indexer (SP)

На **каждой ноде** кластера Wazuh Indexer выполните следующие действия:

1.  Разместите файл метаданных:
    ```bash
    cp idp-metadata.xml /etc/wazuh-indexer/opensearch-security/
    chown wazuh-indexer:wazuh-indexer /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
    chmod 640 /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
    ```
2.  Отредактируйте `/etc/wazuh-indexer/opensearch-security/config.yml`. Добавьте или измените блок `saml_auth_domain`:
    ```yaml
    authc:
      basic_internal_auth_domain:
        http_enabled: true
        transport_enabled: true
        order: 0
        http_authenticator:
          type: basic
          challenge: false # Важно: отключаем всплывающее окно Basic Auth
        authentication_backend:
          type: intern
      saml_auth_domain:
        http_enabled: true
        transport_enabled: false
        order: 1
        http_authenticator:
          type: saml
          challenge: true
          config:
            idp_initiated: true
            idp:
              metadata_file: "/etc/wazuh-indexer/opensearch-security/idp-metadata.xml"
              entity_id: "wazuh-saml"
            sp:
              entity_id: "wazuh-saml"
            kibana_url: "https://<wazuh-dashboard-url>/"
            roles_key: Roles
            # Важно для 4.9+: ключ должен быть длиной ровно 64 символа (hex)
            exchange_key: "сгенерируйте_через_openssl_rand_-hex_32"
        authentication_backend:
          type: noop
    ```
3.  Отредактируйте `/etc/wazuh-indexer/opensearch-security/roles_mapping.yml`, связав SAML-роль с внутренней ролью:
    ```yaml
    all_access:
      reserved: true
      backend_roles:
        - "wazuh-admin"
        - "admin"
    ```
4.  Примените конфигурацию:
    ```bash
    export JAVA_HOME=/usr/share/wazuh-indexer/jdk/ && bash \
    /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
    -f /etc/wazuh-indexer/opensearch-security/config.yml \
    -icl -key /etc/wazuh-indexer/certs/admin-key.pem \
    -cert /etc/wazuh-indexer/certs/admin.pem \
    -cacert /etc/wazuh-indexer/certs/root-ca.pem \
    -h <indexer_fqdn> -p 9200 -nhnv
    ```

#### Шаг В: Настройка Wazuh Dashboard

1.  В файле `/usr/share/wazuh-dashboard/data/wazuh/config/wazuh.yml` установите:
    ```yaml
    run_as: true
    ```
2.  В файле `opensearch_dashboards.yml` добавьте белый список для CORS:
    ```yaml
    opensearch_security.auth.type: "saml"
    opensearch_security.auth.multiple_auth_enabled: true
    server.xsrf.allowlist:
      - "/_opendistro/_security/saml/acs"
      - "/_opendistro/_security/saml/logout"
      - "/_opendistro/_security/saml/acs/idpinitiated"
    opensearch_security.session.keepalive: false
    ```
3.  Перезапустите `wazuh-dashboard`.

### 2. Принудительное включение 2FA (TOTP)

Для защиты SIEM на уровне Authentik:
1.  Перейдите в **Flows -> Flows** -> `default-authentication-flow`.
2.  Отредактируйте стадию `default-authentication-mfa-validation`.
3.  Установите **Not configured action** в значение **Force the user to configure an authenticator**.
4.  Убедитесь, что **Device classes** включает `TOTP`.

### 3. Аудит событий Authentik в Wazuh

Для отслеживания попыток взлома самого IdP (например, Brute Force на портале Authentik).

#### Шаг А: Сбор событий через API
Используйте Python-скрипт на менеджере для опроса эндпоинта `/api/v3/events/events/`. Скрипт должен сохранять состояние (последний обработанный ID) и записывать события в JSON-лог для Wazuh.

**Требования:**
- API Token в Authentik (Service Account).
- Учетная запись в Wazuh с правами на API `/events`.

#### Шаг Б: Правила алертинга
Разместите в `/var/ossec/etc/rules/authentik_custom.xml`:
```xml
<group name="authentik,">
  <!-- Базовое правило ошибки входа -->
  <rule id="110001" level="5">
    <field name="integration">authentik</field>
    <field name="action">login_failed</field>
    <description>Authentik: Ошибка входа для пользователя $(user)</description>
    <mitre><id>T1078</id></mitre>
  </rule>

  <!-- Детекция Brute Force: 5 ошибок за минуту -->
  <rule id="110037" level="10" frequency="5" timeframe="60">
    <if_matched_sid>110001</if_matched_sid>
    <same_field>client_ip</same_field>
    <description>Authentik: Обнаружен Brute force (5 ошибок с одного IP)</description>
    <mitre><id>T1110.001</id></mitre>
  </rule>
</group>
```

### 4. Решение типичных проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **500 Internal Server Error** | Короткий `exchange_key`. | Ключ должен быть ровно 64 символа (hex). |
| **Login Loop / Cookie Error** | Конфликт сессий. | Очистите куки; установите `session.keepalive: false`. |
| **ACS Mismatch** | Разные URL в IdP и SP. | ACS URL должен быть строго `https://<wazuh-url>/_opendistro/_security/saml/acs`. |
| **User has no permissions** | Ошибка RBAC маппинга. | Проверьте наличие атрибута `Roles` в SAML-ответе через Developer Tools браузера. |

## Дополнительная информация

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [OIDC и SAML: стандарты аутентификации](../../Concepts/oauth2_overview.md)
- [MFA и TOTP: теория и применение](../../Concepts/mfa_totp.md)
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md)

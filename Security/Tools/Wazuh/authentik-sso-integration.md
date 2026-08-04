# Интеграция Authentik и Wazuh: SSO, 2FA и Аудит

## Определения

**Authentik** — self-hosted Identity Provider (IdP). Центр управления удостоверениями, обеспечивающий единую точку входа (SSO) для инфраструктуры.

**Single Sign-On (SSO)** — технология единого входа. Позволяет пользователю аутентифицироваться один раз в Authentik и получать доступ ко всем подключенным сервисам (Wazuh, Grafana, Proxmox) без повторного ввода пароля.

**SAML (Security Assertion Markup Language)** — XML-стандарт для обмена данными аутентификации и авторизации между IdP (Authentik) и Service Provider (Wazuh).

**RBAC (Role-Based Access Control)** — управление доступом на основе ролей. В контексте SSO роли назначаются в Authentik и передаются в Wazuh через SAML-атрибуты для маппинга на внутренние права.

## Основные концепции

Интеграция Wazuh с централизованным IdP решает три фундаментальные задачи безопасности:
1.  **Централизация управления**: Мгновенное отключение доступа уволенного сотрудника ко всем системам одновременно.
2.  **Повышение безопасности (2FA)**: Принудительное использование TOTP (Time-based One-Time Password) на уровне IdP защищает все подключенные сервисы, даже если они не поддерживают 2FA нативно.
3.  **Аудит доступа**: Централизованный сбор логов успешных и неуспешных входов, смен паролей и изменений политик.

Взаимодействие по протоколу SAML может быть инициировано двумя путями:
*   **IdP-initiated flow**: Пользователь заходит на портал Authentik, кликает на иконку Wazuh и пробрасывается в дашборд уже авторизованным.
*   **SP-initiated flow**: Пользователь открывает дашборд Wazuh, перенаправляется на Authentik для ввода пароля, и возвращается обратно.

## Практические сценарии

### Сценарий 1: Настройка SSO (SAML) между Authentik и Wazuh

Настройка требует конфигурации с обеих сторон.

#### 1. Настройка Authentik (IdP)

1.  **Группы и пользователи**: Создайте группу (например, `wazuh-administrators`) и добавьте в нее пользователей.
2.  **Property Mappings**: Создайте `SAML Provider Property Mapping` для передачи ролей:
    *   **Name**: Wazuh Roles Mapping
    *   **SAML Attribute Name**: `Roles`
    *   **Expression**:
        ```python
        if ak_is_group_member(request.user, name="wazuh-administrators"):
            yield "wazuh-admin"
        ```
3.  **SAML Provider**: Создайте провайдер с параметрами:
    *   **Name**: Wazuh
    *   **ACS URL**: `https://<wazuh-dashboard-url>/_opendistro/_security/saml/acs/idpinitiated` (для IdP-initiated) или `.../saml/acs` (для SP-initiated).
    *   **Issuer**: `wazuh-saml`
    *   **Binding**: `Post`
    *   **Property Mappings**: Выберите созданный ранее маппинг.
4.  **Application**: Создайте приложение, привяжите к нему Provider и скачайте `idp-metadata.xml` (раздел Related objects -> Metadata).

#### 2. Настройка Wazuh Indexer (SP)

На **каждой ноде** кластера Wazuh Indexer выполните следующие действия:

1.  Разместите метаданные:
    ```bash
    cp idp-metadata.xml /etc/wazuh-indexer/opensearch-security/
    chown wazuh-indexer:wazuh-indexer /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
    chmod 640 /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
    ```
2.  Отредактируйте `/etc/wazuh-indexer/opensearch-security/config.yml` (предварительно сделав бэкап). Добавьте `saml_auth_domain`:
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
            idp_initiated: true # Включает IdP-initiated flow
            idp:
              metadata_file: "/etc/wazuh-indexer/opensearch-security/idp-metadata.xml"
              entity_id: "wazuh-saml"
            sp:
              entity_id: "wazuh-saml"
            kibana_url: "https://<wazuh-dashboard-url>/"
            roles_key: Roles
            exchange_key: "сгенерируйте_ключ_через_openssl_rand_-hex_32"
        authentication_backend:
          type: noop
    ```
3.  Отредактируйте `/etc/wazuh-indexer/opensearch-security/roles_mapping.yml`, связав роль из SAML с внутренней ролью Wazuh:
    ```yaml
    all_access:
      reserved: true
      hidden: false
      backend_roles:
        - "wazuh-admin"
        - "admin"
    ```
4.  Примените конфигурацию с помощью `securityadmin.sh` (укажите правильный FQDN ноды в ключе `-h`):
    ```bash
    export JAVA_HOME=/usr/share/wazuh-indexer/jdk/ && bash \
    /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
    -f /etc/wazuh-indexer/opensearch-security/config.yml \
    -icl -key /etc/wazuh-indexer/certs/admin-key.pem \
    -cert /etc/wazuh-indexer/certs/admin.pem \
    -cacert /etc/wazuh-indexer/certs/root-ca.pem \
    -h indexer.yourdomain.com -p 9200 -nhnv
    ```
    *Повторите команду для `roles_mapping.yml`*.

#### 3. Настройка Wazuh Dashboard

Отредактируйте `/etc/wazuh-dashboard/opensearch_dashboards.yml`:
```yaml
# Можно оставить оба метода: ["basicauth", "saml"]
opensearch_security.auth.type: "saml"
opensearch_security.auth.multiple_auth_enabled: true

# Белый список для CORS. Без него SAML-ответы будут блокироваться.
server.xsrf.allowlist:
  - "/_opendistro/_security/saml/acs"
  - "/_opendistro/_security/saml/logout"
  - "/_opendistro/_security/saml/acs/idpinitiated"

# Отключаем keepalive для предотвращения конфликтов сессий с IdP
opensearch_security.session.keepalive: false
```
Перезапустите `wazuh-dashboard`.

### Сценарий 2: Принудительное включение 2FA (TOTP)

Для обеспечения безопасности всех подключенных сервисов, 2FA должна быть обязательной.

1.  В Authentik перейдите в **Flows -> Flows**.
2.  Выберите `default-authentication-flow`.
3.  Отредактируйте Stage `default-authentication-mfa-validation`.
4.  В поле **Not configured action** установите **Force the user to configure an authenticator**.
5.  Убедитесь, что **Device classes** включает `TOTP`.

Теперь при первом входе пользователь будет обязан отсканировать QR-код в приложении-аутентификаторе.

### Сценарий 3: Аудит событий Authentik в Wazuh

События самого Identity Provider (успешные входы, отказы, смены паролей) критически важны для мониторинга.

#### 1. Интеграционный Python-скрипт
Скрипт использует API Authentik для сбора событий с учетом пагинации и сохраняет state (последний обработанный ID) для дедупликации. События отправляются в Wazuh через REST API `/events`.

**Требования:**
- API Token в Authentik (Admin -> Directory -> Tokens and App Passwords). Рекомендуется создать выделенного Service Account.
- Учетная запись в Wazuh с правами на API `/events`.

*Пример логики скрипта:*
Скрипт делает GET-запрос к `https://<authentik>/api/v3/events/events/?ordering=-created&created__gte=<last_timestamp>`. Полученные JSON-объекты дополняются полем `"integration": "authentik"`, формируются в батчи и отправляются POST-запросом на `https://<wazuh-api>/events`. Для надежности скрипт также может писать события в локальный JSON-файл для сборки через Filebeat/Wazuh Agent.

#### 2. Правила Wazuh для Authentik
Разместите пользовательские правила в `/var/ossec/etc/rules/authentik_custom.xml`. Правила покрывают различные сценарии и смаплены на матрицы MITRE ATT&CK и стандарты комплаенса (PCI DSS, GDPR).

Пример критического правила (Brute Force):
```xml
<group name="authentik,">
  <!-- Базовое правило неудачного входа -->
  <rule id="110001" level="5">
    <field name="integration">authentik</field>
    <action>login_failed</action>
    <description>Authentik: Failed login attempt</description>
    <mitre>
      <id>T1078</id>
      <id>T1110</id>
    </mitre>
  </rule>

  <!-- Корреляционное правило: 5 неудачных попыток за 60 секунд -->
  <rule id="110037" level="10" frequency="5" timeframe="60">
    <if_matched_sid>110001</if_matched_sid>
    <same_field>client_ip</same_field>
    <description>Authentik: Brute force detected (5 failed logins from same IP)</description>
    <mitre>
      <id>T1110.001</id>
    </mitre>
  </rule>
</group>
```

После добавления правил перезапустите Wazuh Manager: `systemctl restart wazuh-manager`.

## Дополнительная информация

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [OIDC и SAML: стандарты аутентификации](../../Concepts/oauth2_overview.md)
- [MFA и TOTP: теория и применение](../../Concepts/mfa_totp.md)
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md)

# Интеграция Authentik и Wazuh: SSO, 2FA и Аудит

## Определения

**Authentik** — современный Identity Provider (IdP) с открытым исходным кодом, обеспечивающий централизованное управление удостоверениями и доступом во всей инфраструктуре.

**Single Sign-On (SSO)** — технология единого входа, позволяющая пользователю один раз пройти аутентификацию в Authentik и получить прозрачный доступ к Wazuh, Grafana и другим сервисам без повторного ввода пароля.

**SAML 2.0 (Security Assertion Markup Language)** — протокол на базе XML для обмена данными аутентификации и авторизации между IdP (Authentik) и Service Provider (Wazuh Indexer).

**RBAC (Role-Based Access Control)** — модель управления доступом на основе ролей. В данной интеграции роли назначаются в Authentik и передаются через SAML-атрибуты для маппинга на внутренние права Wazuh.

**SAML Assertion** — XML-документ, подписанный приватным ключом IdP, содержащий утверждения о пользователе (identity, authentication, attributes). Wazuh Indexer верифицирует подпись assertion перед выдачей сессии.

**SAML Attribute** — пара "имя-значение", передаваемая внутри Assertion. В контексте интеграции атрибут `Roles` содержит список ролей пользователя, которые маппингся на `backend_roles` Wazuh Indexer.

**Property Mapping** — механизм Authentik, преобразующий внутренние данные пользователя (группы, атрибуты) в SAML-атрибуты. Реализуется через Python-выражения в веб-интерфейсе IdP.

**ACS (Assertion Consumer Service)** — эндпоинт Service Provider, принимающий и обрабатывающий SAML Response от IdP. В Wazuh Indexer: `/_opendistro/_security/saml/acs`.

**IdP Metadata** — XML-файл с публичной информацией о провайдере аутентификации (entity ID, сертификаты, ACS URL). Authentik экспортирует его из объекта SAML Provider.

**Logout / SLO (Single Log-Out)** — механизм завершения сессии одновременно в IdP и всех связанных SP. В SAML 2.0 реализуется через `LogoutRequest`/`LogoutResponse`.

**Session** — временный контекст аутентификации пользователя в браузере. Управляется через cookies с параметрами `Secure`, `HttpOnly`, `SameSite`.

**exchange_key** — секретный ключ симметричного шифрования (64 hex-символа = 32 байта), используемый Wazuh Indexer для шифрования и последующего обмена SAML-сообщениями с IdP. Генерируется односторонней функцией и должен быть идентичным на всех нодах кластера.

**SAML Auth Domain** — конфигурационный блок в `config.yml` Wazuh Indexer, определяющий параметры SAML-аутентификации: порядок проверки (`order`), тип аутентификатора, конфигурацию IdP/SP и backend.

**Wazuh Security Config** — набор файлов в `/etc/wazuh-indexer/opensearch-security/`, управляющих аутентификацией и авторизацией: `config.yml`, `roles_mapping.yml`, `roles.yml`, `action_groups.yml`, `tenants.yml`.

## Основные концепции

### Задачи интеграции

1.  **Централизация управления**: Мгновенный отзыв доступа уволенного сотрудника ко всем системам через блокировку одной учетной записи.
2.  **Повышение безопасности (MFA)**: Принудительное использование TOTP или WebAuthn на уровне IdP защищает SIEM даже при компрометации пароля.
3.  **Аудит доступа**: Централизованный сбор логов об успешных и неуспешных входах, сменах паролей и изменениях политик.

### Архитектура потока SAML-аутентификации

Поток данных при входе пользователя (SP-initiated flow):

```
Пользователь (браузер)
    │
    ▼
Wazuh Dashboard (SP)
    │  1. Проверка: нет активной сессии SAML
    │  2. Генерация SAML AuthnRequest
    │  3. Подпись запроса (опционально)
    │  4. Редирект (HTTP 302) на Authentik
    ▼
Authentik (IdP)
    │  5. Прием AuthnRequest, валидация
    │  6. Предъявление формы входа (или SSO session)
    │  7. MFA (TOTP/WebAuthn) при необходимости
    │  8. Формирование SAML Response + Assertion
    │  9. Подпись Assertion приватным ключом IdP
    │ 10. Шифрование Assertion (опционально)
    ▼
Браузер (HTTP-POST)
    │ 11. SAML Response на ACS URL Wazuh Indexer
    ▼
Wazuh Indexer (SP)
    │ 12. Валидация подписи Assertion по IdP Metadata
    │ 13. Проверка времени жизни, audience, recipient
    │ 14. Извлечение атрибута Roles
    │ 15. Маппинг Roles → backend_roles
    │ 16. Выдача сессии (cookie)
    ▼
Wazuh Dashboard
    │ 17. Загрузка интерфейса под ролью пользователя
    ▼
Пользователь авторизован
```

### Механизмы взаимодействия (Flows)

*   **IdP-initiated flow**: Пользователь авторизуется на портале Authentik, нажимает на иконку приложения Wazuh и перенаправляется в дашборд уже авторизованным.
*   **SP-initiated flow**: Пользователь заходит по URL Wazuh Dashboard, система перенаправляет его в Authentik для ввода данных и возвращает обратно с SAML-ответом.

### Требования к инфраструктуре

| Компонент | Требование |
| :--- | :--- |
| **Authentik** | Версия 2023.x+, доступ по HTTPS, валидный TLS-сертификат |
| **Wazuh Indexer** | 4.9+ (рекомендуется 5.x), кластер или single-node |
| **Wazuh Dashboard** | Совместимая версия с Indexer |
| **Сеть** | Доступ из браузера пользователя к Authentik (порт 443) и Wazuh Dashboard (порт 443); доступ из Wazuh Indexer к Authentik для метаданных |
| **TLS** | Валидные сертификаты для всех HTTPS-эндпоинтов; самоподписанные допустимы только для тестирования |
| **Домены** | Статические DNS-имена для Authentik и Wazuh Dashboard (не IP-адреса) |

### Изменения в Wazuh 5.x для аутентификации

С выходом Wazuh 5.0 конфигурация SAML практически не изменилась, но учитывайте:

1.  **Пути конфигурации**: остаются прежними для Indexer (`/etc/wazuh-indexer/opensearch-security/`).
2.  **Права доступа**: пользователь `wazuh-indexer` должен иметь доступ к `config.yml` и `idp-metadata.xml`.
3.  **Кластеризация**: на каждой ноде Indexer должен быть размещен идентичный `idp-metadata.xml` и `config.yml`.
4.  **Dashboard CORS**: параметр `server.xsrf.allowlist` должен включать SAML ACS URL для корректной работы редиректов.
5.  **Роли**: внутренние роли Wazuh Indexer (`all_access`, `kibana_user`, `kibana_server`) определены в `/etc/wazuh-indexer/opensearch-security/roles.yml`.

### SAML vs OIDC для Authentik + Wazuh

| Критерий | SAML 2.0 | OIDC |
| :--- | :--- | :--- |
| **Поддержка Wazuh Indexer** | Да (нативная) | Нет (требует кастомный плагин или reverse proxy) |
| **Сложность настройки** | Средняя | Низкая (где поддерживается) |
| **Формат токена** | XML Assertion | JWT (ID Token + Access Token) |
| **Атрибуты** | XML Attribute Statement | JWT claims |
| **Рекомендация для Wazuh** | **SAML 2.0** | Неприменимо без кастомного решения |

**Вывод:** Для интеграции Authentik с Wazuh Indexer используйте **SAML 2.0**, так как OpenSearch Security (ядро Wazuh Indexer) не поддерживает OIDC нативно.

### RBAC: маппинг ролей

Wazuh Indexer использует концепцию `backend_roles`, которые связываются с внутренними роли через `roles_mapping.yml`:

```yaml
# /etc/wazuh-indexer/opensearch-security/roles_mapping.yml
all_access:
  reserved: true
  backend_roles:
    - "wazuh-admin"
    - "admin"
kibana_user:
  reserved: true
  backend_roles:
    - "wazuh-readonly"
```

**Важные правила:**
1.  Роль `all_access` дает полные права на Indexer и Dashboard.
2.  Роль `kibana_user` позволяет только просматривать Dashboard без изменения настроек.
3.  Кастомные роли создаются в `roles.yml` и связываются через `roles_mapping.yml`.
4.  Имя SAML-атрибута (`Roles` в конфигурации) должно точно совпадать с именем в Assertion от Authentik.

## Практические сценарии

### Предварительные требования

- **Wazuh Manager** 4.9+ (рекомендуется 5.x) с настроенным Indexer кластером.
- **Authentik** 2023.x+ с валидным TLS-сертификатом и доступом к веб-интерфейсу.
- **Сеть**: доступ из браузера пользователя к Authentik (443) и Wazuh Dashboard (443); из Indexer к Authentik для загрузки метаданных.
- **TLS**: валидные сертификаты для всех HTTPS-эндпоинтов.
- **Права**: root-доступ на ноды Wazuh Indexer для редактирования конфигураций и применения securityadmin.sh.
- **DNS**: статические имена для Authentik и Wazuh Dashboard (не IP-адреса).

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

**Валидация Authentik:**
```bash
# Проверка доступности метаданных IdP
curl -sk https://authentik.example.com/application/o/wazuh-saml/saml/metadata.xml | head -20
# → должен вернуться XML с EntityDescriptor
```

#### Шаг Б: Настройка Wazuh Indexer (SP)

На **каждой ноде** кластера Wazuh Indexer выполните следующие действия:

1.  **Разместите файл метаданных**:
    ```bash
    cp idp-metadata.xml /etc/wazuh-indexer/opensearch-security/
    chown wazuh-indexer:wazuh-indexer /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
    chmod 640 /etc/wazuh-indexer/opensearch-security/idp-metadata.xml

    # Валидация
    ls -la /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
    # → -rw-r----- 1 wazuh-indexer wazuh-indexer ... idp-metadata.xml
    ```

2.  **Генерация exchange_key**:
    ```bash
    # Ключ должен быть ровно 64 hex-символа (32 байта)
    openssl rand -hex 32
    # → abc123def456... (64 символа)

    # Валидация длины
    echo -n "<ключ>" | wc -c
    # → 64
    ```
    **Важно:** используйте ОДИН И ТОТ ЖЕ `exchange_key` на всех нодах кластера.

3.  **Отредактируйте `/etc/wazuh-indexer/opensearch-security/config.yml`**. Добавьте или измените блок `saml_auth_domain`:
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

4.  **Отредактируйте `/etc/wazuh-indexer/opensearch-security/roles_mapping.yml`**, связав SAML-роль с внутренней ролью:
    ```yaml
    all_access:
      reserved: true
      backend_roles:
        - "wazuh-admin"
        - "admin"
    kibana_user:
      reserved: true
      backend_roles:
        - "wazuh-readonly"
    ```

5.  **Примените конфигурацию**:
    ```bash
    export JAVA_HOME=/usr/share/wazuh-indexer/jdk/ && bash \
    /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
    -f /etc/wazuh-indexer/opensearch-security/config.yml \
    -icl -key /etc/wazuh-indexer/certs/admin-key.pem \
    -cert /etc/wazuh-indexer/certs/admin.pem \
    -cacert /etc/wazuh-indexer/certs/root-ca.pem \
    -h <indexer_fqdn> -p 9200 -nhnv
    # → Successfully loaded ... config file 'config.yml' into cluster state

    # Валидация
    curl -sk -u admin:admin https://<indexer_fqdn>:9200/_plugins/_security/api/rolesmapping/all_access | python3 -m json.tool
    # → должен содержать "wazuh-admin" в backend_roles
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

3.  **Перезапустите `wazuh-dashboard`**:
    ```bash
    systemctl restart opensearch-dashboard
    # или
    systemctl restart wazuh-dashboard

    # Валидация
    curl -sk https://<wazuh-dashboard-url>/status
    # → {"status":"ok"}
    ```

### 2. Принудительное включение 2FA (TOTP)

Для защиты SIEM на уровне Authentik:

1.  Перейдите в **Flows -> Flows** -> `default-authentication-flow`.
2.  Отредактируйте стадию `default-authentication-mfa-validation`.
3.  Установите **Not configured action** в значение **Force the user to configure an authenticator**.
4.  Убедитесь, что **Device classes** включает `TOTP`.

**Валидация:**
```bash
# Попробуйте войти в Authentik под тестовым пользователем
# → должен появиться экран настройки TOTP при первом входе
```

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

### 4. Альтернативный сценарий: настройка через OIDC (требует reverse proxy)

Wazuh Indexer не поддерживает OIDC наatively, но Authentik может выступать как OIDC IdP через обратный прокси (Nginx/Angie), который валидирует JWT и передает заголовки в Indexer.

**Архитектура:**
```
Браузер → Nginx (OIDC validation) → Wazuh Indexer (headers-based auth)
```

**Важные ограничения:**
- Dashboard не поддерживает headers-based auth для OpenSearch Security нативно.
- Требуется кастомный плагин или модификация `opensearch_dashboards.yml`.
- Для production используйте SAML (рекомендуется).

### 5. Развертывание конфигурации через Ansible

Автоматизация развертывания SAML-конфигурации на кластере Indexer:

```yaml
- name: Deploy Authentik SAML config to Wazuh Indexer
  hosts: wazuh_indexer
  become: yes
  vars:
    saml_exchange_key: "{{ lookup('password', '/dev/null length=32 chars=hex') }}"
  tasks:
    - name: Copy IdP metadata
      copy:
        src: files/authentik-idp-metadata.xml
        dest: /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
        owner: wazuh-indexer
        group: wazuh-indexer
        mode: '0640'

    - name: Configure SAML auth domain in config.yml
      lineinfile:
        path: /etc/wazuh-indexer/opensearch-security/config.yml
        insertafter: 'basic_internal_auth_domain:'
        block:
          - "      saml_auth_domain:"
          - "        http_enabled: true"
          - "        transport_enabled: false"
          - "        order: 1"
          - "        http_authenticator:"
          - "          type: saml"
          - "          challenge: true"
          - "          config:"
          - "            idp_initiated: true"
          - "            idp:"
          - "              metadata_file: \"/etc/wazuh-indexer/opensearch-security/idp-metadata.xml\""
          - "              entity_id: \"wazuh-saml\""
          - "            sp:"
          - "              entity_id: \"wazuh-saml\""
          - "            kibana_url: \"https://{{ wazuh_dashboard_url }}/\""
          - "            roles_key: Roles"
          - "            exchange_key: \"{{ saml_exchange_key }}\""
          - "        authentication_backend:"
          - "          type: noop"
      notify: restart wazuh-indexer

    - name: Apply security configuration
      command: >
        /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh
        -f /etc/wazuh-indexer/opensearch-security/config.yml
        -icl -key /etc/wazuh-indexer/certs/admin-key.pem
        -cert /etc/wazuh-indexer/certs/admin.pem
        -cacert /etc/wazuh-indexer/certs/root-ca.pem
        -h {{ inventory_hostname }} -p 9200 -nhnv
      notify: restart wazuh-indexer
```

### 6. Бэкап и восстановление конфигурации аутентификации

```bash
BACKUP_DIR="/var/backups/wazuh-auth-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Бэкап SAML-конфигурации Indexer
tar -czf "$BACKUP_DIR/wazuh-indexer-saml.tar.gz" \
  /etc/wazuh-indexer/opensearch-security/config.yml \
  /etc/wazuh-indexer/opensearch-security/roles_mapping.yml \
  /etc/wazuh-indexer/opensearch-security/idp-metadata.xml

# Бэкап Dashboard-конфигурации
tar -czf "$BACKUP_DIR/wazuh-dashboard-saml.tar.gz" \
  /usr/share/wazuh-dashboard/data/wazuh/config/wazuh.yml \
  /etc/opensearch-dashboards/opensearch_dashboards.yml

# Восстановление
tar -xzf /var/backups/wazuh-auth-20250918/wazuh-indexer-saml.tar.gz -C /
chown wazuh-indexer:wazuh-indexer /etc/wazuh-indexer/opensearch-security/idp-metadata.xml
chmod 640 /etc/wazuh-indexer/opensearch-security/idp-metadata.xml

# Переприменение securityadmin
export JAVA_HOME=/usr/share/wazuh-indexer/jdk/ && bash \
/usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
-f /etc/wazuh-indexer/opensearch-security/config.yml \
-icl -key /etc/wazuh-indexer/certs/admin-key.pem \
-cert /etc/wazuh-indexer/certs/admin.pem \
-cacert /etc/wazuh-indexer/certs/root-ca.pem \
-h <indexer_fqdn> -p 9200 -nhnv
```

### 7. Мониторинг работоспособности SAML

```bash
# Проверка статуса Indexer
curl -sk -u admin:admin https://<indexer_fqdn>:9200/_cluster/health?pretty
# → "status": "green" или "yellow"

# Проверка ролей маппинга
curl -sk -u admin:admin https://<indexer_fqdn>:9200/_plugins/_security/api/rolesmapping/all_access | python3 -m json.tool
# → должен содержать "wazuh-admin" в backend_roles

# Проверка доступности Dashboard
curl -sk https://<wazuh-dashboard-url>/status
# → {"status":"ok"}

# Проверка логов Indexer на SAML-ошибки
journalctl -u wazuh-indexer -f | grep -i saml
# → при успешной аутентификации ошибок быть не должно

# Тестовый вход через curl (имитация SAML Response)
# (требуется валидный SAML Response — см. документацию OpenSearch Security)
```

### 8. Создание кастомных ролей Wazuh

Для создания роли с ограниченными правами (например, только чтение определенных индексов):

1.  Создайте роль в `/etc/wazuh-indexer/opensearch-security/roles.yml`:
    ```yaml
    wazuh-readonly-soc:
      reserved: false
      cluster_permissions:
        - "cluster_composite_ops"
      index_permissions:
        - index_patterns:
            - "wazuh-alerts-*"
          dls: ""
          fls: []
          masked_fields: []
          allowed_actions:
            - "indices:data/read/search"
            - "indices:data/read/get"
      tenant_permissions:
        - tenant_patterns:
            - "wazuh"
          allowed_actions:
            - "kibana_all_read"
    ```

2.  Свяжите роль с SAML-атрибутом в `roles_mapping.yml`:
    ```yaml
    wazuh-readonly-soc:
      reserved: false
      backend_roles:
        - "wazuh-soc-readonly"
    ```

3.  Добавьте маппинг в Authentik Property Mapping:
    ```python
    if ak_is_group_member(request.user, name="wazuh-soc-readers"):
        yield "wazuh-soc-readonly"
    ```

4.  Примените конфигурацию через `securityadmin.sh`.

### 9. Конфигурация Single Logout (SLO)

Для завершения сессии во всех системах одновременно:

1.  В Authentik SAML Provider включите `Single Logout`.
2.  Укажите `Logout URL` в Authentik: `https://<wazuh-dashboard-url>/_opendistro/_security/saml/logout`.
3.  В Wazuh Dashboard `opensearch_dashboards.yml`:
    ```yaml
    opensearch_security.auth.saml.logout_url: "https://authentik.example.com/application/o/wazuh-saml/end-session/"
    ```
4.  Тестирование: после выхода из Authentik сессия в Wazuh Dashboard должна инвалидироваться.

## Дополнительная информация

### Сравнение методов аутентификации для Wazuh

| Метод | Описание | Рекомендация |
| :--- | :--- | :--- |
| **SAML 2.0** | Нативная поддержка OpenSearch Security, RBAC через атрибуты | **Рекомендуется для enterprise** |
| **Basic Auth** | Локальные пользователи Indexer, пароли в `internal_users.yml` | Только для emergency/break-glass |
| **LDAP** | Прямая интеграция с Active Directory/LDAP | Альтернатива SAML при отсутствии IdP |
| **Proxy Auth** | Аутентификация через обратный прокси (Nginx headers) | Требует кастомной конфигурации Dashboard |

### Миграционные заметки (4.x → 5.x)

- Пути конфигурации SAML в Indexer не изменились: `/etc/wazuh-indexer/opensearch-security/`.
- `exchange_key` должен быть ровно 64 hex-символа; в старых версиях допускалась другая длина.
- `basic_internal_auth_domain` должен оставаться включенным (`http_enabled: true`) для fallback.
- Dashboard CORS настройки (`xsrf.allowlist`) остались без изменений.
- Securityadmin CLI остался прежним; убедитесь что `JAVA_HOME` указывает на JDK Indexer.

### Best Practices

1.  **Кластерная консистентность**: на всех нодах Indexer размещайте идентичные `idp-metadata.xml` и `exchange_key`.
2.  **Ротация exchange_key**: ротируйте `exchange_key` раз в 90 дней через `openssl rand -hex 32` и повторный запуск `securityadmin.sh`.
3.  **Приоритет доменов**: `basic_internal_auth_domain` должен иметь `order: 0`, а `saml_auth_domain` — `order: 1`.
4.  **Сертификаты**: храните CA Wazuh в защищенном месте; без `root-ca.pem` невозможно применить securityadmin.sh.
5.  **RBAC least privilege**: создавайте кастомные роли вместо использования `all_access` для аналитиков.
6.  **Валидация после изменений**: всегда проверяйте `_cluster/health` и пробуйте войти под тестовым пользователем после применения конфигурации.
7.  **Логирование**: мониторьте `/var/log/wazuh-indexer/` на предмет SAML-ошибок (`signature validation failed`, `assertion expired`).
8.  **Сеть**: изолируйте доступ к Authentik; разрешите только доверенным подсетям.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **500 Internal Server Error** | Короткий `exchange_key`. | Ключ должен быть ровно 64 символа (hex). |
| **Login Loop / Cookie Error** | Конфликт сессий. | Очистите куки; установите `session.keepalive: false`. |
| **ACS Mismatch** | Разные URL в IdP и SP. | ACS URL должен быть строго `https://<wazuh-url>/_opendistro/_security/saml/acs`. |
| **User has no permissions** | Ошибка RBAC маппинга. | Проверьте наличие атрибута `Roles` в SAML-ответе через Developer Tools браузера. |
| **signature validation failed** | Неверный или устаревший IdP Metadata. | Обновите `idp-metadata.xml` на всех нодах и перезапустите securityadmin. |
| **assertion expired** | Часовой пояс или `NotBefore`/`NotOnOrAfter` в Assertion не совпадают. | Синхронизируйте время через NTP на всех узлах (chrony/ntpd). |
| **SAML Response не отправляется** | CORS блокирует запрос. | Проверьте `server.xsrf.allowlist` в `opensearch_dashboards.yml`. |
| **Неверные роли после входа** | Атрибут `Roles` отсутствует или имеет неверное имя. | Проверьте Property Mapping в Authentik и `roles_key` в `config.yml`. |
| **securityadmin.sh не применяет конфиг** | Неверные права или путь к сертификатам. | Проверьте `JAVA_HOME`, права на `.pem` файлы и FQDN ноды. |
| **Только admin может входить, остальные получают 403** | В `roles_mapping.yml` отсутствует маппинг для SAML-ролей. | Добавьте `backend_roles` для всех ролей, возвращаемых Authentik. |

### Edge Cases и ограничения

*   **Длина exchange_key**: должна быть ровно 64 hex-символа. Меньшее или большее значение вызывает `500 Internal Server Error` при обмене SAML-сообщениями.
*   **Несколько нод Indexer**: `idp-metadata.xml` и `exchange_key` должны быть идентичны на всех нодах; иначе сессия, созданная на одной ноде, не будет валидна на другой.
*   **Самоподписанные сертификаты**: Authentik и Wazuh Dashboard должны доверять сертификатам друг друга; добавьте CA в trust store браузера и серверов.
*   **Часовые пояса**: SAML Assertion имеет ограничение по времени (`NotBefore`/`NotOnOrAfter`). Разница более 5 минут между IdP и SP вызывает `assertion expired`. Используйте NTP.
*   **Browser SameSite cookies**: современные браузеры (Safari, Firefox) могут блокировать SAML POST из-за политик `SameSite`. Используйте HTTPS и правильные `Secure`/`SameSite=None` атрибуты.
*   **Logout из Dashboard**: по умолчанию logout только в Dashboard, но не в Authentik. Для SLO требуется явная конфигурация `saml.logout_url` и поддержка на стороне IdP.
*   **Резервный вход**: всегда оставляйте `basic_internal_auth_domain` включенным с локальным администратором для аварийного доступа при падении Authentik.
*   **Режим maintenance**: при обновлении Authentik временно отключите `challenge: true` в `saml_auth_domain`, чтобы избежать блокировки инженеров.

### Телеметрия и мониторинг SAML-аутентификации

```bash
# Проверка статуса Indexer
curl -sk -u admin:admin https://<indexer_fqdn>:9200/_cluster/health?pretty

# Проверка ролей маппинга
curl -sk -u admin:admin https://<indexer_fqdn>:9200/_plugins/_security/api/rolesmapping/all_access | python3 -m json.tool

# Мониторинг логов Indexer на SAML-ошибки
journalctl -u wazuh-indexer -f | grep -iE "saml|assertion|auth"

# Проверка доступности Dashboard
curl -sk https://<wazuh-dashboard-url>/status
# → {"status":"ok"}
```

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [OIDC и SAML: стандарты аутентификации](../../Concepts/oauth2_overview.md)
- [MFA и TOTP: теория и применение](../../Concepts/mfa_totp.md)
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md)

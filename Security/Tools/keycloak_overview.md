# Keycloak

## Определения

**Keycloak** — open-source продукт для управления идентификацией и доступом (Identity and Access Management, IAM). Обеспечивает централизованную аутентификацию и авторизацию для приложений и сервисов. Разрабатывается Red Hat, распространяется под лицензией Apache 2.0.

**Realm** — изолированное пространство в Keycloak, содержащее собственный набор пользователей, ролей, клиентов и политик доступа. Каждый Realm работает независимо от других.

---

## Базовые концепции

### Аутентификация и Авторизация (AuthN/AuthZ)

Keycloak разделяет процессы:

- **Аутентификация (Authentication, AuthN):** Проверка подлинности пользователя (кто ты?).
- **Авторизация (Authorization, AuthZ):** Предоставление прав доступа к ресурсам (что тебе разрешено?).

### Поддерживаемые протоколы

| Протокол | Назначение |
| :--- | :--- |
| **OpenID Connect (OIDC)** | Слой идентификации поверх OAuth 2.0, выдаёт ID Token (JWT) |
| **OAuth 2.0** | Фреймворк делегирования авторизации (access token, refresh token) |
| **SAML 2.0** | Стандарт обмена данными аутентификации для enterprise-приложений |

### Аналоги

| Решение | Отличия от Keycloak |
| :--- | :--- |
| **Microsoft Active Directory** | Ориентирован на Windows-инфраструктуру; Keycloak — кросс-платформенный, стек Linux/macOS |
| **Okta, Auth0** | Облачные SaaS-провайдеры; Keycloak — self-hosted, полный контроль над данными |
| **Dex** | Лёгкий OIDC-провайдер; Keycloak — полноценный IAM с UI и политиками доступа |

### Ключевые компоненты

- **User Federation:** Подключение внешних источников пользователей (LDAP, Active Directory). Подробности: [Keycloak LDAP Federation](./keycloak_ldap_federation.md)
- **Identity Brokering:** Промежуточная аутентификация через внешние провайдеры (Google, GitHub, GitLab)
- **Client Scopes:** Наборы OIDC-скоупов и маппингов для токенов
- **Service Accounts:** Аутентификация сервисов через Client Credentials Grant

---

## Практические сценарии

### Single Sign-On (SSO)

Пользователи входят в несколько приложений через единую учётную запись Keycloak. После аутентификации в одном приложении доступ к другим происходит без повторного ввода пароля.

### Управление доступом

Администраторы настраивают детальные политики доступа (roles, groups, policies) для пользователей и сервисов. Поддержка ролевого моделирования (role-based access control) с наследованием ролей.

### Федерация удостоверений (Identity Federation)

Keycloak выступает посредником для внешних провайдеров идентификации: Google, GitHub, корпоративный LDAP/Active Directory. Подробности федерации: [Keycloak LDAP Federation](./keycloak_ldap_federation.md).

---

## Дополнительная информация

### Архитектура развёртывания

- **Standalone:** Одиночный экземпляр на базе WildFly (до v22) или Quarkus (v22+)
- **High Availability:** Кластеризация через Infinispan/JGroups для репликации сессий
- **Kubernetes:** Официальный Helm-chart `codecentric/keycloakx` (устаревший `codecentric/keycloak` не рекомендуется)

### Рекомендуемые практики

1. **Production:** Использовать внешнюю БД (PostgreSQL) вместо встроенной H2
2. **TLS:** Обязателен для всех endpoint; self-signed сертификаты только для тестирования
3. **Realms:** Разделять среды (dev, staging, prod) через отдельные Realms или экземпляры
4. **Бэкапы:** Регулярный бэкап БД Keycloak — восстановление без бэкапа невозможно

### Мониторинг

Keycloak предоставляет метрики через endpoint `/metrics` (формат Prometheus). Ключевые метрики: количество аутентификаций, ошибки входа, активные сессии, время отклика. Интеграция с Grafana через дашборды сообщества.

### См. также

- [OAuth2 Overview](../Concepts/oauth2_overview.md) — протоколы OAuth 2.0 и OIDC
- [Authentication in Kubernetes](../../Kubernetes/Security/authentication.md) — OIDC-аутентификация в Kubernetes
- [Istio Observability](../../Service_Mesh/istio_observability_and_tools.md) — интеграция Keycloak с Istio

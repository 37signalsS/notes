# ArgoCD: Настройка SSO через GitLab

Настройка Single Sign-On (SSO) в ArgoCD через GitLab позволяет централизованно управлять доступом пользователей, используя существующие учетные записи и группы GitLab. Для реализации используется встроенный сервер **Dex**.

## Определения

- **SSO (Single Sign-On)** — технология единого входа, позволяющая пользователю переходить между различными приложениями без повторной аутентификации.
- **Dex** — федеративный OpenID Connect (OIDC) провайдер, который выступает посредником между ArgoCD и внешними Identity Providers (IdP).
- **OIDC (OpenID Connect)** — протокол идентификации на базе OAuth 2.0.
- **RBAC (Role-Based Access Control)** — механизм разграничения прав доступа на основе ролей, сопоставленных с группами пользователей.

## Базовые концепции

### Архитектура взаимодействия
1. **Запрос:** Пользователь инициирует вход в веб-интерфейсе ArgoCD.
2. **Редирект:** `argocd-server` перенаправляет запрос к `argocd-dex-server`.
3. **Аутентификация:** Dex перенаправляет пользователя в GitLab.
4. **Токен:** После успешного входа GitLab возвращает OIDC-токен серверу Dex.
5. **Авторизация:** Dex извлекает Claims (email, группы) и передает их в ArgoCD, который применяет политики из `argocd-rbac-cm`.

### Требования
- ArgoCD версии 2.x или 3.x.
- Доступ к GitLab (SaaS или Self-managed).
- Настроенный внешний URL для ArgoCD (обязательно HTTPS).

## Практические сценарии

### Шаг 1: Регистрация приложения в GitLab

1. В GitLab перейдите в **Settings → Applications** (на уровне инстанса или конкретной группы).
2. Заполните параметры:
   - **Name**: `ArgoCD`.
   - **Redirect URI**: `https://<argocd-url>/api/dex/callback`.
   - **Confidential**: `Yes` (включено).
   - **Scopes**: `openid`, `profile`, `email`, `read_api`.
3. Сохраните **Application ID** и **Secret**.

### Шаг 2: Хранение секрета в Kubernetes

Для обеспечения безопасности `clientSecret` рекомендуется хранить в `argocd-secret`.

**Вариант А: Редактирование существующего секрета**
```bash
# Кодирование секрета в base64
echo -n "ваш_секрет_gitlab" | base64

# Добавление в argocd-secret
kubectl edit secret -n argocd argocd-secret
```
Добавьте поле `gitlab.clientSecret` в секцию `data`.

**Вариант Б: Декларативный манифест (External Secrets / SOPS)**
Если вы используете GitOps для секретов, определите поле в `stringData`:
```yaml
stringData:
  gitlab.clientSecret: "ваш_секрет_gitlab"
```

### Шаг 3: Настройка коннектора в ConfigMap

Отредактируйте `argocd-cm` для настройки связи с GitLab.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  url: https://argocd.example.com
  dex.config: |
    connectors:
      - type: gitlab
        id: gitlab
        name: GitLab
        config:
          baseURL: https://gitlab.example.com # URL вашего GitLab инстанса
          clientID: <application_id>
          clientSecret: $gitlab.clientSecret
          # Дополнительные настройки для безопасности и групп:
          requestedScopes: ["openid", "profile", "email", "groups"]
          # Настройка для вложенных групп (v3.x)
          # groupMemberAttributes: true
```

**Примечание для Self-managed GitLab с внутренним CA:**
Если GitLab использует самоподписанный сертификат, добавьте корневой сертификат в `argocd-cm`:
```yaml
dex.config: |
  logger:
    level: debug
  connectors:
    - type: gitlab
      ...
      config:
        rootCAData: <base64_encoded_ca_cert>
```

### Шаг 4: Настройка политик доступа (RBAC)

Маппинг групп GitLab на роли ArgoCD выполняется в `argocd-rbac-cm`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Группа 'infra-admins' получает полные права
    g, "infra/kubernetes-admins", role:admin
    
    # Кастомная роль для разработчиков проекта 'shop'
    p, role:dev-shop, applications, get, shop/*, allow
    p, role:dev-shop, applications, sync, shop/*, allow
    
    # Маппинг вложенной группы GitLab на роль
    g, "shop-team/backend-devs", role:dev-shop
```

*Важно: Названия групп в GitLab при использовании OIDC передаются как полные пути (`path/to/group`).*

## Диагностика и устранение неисправностей

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Invalid redirect URI** | Несоответствие URL в GitLab и `argocd-cm`. | Проверьте наличие завершающего слэша и протокола HTTPS. |
| **Internal Server Error (500)** | Ошибка связи с GitLab или неверный Secret. | Проверьте логи пода `argocd-dex-server`. |
| **Пользователь залогинился, но нет прав** | Ошибка в маппинге групп в `policy.csv`. | Проверьте точное написание группы во вкладке **User Info** в ArgoCD. |

### Полезные команды для отладки

```bash
# Проверка логов Dex (самый важный источник информации)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server

# Проверка конфигурации RBAC в реальном времени
argocd admin settings rbac
```

## Дополнительная информация

### Использование нескольких коннекторов
Dex позволяет одновременно настроить несколько провайдеров (например, GitLab для сотрудников и Google для подрядчиков). Каждый коннектор должен иметь уникальный `id`.

**Связанные документы:**
- [ArgoCD: Установка и настройка HA](./argocd_installation_and_setup.md)
- [Диагностика и мониторинг ArgoCD](./argocd_troubleshooting_and_monitoring.md)

**Официальные ресурсы:**
- [ArgoCD OIDC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/gitlab/)
- [Dex GitLab Connector Specs](https://dexidp.io/docs/connectors/gitlab/)


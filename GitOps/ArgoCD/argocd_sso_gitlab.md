# ArgoCD: Настройка SSO через GitLab

Настройка Single Sign-On (SSO) в ArgoCD через GitLab позволяет централизованно управлять доступом пользователей, используя существующие учетные записи и группы GitLab. Для реализации используется встроенный сервер **Dex**.

## Определения

- **SSO (Single Sign-On)** — технология единого входа, позволяющая пользователю переходить между различными приложениями без повторной аутентификации.
- **Dex** — федеративный OpenID Connect (OIDC) провайдер, который выступает посредником между ArgoCD и внешними IdP (GitLab, GitHub, LDAP).
- **RBAC (Role-Based Access Control)** — механизм разграничения прав доступа в ArgoCD на основе ролей, сопоставленных с группами пользователей из GitLab.

## Базовые концепции

### Механизм работы
1. Пользователь выбирает «LOGIN VIA GITLAB» в интерфейсе ArgoCD.
2. ArgoCD перенаправляет пользователя в GitLab для аутентификации.
3. После успешного входа GitLab возвращает OIDC-токен серверу Dex.
4. Dex извлекает информацию о пользователе и его группах.
5. ArgoCD применяет политики RBAC на основе полученных групп.

### Требования
- Установленный ArgoCD в кластере Kubernetes.
- Права администратора в GitLab.
- Доступ к кластеру через `kubectl`.

## Практические сценарии

### Шаг 1: Регистрация приложения в GitLab

1. В веб-интерфейсе GitLab перейдите в **Menu → Admin → Applications**.
2. Нажмите **New application**.
3. Заполните поля:
   - **Name**: `ArgoCD`.
   - **Redirect URI**: `https://<argocd-url>/api/dex/callback` (обязательно HTTPS).
   - **Scopes**: выберите `read_user` и `openid`.
4. После сохранения вы получите **Application ID** и **Secret**. Сохраните их.

### Шаг 2: Создание Secret для клиента

Для безопасного хранения секрета GitLab необходимо создать или обновить `argocd-secret`.

1. Закодируйте секрет GitLab в base64 (используйте `echo -n`, чтобы избежать лишних символов новой строки):
   ```bash
   echo -n "ваш_секрет_gitlab" | base64
   ```
2. Добавьте значение в Secret кластера:
   ```bash
   kubectl edit secret -n argocd argocd-secret
   ```
   Добавьте в секцию `data`:
   ```yaml
   data:
     gitlab.clientSecret: <base64_encoded_secret>
   ```

### Шаг 3: Настройка ConfigMap для Dex

Отредактируйте `argocd-cm` для включения коннектора GitLab.

```bash
kubectl edit configmap argocd-cm -n argocd
```

Добавьте конфигурацию в секцию `data`:
```yaml
data:
  url: https://argocd.example.com/
  dex.config: |
    connectors:
      - type: gitlab
        id: gitlab
        name: GitLab
        config:
          baseURL: https://gitlab.example.com
          clientID: <application_id>
          clientSecret: $gitlab.clientSecret
```

### Шаг 4: Разграничение прав доступа (RBAC)

Настройка ролей на основе групп GitLab выполняется в `argocd-rbac-cm`.

```bash
kubectl edit configmap argocd-rbac-cm -n argocd
```

Пример конфигурации с разделением на админов и пользователей:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Группе 'devops' из GitLab даем роль admin
    g, devops, role:admin
    
    # Кастомная роль для разработчиков
    p, role:dev-team, applications, *, */*, allow
    p, role:dev-team, clusters, get, *, allow
    p, role:dev-team, repositories, get, *, allow
    
    # Привязка группы 'gitlab-group-name' к кастомной роли
    g, gitlab-group-name, role:dev-team
```

*Примечание: Группы в GitLab должны точно совпадать по названию с указанными в `policy.csv`.*

## Дополнительная информация

### Проверка конфигурации
После внесения изменений серверы ArgoCD автоматически подхватят конфигурацию. Если кнопка «Log in via GitLab» не появилась или выдает ошибку:
1. Проверьте логи пода `argocd-dex-server`.
2. Убедитесь, что `Redirect URI` в GitLab совпадает с `url` в `argocd-cm`.
3. Проверьте вкладку **User Info** в ArgoCD после входа — там будут перечислены группы, которые Dex получил от GitLab.

**Связанные документы:**
- [ArgoCD: Установка и настройка](./argocd_installation_and_setup.md)
- [ArgoCD: Обзор системы](./argocd_overview.md)
- [Диагностика RBAC](./argocd_troubleshooting_and_monitoring.md)

**Официальные ресурсы:**
- [ArgoCD SSO Documentation](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/)
- [Dex GitLab Connector](https://dexidp.io/docs/connectors/gitlab/)

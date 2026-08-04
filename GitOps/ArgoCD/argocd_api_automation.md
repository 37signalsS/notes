# ArgoCD: Автоматизация через API и Ansible

Управление ArgoCD через REST API позволяет автоматизировать жизненный цикл приложений в разнородных инфраструктурах (облака, Kubernetes, Bare Metal). Использование Ansible в связке с API обеспечивает декларативный подход к управлению самими объектами ArgoCD.

## Определения

- **ArgoCD API**: RESTful интерфейс для управления всеми ресурсами ArgoCD (Applications, Projects, Clusters).
- **API Token**: JWT-токен (JSON Web Token) для аутентификации запросов к API.
- **Ansible `uri` module**: Модуль Ansible для взаимодействия с HTTP/HTTPS API.
- **Swagger**: Встроенная интерактивная документация API, доступная по адресу `https://<argocd-url>/swagger-ui`.

## Базовые концепции

### Управление токенами (Authentication)

Для взаимодействия с API требуется токен доступа. Существует два основных способа его получения:

#### 1. Временный токен (Session)
Генерируется через API-запрос с использованием учетных данных пользователя.
```bash
curl $ARGOCD_SERVER/api/v1/session -d '{"username":"admin","password":"your_password"}'
```

#### 2. Постоянный токен (API Key)
Для автоматизации рекомендуется использовать постоянные токены, привязанные к аккаунтам.
1. **Настройка аккаунта**: В `argocd-cm` (ConfigMap) добавьте возможность использования API-ключей для пользователя:
   ```yaml
   data:
     accounts.admin: apiKey, login
   ```
2. **Перезапуск**: Выполните рестарт `argocd-server`.
3. **Генерация в UI**: `Settings -> Accounts -> admin -> Generate New Token`.

## Практические сценарии

### Сценарий 1: Управление приложениями через cURL

Экспортируйте токен:
```bash
export ARGOCD_TOKEN="ваш_токен"
```

**Создание приложения (Helm):**
```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "metadata": {"name": "test-api-app", "namespace": "argocd"},
    "spec": {
      "project": "default",
      "source": {
        "repoURL": "https://github.com/example/charts.git",
        "path": "my-chart",
        "targetRevision": "main"
      },
      "destination": {
        "server": "https://kubernetes.default.svc",
        "namespace": "target-ns"
      },
      "syncPolicy": {
        "automated": {"prune": true, "selfHeal": true}
      }
    }
  }' https://<argocd-url>/api/v1/applications
```

**Удаление приложения:**
```bash
curl -X DELETE -H "Authorization: Bearer $ARGOCD_TOKEN" \
  https://<argocd-url>/api/v1/applications/test-api-app
```

### Сценарий 2: Интеграция Ansible с ArgoCD

Использование модуля `uri` позволяет интегрировать управление приложениями ArgoCD в общие плейбуки развертывания инфраструктуры.

#### Структура роли `app-k8s-deploy`
```text
roles/app-k8s-deploy/
├── defaults/
│   └── main.yaml      # Переменные (URL, токен, имя приложения)
├── tasks/
│   ├── main.yaml      # Переключатель задач
│   ├── create.yaml    # Реализация POST запроса
│   └── delete.yaml    # Реализация DELETE запроса
```

**Пример `defaults/main.yaml`:**
```yaml
ARGOCD_URL: "https://argocd.example.com"
ARGOCD_TOKEN: ""  # Рекомендуется передавать через Vault
APP_NAME: "test-api-app"
```

**Пример `tasks/main.yaml` (Диспетчер):**
```yaml
- name: Include create application tasks
  include_tasks: create.yaml
  when: task == 'install'

- name: Include delete application tasks
  include_tasks: delete.yaml
  when: task == 'delete'
```

#### Запуск роли в основном плейбуке
```yaml
- hosts: localhost
  roles:
    - { role: app-k8s-deploy, task: install }
```

## Дополнительная информация

### Безопасность
- Не храните `ARGOCD_TOKEN` в открытом виде. Используйте **[Ansible Vault](../../Ansible/Vault/basics.md)**.
- Ограничивайте права аккаунта, используемого для API, через **[RBAC политики](./argocd_sso_gitlab.md#шаг-4-разграничение-прав-доступа-rbac)**.

**Связанные документы:**
- [ArgoCD: Обзор системы](./argocd_overview.md)
- [ArgoCD: Настройка SSO и RBAC](./argocd_sso_gitlab.md)
- [Ansible: Использование Vault](../../Ansible/Vault/basics.md)

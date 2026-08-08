# ArgoCD: Автоматизация через API и Ansible

Управление ArgoCD через программные интерфейсы (REST и gRPC) позволяет автоматизировать жизненный цикл приложений в разнородных инфраструктурах. Использование Ansible в связке с API обеспечивает декларативный подход к управлению конфигурацией самого ArgoCD.

## Определения

- **ArgoCD REST API** — HTTP-интерфейс для управления всеми ресурсами ArgoCD (Applications, Projects, Clusters).
- **ArgoCD gRPC API** — высокопроизводительный бинарный интерфейс, используемый CLI-клиентом по умолчанию.
- **Service Account (SA)** — специальный тип аккаунта в ArgoCD для программного доступа, не привязанный к конкретному пользователю.
- **API Token** — JWT-токен (JSON Web Token) для аутентификации запросов.
- **Ansible Collection `argoproj.argocd`** — официальный набор модулей для управления ресурсами ArgoCD.

## Базовые концепции

### Методы аутентификации

Для программного взаимодействия требуется токен доступа. В современных версиях ArgoCD (v2.0+) рекомендуется использовать **Service Accounts**.

#### 1. Сервисные аккаунты (Service Accounts)
Это предпочтительный метод для CI/CD систем.
1. **Создание SA:** Добавьте аккаунт в `argocd-cm` ConfigMap.
   ```yaml
   data:
     accounts.github-actions: apiKey
   ```
2. **Назначение прав:** В `argocd-rbac-cm` свяжите аккаунт с ролью.
   ```yaml
   data:
     policy.csv: |
       p, role:ci-bot, applications, sync, *, allow
       g, github-actions, role:ci-bot
   ```
3. **Генерация токена:**
   ```bash
   argocd account generate-token --account github-actions
   ```

#### 2. Временная сессия (User Session)
Используется для разовых задач от имени пользователя.
```bash
curl -s -X POST $ARGOCD_SERVER/api/v1/session -d '{"username":"admin","password":"password"}' | jq -r .token
```

### Сравнение протоколов: REST vs gRPC

| Протокол | Назначение | Особенности |
| :--- | :--- | :--- |
| **REST (HTTP/JSON)** | Интеграция с внешними скриптами, cURL, Ansible. | Прост в использовании, работает через стандартные HTTP-клиенты. |
| **gRPC (HTTP/2)** | Внутреннее взаимодействие, работа через `argocd` CLI. | Высокая производительность, требует специальных клиентских библиотек. |

*Примечание: Если ArgoCD находится за прокси-сервером, не поддерживающим HTTP/2, используйте флаг `--grpc-web` в CLI или REST API.*

## Практические сценарии

### Сценарий 1: Управление ресурсами через cURL

Экспортируйте токен: `export ARGOCD_TOKEN="ваш_токен"`

**Создание AppProject:**
```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "project": {
      "metadata": {"name": "prod-project"},
      "spec": {
        "destinations": [{"server": "https://kubernetes.default.svc", "namespace": "prod"}],
        "sourceRepos": ["https://github.com/my-org/*"]
      }
    }
  }' $ARGOCD_SERVER/api/v1/projects
```

**Принудительная синхронизация приложения:**
```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications/my-app/sync
```

### Сценарий 2: Использование Ansible Collection

Официальная коллекция `argoproj.argocd` позволяет управлять приложениями без написания низкоуровневых HTTP-запросов.

**Установка коллекции:**
```bash
ansible-galaxy collection install argoproj.argocd
```

**Пример плейбука для создания приложения:**
```yaml
- hosts: localhost
  tasks:
    - name: Create ArgoCD Application
      argoproj.argocd.app:
        name: guestbook
        namespace: argocd
        repo_url: https://github.com/argoproj/argocd-example-apps.git
        path: guestbook
        dest_namespace: default
        dest_server: https://kubernetes.default.svc
        project: default
        sync_policy:
          automated:
            prune: true
            self_heal: true
        auth_token: "{{ lookup('env', 'ARGOCD_TOKEN') }}"
        server_url: "{{ lookup('env', 'ARGOCD_SERVER') }}"
```

## Дополнительная информация

### Безопасность
- **Ansible Vault:** Всегда шифруйте токены доступа. Никогда не фиксируйте их в Git в открытом виде.
- **Принцип минимальных привилегий:** Используйте Service Accounts с узкоспециализированными RBAC-ролями вместо токена администратора.
- **Изоляция API:** Рекомендуется ограничить доступ к API ArgoCD на уровне сети (Ingress Allow-list) только доверенными IP-адресами (например, раннерами CI).

**Связанные документы:**
- [ArgoCD: Обзор системы](./argocd_overview.md)
- [ArgoCD: Настройка SSO и RBAC](./argocd_sso_gitlab.md)
- [Ansible: Использование Vault](../../Ansible/Vault/basics.md)

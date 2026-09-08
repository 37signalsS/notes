# Веб-интерфейсы Kubernetes: Dashboard, Headlamp и альтернативы

## Определения

**Kubernetes Dashboard** — исторически первый официальный веб-интерфейс для управления кластерами. К 2026 году проект официально переведен в статус **Retired** (архивирован) и не рекомендуется для использования в новых инсталляциях из-за прекращения поддержки безопасности.

**Headlamp** — современный, расширяемый веб-интерфейс, являющийся официальным преемником Dashboard в рамках CNCF Sandbox. Оптимизирован для мультикластерности, глубокой интеграции RBAC и расширения функционала через плагины.

**Lens (Lens Desktop)** — графическая IDE для Kubernetes, работающая как десктопное приложение. Фокусируется на удобстве разработчиков и SRE, предоставляя "единое окно" для всех кластеров без необходимости установки агентов внутри кластера.

**k9s** — терминальный интерфейс (TUI), стандарт де-факто для быстрой навигации и отладки через CLI.

## Основные концепции

### Сравнение решений для управления кластером

| Параметр | Headlamp (Стандарт) | Lens (IDE) | k9s (TUI) | Dashboard (Legacy) |
| :--- | :--- | :--- | :--- | :--- |
| **Среда запуска** | In-cluster / Desktop | Desktop (Local) | Terminal (Local) | In-cluster |
| **Тип интерфейса** | Web UI / Desktop | GUI (Desktop App) | Terminal (TUI) | Web UI |
| **Мультикластерность** | Родная поддержка | Отличная | Через переключение контекстов | Отсутствует |
| **Безопасность** | Строгий RBAC + OIDC | Использует локальный kubeconfig | Использует локальный kubeconfig | Высокий риск (токены/прокси) |
| **Расширяемость** | Плагины на JS/TS | Встроенные расширения и GitOps-интеграции | Ограниченная (алиасы, skins) | Нет |
| **Статус проекта** | Активен (Рекомендован) | Активен (Proprietary/OSS) | Активен (OSS) | **Архивирован (2026)** |

### Архитектура и безопасность Headlamp

В отличие от старого Dashboard, Headlamp не требует привилегированного ServiceAccount для своей работы. Он выступает как прокси, передающий запросы к Kubernetes API от имени аутентифицированного пользователя.

- **Плагины на JS/TS:** Позволяют добавлять кастомные страницы, столбцы в таблицах или целые модули (например, визуализацию стоимости ресурсов или безопасности).
- **Topology View:** Визуальное представление связей между Pod, Service, Ingress и NetworkPolicy, что критично для отладки сетевых проблем.
- **Интеграция с OIDC:** Поддержка SSO (Okta, Keycloak, GitHub) позволяет исключить использование небезопасных статических токенов.

## Практические сценарии

### Предварительные требования

- **Kubernetes:** v1.20+ (рекомендуется v1.28+ для Headlamp и Lens).
- **kubectl:** версия, совместимая с кластером (`kubectl version --client`).
- **Helm:** v3.12+ для установки Headlamp и Dashboard.
- **Браузер:** Chrome, Firefox, Edge или Safari (для Web UI).
- **Права:** RBAC-разрешения на создание Namespace, ServiceAccount, Role/ClusterRole, Deployment, Service, Ingress/Route.

### Установка Kubernetes Dashboard (legacy)

Проект официально архивирован. Установка возможна только для обратной совместимости:

```bash
helm repo add kubernetes-dashboard https://kubernetes.github.io/dashboard/
helm repo update
helm install kubernetes-dashboard kubernetes-dashboard/kubernetes-dashboard \
  --namespace kubernetes-dashboard \
  --create-namespace \
  --set metricsScraper.enabled=true
```

```bash
# Создание ServiceAccount и ClusterRoleBinding (admin-доступ для тестирования)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml
kubectl create serviceaccount dashboard-admin-sa -n kubernetes-dashboard
kubectl create clusterrolebinding dashboard-admin-sa --clusterrole=cluster-admin --serviceaccount=kubernetes-dashboard:dashboard-admin-sa
kubectl -n kubernetes-dashboard create token dashboard-admin-sa --duration=87600h
```

```bash
# Доступ через kubectl proxy
kubectl proxy
# → http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

⚠️ **Предупреждение:** Использование в production запрещено из-за отсутствияsecurity-патчей. Мигрируйте на Headlamp.

### Развертывание Headlamp в кластере

Рекомендуемый способ установки через Helm:

```bash
helm repo add headlamp https://headlamp-project.github.io/headlamp/
helm install my-headlamp headlamp/headlamp \
  --namespace headlamp \
  --create-namespace \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=headlamp.example.com
```
*# → Создается Namespace, Service, Deployment и Ingress для доступа к интерфейсу.*

### Настройка Headlamp (OIDC и безопасность)

#### Конфигурация OIDC

Для настройки входа через внешний провайдер (например, Keycloak) в `values.yaml` необходимо указать параметры OIDC:

```yaml
config:
  oidc:
    clientID: "headlamp-client"
    clientSecret: "your-secret"
    issuerURL: "https://keycloak.example.com/realms/master"
    scopes: "openid,profile,email,groups"
```

После установки проверьте, что Secret `headlamp-oidc-secret` создан в namespace `headlamp`.

#### ServiceAccount и RBAC

Headlamp работает от имени аутентифицированного пользователя, но для доступа к Namespace в режиме in-cluster требуется ServiceAccount:

```bash
# Проверка ServiceAccount
kubectl get sa -n headlamp
kubectl describe sa headlamp -n headlamp

# Проверка прав (пример)
kubectl auth can-i get pods --as=system:serviceaccount:headlamp:headlamp -n production
```

**Рекомендация:** Используйте отдельный ClusterRole с минимальными правами вместо `cluster-admin`.

#### NetworkPolicy

Ограничьте сетевой доступ к Headlamp только из доверенных подсетей:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: headlamp-ingress
  namespace: headlamp
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: headlamp
  policyTypes:
    - Ingress
  ingress:
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - protocol: TCP
          port: 80
```

#### TLS

При использовании Ingress убедитесь, что настроен TLS:

```yaml
spec:
  ingress:
    enabled: true
    hosts:
      - host: headlamp.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: headlamp-tls
        hosts:
          - headlamp.example.com
```

### Использование Headlamp Desktop

Если вы не хотите устанавливать ничего в кластер, используйте Desktop-версию:
1. Скачайте приложение с [официального сайта](https://headlamp.dev/).
2. Приложение автоматически подхватит ваши контексты из `~/.kube/config`.
3. Все действия будут выполняться с вашими текущими правами RBAC.

### Lens Desktop

**Lens Desktop** — графическая IDE для Kubernetes, работающая как локальное приложение. Поддерживает мультикластерность, Hotbar, GitOps-навигацию (Flux, Argo CD) и встроенный терминал.

**Установка:**

```bash
# macOS (Homebrew)
brew install --cask freelens   # FreeLens (MIT, без регистрации)
brew install --cask lens       # Lens Desktop (коммерческая)

# Проверка
lens --version
```

**Быстрый старт:**
1. Приложение сканирует `~/.kube/config` и отображает все контексты.
2. Добавление кластера: `File > Add Cluster` (или `⌘/Ctrl + K`).
3. ПКМ на кластере → **Settings > Metrics** → **Install** для развертывания встроенного Prometheus (Lens Metrics).

**Важно:** Lens не требует установки агентов в кластер. Все операции выполняются через локальный kubeconfig. Детальные сценарии: [Lens — практические сценарии](./ToolsUtilities/lens/practical_scenarios.md).

### Быстрая отладка через k9s

Для мгновенного доступа к логам и ресурсам без браузера:
```bash
k9s --context prod-cluster -n my-app
```
`# → Открывается интерактивный интерфейс. Навигация: `:pods` — список подов, `l` — логи, `s` — shell.`

**Продвинутые сценарии k9s:**

```bash
# Алиасы (создайте ~/.config/k9s/config.yaml)
alias:
  pods: po
  deployments: deploy
  services: svc

# Автодополнение для bash/zsh
echo 'source <(k9s completion bash)' >> ~/.bashrc

# Просмотр событий кластера
k9s --context prod-cluster -n kube-system
# → :ev  (events)
# → :ns  (переключение namespace)

# Фильтрация подов по статусу
/^0/
# → покажет поды с 0/1 Ready

# Просмотр логов с tail
l -t
# → лог с автообновлением

# Редактирование ресурса на лету
e
# → открывает $EDITOR для манифеста

# Port-forward через UI
Shift+f
# → введите pod, порт и целевой порт
```

### Перенос ресурсов из Dashboard в Headlamp

При миграции со старого Dashboard:
1. **Удаление Dashboard:** `kubectl delete ns kubernetes-dashboard`.
2. **Проверка RBAC:** Убедитесь, что у пользователей настроены Role/ClusterRole, так как Headlamp строго следует правам текущего пользователя, а не использует "админский" токен интерфейса.

### Troubleshooting

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Headlamp: 503 Service Unavailable** | Под не готов или нет ингресса | `kubectl get pods -n headlamp` | Проверить readiness probe, проверить Ingress Controller |
| **Headlamp: OIDC redirect loop** | Неверный issuerURL или scopes | Логи пода: `kubectl logs -n headlamp deploy/headlamp` | Сверить `issuerURL` с конфигурацией IdP, добавить `offline_access` в scopes |
| **Headlamp: нет прав на namespace** | RBAC ограничения | `kubectl auth can-i list pods --as=user@example.com -n ns` | Назначить RoleBinding в целевом namespace |
| **Lens: metrics not available** | Отсутствует Prometheus или kube-state-metrics | Проверить Pods в namespace `lens-metrics` | Установить Lens Metrics или настроить Custom Prometheus |
| **Lens: high memory usage** | Слишком много активных кластеров | Мониторинг ОЗУ в macOS Activity Monitor / Windows Task Manager | Отключить неиспользуемые кластеры (ПКМ → Disconnect) |
| **k9s: cannot connect to cluster** | Неверный контекст или недоступен API | `kubectl cluster-info` | Проверить `KUBECONFIG`, доступность API, срок действия токена |
| **k9s: logs not showing** | Контейнер не запущен или stdout пустой | `kubectl logs pod -c container` | Проверить `logging` драйвер контейнера, наличие логов в `docker/crictl` |
| **Dashboard (legacy): token expired** | Токен SA имеет короткий TTL | `kubectl describe sa dashboard-admin-sa` | Пересоздать токен или использовать `create token` с `--duration` |

### Best Practices

1. **Принцип наименьших привилегий:** Никогда не используйте `cluster-admin` для интерфейсов мониторинга. Создавайте отдельные ClusterRole с минимально необходимыми правами (`get`, `list`, `watch`).
2. **Изоляция доступа:** Развертывайте Headlamp в отдельном namespace с NetworkPolicy, ограничивающей источник трафика.
3. **Аутентификация:** Используйте OIDC/OAuth2 вместо статических токенов. Для Desktop-инструментов (Lens, Headlamp Desktop) полагайтесь на локальный kubeconfig с правами текущего пользователя.
4. **Сертификаты:** В production используйте валидные TLS-сертификаты для Ingress/Route. Избегайте самоподписанных сертификатов без явного acceptance.
5. **Аудит:** Включите аудит API-сервера для отслеживания действий, выполненных через веб-интерфейсы.
6. **Резервное копирование:** Регулярно экспортируйте конфигурации RBAC и NetworkPolicy. Headlamp не хранит состояние кластера, но терять доступ к интерфейсу из-за ошибки RBAC недопустимо.

### Очистка

```bash
# Удаление Headlamp
helm uninstall my-headlamp -n headlamp
kubectl delete namespace headlamp

# Удаление Dashboard (legacy)
helm uninstall kubernetes-dashboard -n kubernetes-dashboard
kubectl delete namespace kubernetes-dashboard

# Удаление Lens Metrics (если устанавливали встроенный стек)
kubectl delete namespace lens-metrics

# Удаление k9s конфигурации (при необходимости)
rm -rf ~/.config/k9s
```

## Дополнительная информация

### Тренды 2026 года: Observability и мультикластерность

Современные интерфейсы (Lens, Headlamp) фокусируются на:
- **Единой панели Observability:** интеграция метрик, логов и трейсов без переключения между инструментами.
- **Мультикластерности:** нативное управление десятками кластеров через единый контекст, что критично для платформенных команд.
- **GitOps-навигации:** прямая навигация по ресурсам Flux CD и Argo CD, статус reconcile и история deployments.
- **Admission Policies:** визуализация ValidatingAdmissionPolicy и MutatingAdmissionPolicy с подсветкой CEL-выражений.

### Ссылки

- [Официальный сайт Headlamp](https://headlamp.dev/)
- [Lens Desktop — Kubernetes IDE](https://k8slens.dev/)
- [Репозиторий k9s](https://github.com/derailed/k9s)
- [Архив проекта Kubernetes Dashboard](https://github.com/kubernetes-retired/dashboard)

### См. также

- [Kubernetes — обзор инструментов](./kubernetes_overview.md)
- [RBAC — управление доступом](./Security/rbac/rbac_overview.md)
- [Lens — практические сценарии](./ToolsUtilities/lens/practical_scenarios.md)

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
| **AI-интеграция** | Плагины (Lightspeed и др.) | Встроенный Copilot | Ограниченная | Нет |
| **Статус проекта** | Активен (Рекомендован) | Активен (Proprietary/OSS) | Активен (OSS) | **Архивирован (2026)** |

### Архитектура и безопасность Headlamp

В отличие от старого Dashboard, Headlamp не требует привилегированного ServiceAccount для своей работы. Он выступает как прокси, передающий запросы к Kubernetes API от имени аутентифицированного пользователя.

- **Плагины на JS/TS:** Позволяют добавлять кастомные страницы, столбцы в таблицах или целые модули (например, визуализацию стоимости ресурсов или безопасности).
- **Topology View:** Визуальное представление связей между Pod, Service, Ingress и NetworkPolicy, что критично для отладки сетевых проблем.
- **Интеграция с OIDC:** Поддержка SSO (Okta, Keycloak, GitHub) позволяет исключить использование небезопасных статических токенов.

## Практические сценарии

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

### Настройка OIDC (Аутентификация)

Для настройки входа через внешний провайдер (например, Keycloak) в `values.yaml` необходимо указать параметры OIDC:

```yaml
config:
  oidc:
    clientID: "headlamp-client"
    clientSecret: "your-secret"
    issuerURL: "https://keycloak.example.com/realms/master"
    scopes: "openid,profile,email,groups"
```

### Использование Headlamp Desktop

Если вы не хотите устанавливать ничего в кластер, используйте Desktop-версию:
1. Скачайте приложение с [официального сайта](https://headlamp.dev/).
2. Приложение автоматически подхватит ваши контексты из `~/.kube/config`.
3. Все действия будут выполняться с вашими текущими правами RBAC.

### Быстрая отладка через k9s

Для мгновенного доступа к логам и ресурсам без браузера:
```bash
k9s --context prod-cluster -n my-app
```
*# → Открывается интерактивный интерфейс. Навигация: `:pods` — список подов, `l` — логи, `s` — shell.*

### Перенос ресурсов из Dashboard в Headlamp

При миграции со старого Dashboard:
1. **Удаление Dashboard:** `kubectl delete ns kubernetes-dashboard`.
2. **Проверка RBAC:** Убедитесь, что у пользователей настроены Role/ClusterRole, так как Headlamp строго следует правам текущего пользователя, а не использует "админский" токен интерфейса.

## Дополнительная информация

### Тренды 2026 года: AI и Наблюдаемость

Современные интерфейсы (Lens, Headlamp) активно интегрируют AI-ассистентов, которые могут:
- Объяснять причины `CrashLoopBackOff` на основе анализа логов и событий.
- Предлагать исправления для YAML-манифестов.
- Генерировать топологические карты зависимостей в реальном времени.

### Ссылки

- [Официальный сайт Headlamp](https://headlamp.dev/)
- [Lens Desktop — Kubernetes IDE](https://k8slens.dev/)
- [Репозиторий k9s](https://github.com/derailed/k9s)
- [Архив проекта Kubernetes Dashboard](https://github.com/kubernetes-retired/dashboard)

### См. также

- [Kubernetes — обзор инструментов](./kubernetes_overview.md)
- [RBAC — управление доступом](./Security/rbac/rbac_overview.md)
- [OIDC в Kubernetes — концепции аутентификации](./Security/authentication.md)
- [Lens — практические сценарии](./ToolsUtilities/lens/practical_scenarios.md)

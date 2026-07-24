# Веб-интерфейсы Kubernetes: Dashboard и Headlamp

## Определение

**Kubernetes Dashboard** — исторически первый официальный веб-интерфейс для управления кластерами Kubernetes. Позволяет визуализировать ресурсы кластера, управлять приложениями и выполнять базовую диагностику.

**Headlamp** — современный, расширяемый веб-интерфейс и официальный преемник Dashboard в рамках инициативы Kubernetes SIG UI. Поддерживает мультикластерность, плагины и обладает более совершенной моделью безопасности.

> **Важное уведомление о статусе (2026 г.):**
> Проект Kubernetes Dashboard официально архивирован (21.01.2026) и перенесён в репозиторий `kubernetes-retired`. Он больше не получает обновлений безопасности и исправлений ошибок. Для всех новых установок и производственных сред **настоятельно рекомендуется использовать Headlamp**.

## Основные концепции

### Сравнение решений

| Параметр | Kubernetes Dashboard (Legacy) | Headlamp (Рекомендуется) |
| :--- | :--- | :--- |
| **Статус** | Архивом (Retired) | Активен (CNCF Sandbox) |
| **Управление** | Только один кластер | Мультикластерный интерфейс |
| **Расширяемость** | Отсутствует | Система плагинов (JS/TS) |
| **Аутентификация** | Токены, Kubeconfig (сложно) | Нативная поддержка OIDC, SSO |
| **Интерфейс** | Только Web | Web + Desktop (Linux, Mac, Win) |
| **Безопасность** | Высокий риск при неверной настройке | Строгое соблюдение RBAC |

### Аутентификация в Headlamp

Headlamp использует стандартные механизмы Kubernetes, но делает процесс входа более интуитивным:
- **ID Token (OIDC):** Интеграция с корпоративными провайдерами (Okta, Keycloak, Google).
- **Service Account Token:** Вход через токен конкретного пользователя.
- **Kubeconfig:** Загрузка локального файла конфигурации для быстрого доступа.

## Практические сценарии

### Установка Headlamp (Рекомендуемый способ)

Для развертывания в кластере используйте Helm:

```bash
helm repo add headlamp https://headlamp-project.github.io/headlamp/
helm install my-headlamp headlamp/headlamp --namespace headlamp --create-namespace
```

После установки сервис будет доступен внутри кластера. Для внешнего доступа настройте Ingress или используйте `kubectl port-forward`.

### Использование Kubernetes Dashboard (Только для поддержки Legacy)

Если в вашей инфраструктуре всё ещё используется старый Dashboard, обеспечьте его безопасность через `kubectl proxy`.

#### Доступ через прокси (Безопасный метод)

1. **Запуск прокси на локальной машине:**
   ```bash
   kubectl proxy
   ```

2. **Доступ по URL:**
   `http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https-kubernetes-dashboard:/proxy/`

#### Создание административного токена (K8s 1.24+)

Для входа в старый интерфейс часто требуется токен с правами администратора:

1. **Создание ServiceAccount:**
   ```bash
   kubectl -n kubernetes-dashboard create serviceaccount admin-user
   ```

2. **Привязка роли Cluster Admin:**
   ```bash
   kubectl create clusterrolebinding admin-user --clusterrole=cluster-admin --serviceaccount=kubernetes-dashboard:admin-user
   ```

3. **Генерация токена:**
   ```bash
   kubectl -n kubernetes-dashboard create token admin-user
   ```

### Устранение неполадок

#### Headlamp: Ошибка подключения к API
- **Причина:** CORS-политики или неверный контекст в Kubeconfig.
- **Решение:** Проверьте доступность API-сервера с узла, где запущен Headlamp, и убедитесь, что сертификаты валидны.

#### Dashboard: Ошибка 401 Unauthorized
- **Причина:** Истёк срок действия токена ServiceAccount.
- **Решение:** Сгенерируйте новый токен командой `kubectl create token`. Помните, что в новых версиях K8s токены имеют ограниченное время жизни по умолчанию.

## Дополнительная информация

### Ссылки

- [Официальный сайт Headlamp](https://headlamp.dev/)
- [Документация по плагинам Headlamp](https://headlamp.dev/docs/latest/development/plugins/)
- [Архив проекта Kubernetes Dashboard](https://github.com/kubernetes-retired/dashboard)

### См. также

- [Kubespray — примеры установки интерфейсов](../Installation/Kubespray/examples.md)
- [Namespace — изоляция ресурсов](./Base/namespace.md)
- [Minikube — использование встроенных аддонов](./Installation/minikube/minikube_practical_scenarios.md)

# Решение проблем при установке GitLab в Kubernetes

Руководство по диагностике и устранению типичных ошибок, возникающих при развертывании GitLab через официальный Helm-чарт.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **CrashLoopBackOff** | Статус пода, при котором контейнер запускается и сразу завершается с ошибкой, после чего Kubernetes пытается его перезапустить. |
| **PVC Pending** | Состояние запроса на хранилище, при котором том не может быть выделен из-за отсутствия StorageClass или свободных ресурсов. |
| **Shared Secrets** | Набор ключей и паролей (rails-secret, gitaly-token и др.), которые должны быть идентичны во всех компонентах GitLab для корректного взаимодействия. |
| **Initial Root Password** | Временный пароль администратора, генерируемый при первой установке и хранящийся в секрете Kubernetes. |
| **Database Migrations** | Процесс обновления схемы базы данных, выполняемый отдельным Job (`gitlab-migrations`) перед запуском основных сервисов. |

---

## Основные концепции

### Типология ошибок GitLab

Сбои при установке GitLab в Kubernetes обычно делятся на три уровня:
1.  **Инфраструктурный уровень:** Ошибки планирования (Resources), хранилищ (PVC) и сети (LoadBalancer).
2.  **Уровень зависимостей:** Проблемы с запуском встроенных или внешних PostgreSQL, Redis, MinIO и Gitaly.
3.  **Прикладной уровень:** Ошибки миграций базы данных, невалидные конфигурации в `values.yaml`, конфликты секретов.

### Цепочка зависимостей при запуске

Для успешного старта веб-интерфейса компоненты должны запускаться в строго определенном порядке:
`Storage/PV → PostgreSQL/Redis → gitlab-migrations (Job) → Gitaly → Webservice (Puma) / Sidekiq`.
Если `gitlab-migrations` не завершится успешно, основные поды приложения не перейдут в состояние `Ready`.

---

## Практические сценарии

### Ошибки миграции базы данных (Job Failed)

**Симптом:** Поды `webservice` и `sidekiq` находятся в `Running`, но `Ready 0/1`. При этом под `gitlab-migrations` имеет статус `Error`.

**Диагностика:**
```bash
# Поиск упавшего Job миграций
kubectl get pods -l app=migrations -n gitlab

# Просмотр логов миграций для выявления причины (например, тайм-аут или ошибка SQL)
kubectl logs -l app=migrations -n gitlab --tail=100
```

**Решение:** Если база данных была изменена вручную или установка была прервана, может потребоваться ручной перезапуск Job или очистка БД.

### Конфликты секретов (Shared Secrets Mismatch)

**Симптом:** Ошибки "401 Unauthorized" между компонентами или "Invalid Token" в логах Sidekiq/Puma.

**Причина:** При переустановке GitLab без полной очистки или при ручном создании секретов возникло расхождение ключей.

**Решение:** Принудительно обновите секреты или убедитесь, что они генерируются чартом согласованно.
```bash
# Просмотр существующих секретов
kubectl get secrets -n gitlab -l release=gitlab

# Рекомендуется использовать один секрет для всех rails-компонентов
# через параметр global.appConfig.defaults.secret
```

### Проблемы с хранилищем (PVC Pending)

**Симптом:** Поды в статусе `Pending`, PVC в статусе `Pending`.

**Диагностика:**
```bash
# Проверка причин ожидания PVC
kubectl describe pvc <pvc_name> -n gitlab
```

**Типичные причины:**
1.  **Отсутствие Default StorageClass:** См. `kubectl get sc`.
2.  **Insufficient Space:** Физическое отсутствие места на СХД или узлах.
3.  **Multi-AZ Conflict:** PVC создан в одной зоне доступности, а узел планировщика — в другой.

### Нехватка ресурсов (OOMKilled / Insufficient CPU)

**Симптом:** Поды постоянно перезапускаются (`CrashLoopBackOff`) или не планируются.

**Диагностика:**
```bash
# Проверка OOM событий
kubectl get pods -n gitlab | grep -i oom

# Проверка лимитов и запросов
kubectl describe pod <pod_name> -n gitlab | grep -A 3 Limits
```

**Решение:** Для тестовых сред отключите ресурсоемкие компоненты или уменьшите их лимиты и размеры томов (с осторожностью):

```yaml
# Оптимизация для dev-окружений
prometheus:
  install: false
gitlab-runner:
  install: false
postgresql:
  primary:
    persistence:
      size: 5Gi # Уменьшение с дефолтных 80ГБ
```

### Ошибки Cert-Manager (SSL Issue)

**Симптом:** Браузер выдает ошибку сертификата, а секрет `gitlab-tls` не создается или пуст.

**Диагностика:**
```bash
# Проверка ресурсов cert-manager
kubectl get certificate -n gitlab
kubectl describe challenge -n gitlab
```

**Решение:** Убедитесь, что Ingress-контроллер имеет внешний IP и порт 80 открыт для прохождения проверки Let's Encrypt (HTTP-01 challenge).

---

## Дополнительная информация

### Полезные команды для отладки

| Команда | Описание |
| :--- | :--- |
| `helm status gitlab -n gitlab` | Общий статус релиза и выведенные заметки. |
| `kubectl get events -n gitlab --sort-by='.lastTimestamp'` | Хронология событий в пространстве имен. |
| `kubectl logs -f -l app=webservice -n gitlab -c webservice` | Логи Puma в реальном времени. |

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Методы доступа к GitLab](./gitlab_kubernetes_access.md)
- [Диагностика статуса Pending в Kubernetes](../Troubleshooting/Common_Errors/pod_pending/diagnostics.md)
- [Официальный Troubleshooting Guide GitLab](https://docs.gitlab.com/charts/troubleshooting/)

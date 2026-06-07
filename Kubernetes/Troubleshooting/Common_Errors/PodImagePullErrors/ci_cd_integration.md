# Ошибки загрузки образов (Image Pull Errors): Интеграция с CI/CD

## Определения

**Автоматизация управления секретами** — процесс создания, обновления и распределения `imagePullSecrets` в кластере Kubernetes средствами конвейеров CI/CD (GitLab CI, GitHub Actions) для обеспечения бесперебойного доступа к приватным реестрам.

**Переменные окружения CI/CD** — зашифрованные или встроенные параметры (например, `CI_REGISTRY_PASSWORD`), используемые для аутентификации в реестрах контейнеров без хранения паролей в исходном коде.

---

## Основные концепции

### Роль CI/CD в предотвращении ошибок загрузки

| Проблема | Решение через CI/CD | Описание |
| :--- | :--- | :--- |
| **Unauthorized** | Динамическое обновление секретов | Конвейер обновляет секрет при каждой итерации деплоя, предотвращая использование устаревших данных. |
| **Manifest not found** | Проверка артефактов (Gate) | Pipeline блокирует деплой, если шаг сборки и пуша образа не был завершен успешно. |
| **Namespace isolation** | Изолированное создание секретов | Автоматическое создание необходимых секретов в целевом пространстве имен приложения. |

### Принцип работы конвейера

1. **Сборка и пуш:** Создание образа и его загрузка в Registry.
2. **Подготовка кластера:** Создание или обновление `imagePullSecret` в нужном Namespace.
3. **Привязка:** (Опционально) Обновление `ServiceAccount` для автоматического подтягивания секрета.
4. **Развертывание:** Применение манифестов (Deployment, StatefulSet), использующих новый образ.

---

## Практические сценарии

### Сценарий 1: GitLab CI — создание секрета и деплой

Пример шага деплоя, который гарантирует наличие секрета в кластере перед запуском подов:

```yaml
# .gitlab-ci.yml
deploy_app:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    # Идемпотентное создание секрета
    - kubectl create secret docker-registry regcred \
        --docker-server=$CI_REGISTRY \
        --docker-username=$CI_REGISTRY_USER \
        --docker-password=$CI_REGISTRY_PASSWORD \
        --namespace=$KUBE_NAMESPACE \
        --dry-run=client -o yaml | kubectl apply -f -
    # → secret/regcred configured

    # Привязка к ServiceAccount для упрощения манифестов
    - kubectl patch serviceaccount default \
        -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
        -n $KUBE_NAMESPACE
    # → serviceaccount/default patched

    # Применение манифестов приложения
    - kubectl apply -f k8s/deployment.yaml -n $KUBE_NAMESPACE
    # → deployment.apps/my-app created
```

### Сценарий 2: GitOps (ArgoCD) и внешние секреты

В GitOps-модели (ArgoCD, Flux) императивные команды `kubectl` запрещены. Секреты должны управляться декларативно.

**Рекомендуемый стек:**

- **Sealed Secrets:** Шифрование секретов в Git.
- **External Secrets Operator:** Получение данных из HashiCorp Vault или AWS Secrets Manager.

Пример манифеста для ручного управления (в составе Helm-чарта):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: regcred
  namespace: {{ .Release.Namespace }}
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: {{ .Values.imageCredentials | b64enc }}
```

---

## Дополнительная информация

### Связанные темы

- [Лучшие практики по управлению образами](./best_practices.md) — рекомендации по привязке секретов к ServiceAccount.
- [Распространённые ошибки](./common_errors.md) — детальное описание параметров команды `create secret`.
- [Внешние менеджеры секретов](../../../Kubernetes/Base/secrets/external_managers.md) — интеграция с HashiCorp Vault.

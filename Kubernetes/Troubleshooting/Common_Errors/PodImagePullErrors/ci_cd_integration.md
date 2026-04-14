# Pod Image Pull Errors: Интеграция с CI/CD

## Определения

**CI/CD интеграция (в контексте image pull)** — автоматизация создания и обновления `imagePullSecrets` в Kubernetes на этапе pipeline, чтобы pod'ы имели доступ к приватным registry (GitLab Registry, Harbor, GHCR) без ручного вмешательства.

**CI_REGISTRY, CI_REGISTRY_USER, CI_REGISTRY_PASSWORD** — встроенные перемен GitLab CI, содержащие адрес registry и учётные данные для аутентификации.

---

## Основные концепции

### Почему CI/CD важен для предотвращения Image Pull Errors

| Проблема | Причина | Решение через CI/CD |
| :--- | :--- | :--- |
| `unauthorized` | Secret отсутствует или протёк | Автоматическое создание/обновление secret на каждом деплое |
| `manifest not found` | Образ не собран или не запушен | Gate в pipeline — проверка наличия образа до деплоя |
| Secret в другом namespace | Deploy в другой namespace, чем secret | Создание secret в целевом namespace через переменные |

### Принцип работы

```
CI/CD Pipeline
    ↓
Build & Push образа в Registry
    ↓
Create/Update imagePullSecret в Kubernetes
    ↓
Patch ServiceAccount (автоматическая привязка)
    ↓
Deploy приложения → Pod использует secret автоматически
```

### GitOps-подход (ArgoCD, Flux)

В GitOps-средах imagePullSecrets указываются декларативно в манифестах. ArgoCD/Flux применяют манифесты к кластеру, но **не создают секреты автоматически** — secret должен существовать в целевом namespace до деплоя.

---

## Практические сценарии

### Сценарий 1: GitLab CI — автоматическое создание secret

```yaml
# .gitlab-ci.yml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    # Создание secret через dry-run + apply (идемпотентно)
    - kubectl create secret docker-registry regcred \
        --docker-server=$CI_REGISTRY \
        --docker-username=$CI_REGISTRY_USER \
        --docker-password=$CI_REGISTRY_PASSWORD \
        --namespace=$KUBE_NAMESPACE \
        --dry-run=client -o yaml | kubectl apply -f -
    # Привязка к default ServiceAccount
    - kubectl patch serviceaccount default \
        -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
        -n $KUBE_NAMESPACE
    # Деплой приложения
    - kubectl apply -f deployment.yaml -n $KUBE_NAMESPACE
```

**Преимущества:**

- Идемпотентность — `dry-run=client -o yaml | kubectl apply -f -` обновляет существующий secret
- Автоматическая привязка — все pod'ы с `default` SA получают доступ к registry
- Не требуется хранить credentials в репозитории

### Сценарий 2: ArgoCD — декларативное управление секретами

ArgoCD применяет манифесты из Git, но не выполняет imperative-команды. Порядок действий:

1. **Создать secret отдельно** (через CI/CD, Sealed Secrets, External Secrets Operator):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: regcred
  namespace: my-app
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded-config>
```

1. **Указать imagePullSecrets в манифесте Deployment:**

```yaml
spec:
  template:
    spec:
      containers:
      - name: app
        image: registry.example.com/my-app:1.0
      imagePullSecrets:
      - name: regcred
```

1. **Убедиться, что secret существует до деплоя** — ArgoCD выдаст ошибку, если secret не найден.

**Рекомендация:** Для автоматического создания секретов в GitOps используйте [Sealed Secrets](../../../Kubernetes/Base/secrets/external_managers.md) или [External Secrets Operator](../../../Kubernetes/Base/secrets/external_managers.md).

---

## Дополнительная информация

### Связанные темы

- Создание docker-registry secret: [Common Errors](./common_errors.md#2-проблемы-с-доступом-к-приватному-репозиторию)
- Глобальная привязка imagePullSecrets: [Best Practices](./best_practices.md#сценарий-1-глобальная-настройка-imagepullsecrets)
- Rancher Pipelines (deprecated): [Rancher Pipelines](../../../Rancher/rancher_pipelines.md)
- Werf и imagePullSecrets: [Werf Scenarios](../../../../CI-CD/Tools/werf_scenarios.md)
- Внешние менеджеры секретов: [External Managers](../../../Base/secrets/external_managers.md)

# ArgoCD: Динамические окружения с Crossplane и GitLab CI

Организация динамических окружений (Preview / Feature Environments) через GitOps позволяет автоматически разворачивать изолированные копии приложения и необходимой инфраструктуры (баз данных, очередей) для каждой ветки разработчика.

## Определения

- **Динамическое окружение (Review App)** — временный экземпляр приложения и инфраструктуры, создаваемый под конкретную ветку кода или Merge Request.
- **ApplicationSet** — инструмент ArgoCD для автоматической генерации объектов `Application` на основе шаблонов и внешних источников (генераторов).
- **scmProvider generator** — генератор в ApplicationSet, который отслеживает репозитории в Git-хостингах (GitLab, GitHub) и создает приложения для каждой найденной ветки или PR.
- **Crossplane** — Kubernetes-native инструмент для управления облачными ресурсами (IaC) через стандартные манифесты YAML.

## Базовые концепции

### Логика работы пайплайна

1.  **Триггер:** Разработчик пушит ветку с постфиксом (например, `-dyn`) в репозиторий приложения (`project-backend`).
2.  **GitLab CI:**
    - Сборка Docker-образа и пуш в реестр.
    - Создание ветки в репозитории `manifests` с тем же именем.
    - Обновление тега образа в Helm-values новой ветки репозитория манифестов.
3.  **ArgoCD ApplicationSet:**
    - Обнаруживает новую ветку в репозитории `manifests` через `scmProvider`.
    - Генерирует объект `Application` для этой ветки.
    - Начинает синхронизацию: разворачивает Helm-чарт приложения.
4.  **Инфраструктура (Crossplane):**
    - Helm-чарт приложения включает ресурсы Crossplane (например, `PostgresqlDatabase`).
    - Crossplane обнаруживает эти ресурсы и создает реальную БД в облаке (например, в Yandex Cloud).
5.  **Очистка:** При удалении ветки из Git ArgoCD автоматически удаляет `Application`, что приводит к удалению ресурсов в Kubernetes и связанных ресурсов в облаке через Crossplane.

## Практические сценарии

### 1. Конфигурация ApplicationSet (scmProvider)

Этот манифест настраивает ArgoCD на отслеживание веток в GitLab.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: project-stack-dyn
  namespace: argocd
spec:
  generators:
    - scmProvider:
        cloneProtocol: ssh
        filters:
          - branchMatch: .*PROJECT.*-dyn # Фильтр веток
            repositoryMatch: manifests
        gitlab:
          group: "12345678" # ID группы в GitLab
          allBranches: true
          tokenRef:
            secretName: gitlab-token
            key: token
  template:
    metadata:
      name: "{{branchNormalized}}" # Имя приложения на основе имени ветки
    spec:
      source:
        path: charts/project-stack
        repoURL: https://gitlab.com/manifests.git
        targetRevision: "{{branch}}" # Ветка, из которой берем манифесты
        helm:
          valueFiles:
            - ci/dyn/dyn-values.yaml
          values: |
            project-backend:
              envConfig:
                DATASOURCE_URL: "jdbc:postgresql://db.host:6432/{{branchNormalized}}-db"
      project: project-dyn
      destination:
        namespace: 'argo-app-project-dyn'
        server: https://kubernetes.default.svc
      syncPolicy:
        automated:
          selfHeal: true
          prune: true
        syncOptions:
          - CreateNamespace=true
```

### 2. Динамическая инфраструктура через Crossplane

Пример ресурса для создания базы данных в Yandex Cloud внутри Helm-чарта приложения:

```yaml
apiVersion: mdb.yandex-cloud.jet.crossplane.io/v1alpha1
kind: PostgresqlDatabase
metadata:
  name: {{ .Release.Name }}-db
spec:
  forProvider:
    name: {{ .Release.Name }}-db
    clusterId: {{ .Values.infra.dbClusterId }}
    owner: {{ .Release.Name }}-user
    lcCollate: en_US.UTF-8
    lcType: en_US.UTF-8
  providerConfigRef:
    name: yc-provider
```

### 3. Обработка ограничений (DataTransfer)

Если Crossplane или облачный провайдер имеют ограничения (например, невозможность активации трансфера данных `SNAPSHOT_ONLY` через манифест), используется **init-container** в приложении:

1.  Приложение запускает `init-container` со скриптом.
2.  Скрипт через облачный API активирует необходимые процессы (например, Yandex DataTransfer для клонирования эталонной БД).
3.  После завершения трансфера основной контейнер приложения запускается.

## Преимущества и недостатки

| Плюсы | Минусы / Ограничения |
| :--- | :--- |
| **Полная изоляция:** Каждый разработчик имеет свою БД и окружение. | **Стоимость:** Большое количество облачных ресурсов может быть дорогим. |
| **Автоматизация:** Нет ручных действий по созданию сред. | **Время:** Создание БД и трансфер данных занимают время (от 5 до 15 мин). |
| **Соответствие Git:** Состояние кластера всегда равно состоянию Git. | **Сложность:** Требуется глубокая настройка ArgoCD, Crossplane и CI. |

## Дополнительная информация

**Связанные документы:**
- [Обзор ArgoCD](./argocd_overview.md) — базовые концепции и архитектура.
- [Crossplane: Интеграция с GitOps](../Crossplane/gitops_integration.md) — подробнее об управлении инфраструктурой.
- [GitLab CI: Review Apps](../../CI-CD/GitLab_CI/Tutorials/kubernetes_review_apps.md) — традиционный подход к динамическим средам.

**Официальные ресурсы:**
- [ArgoCD ApplicationSet Documentation](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/)
- [Crossplane Providers](https://marketplace.upbound.io/)

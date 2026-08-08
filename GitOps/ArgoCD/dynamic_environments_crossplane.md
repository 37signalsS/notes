# Argo CD: Динамические окружения с Crossplane и GitLab CI

> **Актуальность (2026):** Динамические окружения (Preview Environments) являются стандартом для зрелых DevOps-команд. Использование связки Argo CD + Crossplane позволяет автоматизировать не только деплой кода, но и создание полноценной облачной инфраструктуры (БД, S3, очереди) для каждой ветки, обеспечивая 100% изоляцию и соответствие состоянию в Git.

## Определения

**Динамическое окружение (Review App / Preview Environment)** — временный, полностью изолированный экземпляр приложения и всей необходимой ему инфраструктуры, создаваемый автоматически для конкретной ветки кода или Merge Request (MR).

**ApplicationSet Controller** — компонент Argo CD, автоматизирующий генерацию объектов `Application`. Позволяет использовать генераторы для массового создания приложений на основе внешних источников.

**scmProvider generator** — специализированный генератор в `ApplicationSet`, который отслеживает API Git-хостингов (GitLab, GitHub, Bitbucket) и динамически создает/удаляет приложения при появлении или удалении веток/PR.

**Crossplane** — Kubernetes-native фреймворк для управления внешними облачными ресурсами через стандартный API Kubernetes (IaC). Позволяет описывать базы данных, кластеры и сети как обычные манифесты YAML.

**ExternalDNS** — инструмент для автоматического управления записями в DNS-провайдерах (Cloudflare, AWS Route53, Yandex DNS) на основе Ingress-ресурсов или сервисов Kubernetes.

## Базовые концепции

### Архитектура и поток данных (Workflow)

1.  **Событие в Git:** Разработчик создает ветку с префиксом `feat/` или пушит в существующий Merge Request.
2.  **CI-пайплайн (GitLab CI):**
    - Сборка Docker-образа с тегом, соответствующим Short Commit SHA.
    - Пуш образа в Container Registry.
    - (Опционально) Обновление метаданных в репозитории конфигураций (GitOps-репозитории).
3.  **Argo CD ApplicationSet:**
    - Постоянно опрашивает GitLab API (через `scmProvider`).
    - Обнаруживает новую ветку и генерирует объект `Application`.
    - `Application` ссылается на Helm-чарт, где описаны и само приложение, и его зависимости (Crossplane resources).
4.  **Инстанцирование инфраструктуры (Crossplane):**
    - Kubernetes-контроллер Crossplane видит новые ресурсы (например, `PostgreSQLInstance`).
    - Выполняет вызовы к облачному API для создания реальных ресурсов.
5.  **Сетевой доступ (DNS):**
    - Ingress-контроллер создает точку входа.
    - `ExternalDNS` автоматически регистрирует запись вида `feat-123.preview.example.com`.
6.  **Жизненный цикл и очистка:**
    - При закрытии Merge Request ветка удаляется.
    - Argo CD обнаруживает отсутствие ветки, удаляет `Application` и все связанные ресурсы (включая облачные).

## Практические сценарии

### Сценарий 1: Конфигурация ApplicationSet для GitLab

Этот манифест является "точкой входа" для автоматизации.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-environments
  namespace: argocd
spec:
  generators:
    - scmProvider:
        gitlab:
          group: "my-org/apps" # Группа проектов
          allBranches: true # Отслеживать все ветки (или фильтровать)
          tokenRef:
            secretName: gitlab-access-token
            key: token
        filters:
          - branchMatch: ^feat/.* # Только ветки с префиксом feat/
  template:
    metadata:
      name: "app-{{branchNormalized}}" # Нормализованное имя ветки для DNS
    spec:
      project: preview-apps
      source:
        repoURL: https://gitlab.com/my-org/manifests.git
        targetRevision: "{{branch}}"
        path: charts/standard-app
        helm:
          values: |
            ingress:
              host: "{{branchNormalized}}.preview.example.com"
            infrastructure:
              databaseName: "{{branchNormalized}}"
      destination:
        namespace: "preview-{{branchNormalized}}"
        server: https://kubernetes.default.svc
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### Сценарий 2: Описание динамической БД (Crossplane + Yandex Cloud)

Ресурс внутри Helm-чарта приложения, который создает изолированную БД.

```yaml
apiVersion: postgresql.managed-kubernetes.yandex.cloud/v1alpha1
kind: Database
metadata:
  name: {{ .Values.infrastructure.databaseName }}
spec:
  forProvider:
    clusterIdRef:
      name: shared-preview-cluster # Использование общего кластера для экономии
    name: {{ .Values.infrastructure.databaseName }}
    owner: db-admin
    lcCollate: en_US.UTF-8
  providerConfigRef:
    name: yc-config
```

### Сценарий 3: Автоматизация DNS и SSL

Для Review Apps критически важен автоматический доступ по HTTPS.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "app.fullname" . }}
  annotations:
    # ExternalDNS подхватит этот хост и создаст запись в Cloudflare/Yandex DNS
    external-dns.alpha.kubernetes.io/hostname: {{ .Values.ingress.host }}
    # Cert-manager выпустит Wildcard или индивидуальный сертификат
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts: [{{ .Values.ingress.host | quote }}]
      secretName: {{ include "app.fullname" . }}-tls
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "app.fullname" . }}
                port: {number: 80}
```

### Сценарий 4: Ограничение ресурсов (ResourceQuota)

Защита кластера от неконтролируемого роста количества временных сред.

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: preview-quota
  namespace: {{ .Release.Namespace }}
spec:
  hard:
    requests.cpu: "500m"
    requests.memory: "1Gi"
    limits.cpu: "2"
    limits.memory: "4Gi"
    count/pods: "10"
    count/services: "5"
```

## Управление стоимостью и очисткой

### Стратегии оптимизации затрат (FinOps)

1.  **Общие ресурсы:** Использование одной инстанции БД (Shared Instance) с разными логическими базами/схемами для Review Apps вместо создания отдельных кластеров.
2.  **TTL (Time To Live):** Автоматическое удаление окружений по истечении времени.
    - *Реализация:* Скрипт в GitLab CI, который удаляет ветки в GitOps-репозитории, если в оригинальном MR не было активности > 3 дней.
3.  **HPA (Horizontal Pod Autoscaler):** Установка минимального количества реплик (например, 1) для всех preview-сред.

### Очистка инфраструктуры

Argo CD гарантирует, что при удалении объекта `Application` будут удалены все дочерние ресурсы в Kubernetes. Благодаря `Finalizers` в Crossplane, облачные ресурсы не будут считаться удаленными в Kubernetes, пока облачный провайдер не подтвердит их физическое уничтожение.

## Технические нюансы и ограничения

| Аспект | Описание / Решение |
| :--- | :--- |
| **Инициализация данных** | Использование `Yandex DataTransfer` или `Job` с `pg_dump` для клонирования эталонной БД при создании новой среды. |
| **Кеширование образов** | Динамические среды генерируют много уникальных образов. Настройте политику очистки (Registry Cleanup Policy) в GitLab/Harbor. |
| **Время старта** | Создание облачной БД может занимать 5-10 минут. Используйте `Health Checks` в Argo CD для визуализации готовности. |
| **Лимиты API** | Слишком частые опросы GitLab API могут привести к Rate Limiting. Настройте `reconcile` интервал в ApplicationSet. |

## Дополнительная информация

### См. также
- [Обзор Argo CD: Продвинутые шаблоны](./argocd_overview.md)
- [Crossplane: Управление облачной инфраструктурой](../Crossplane/gitops_integration.md)
- [GitLab CI: Динамические окружения (Review Apps)](../../CI-CD/GitLab_CI/Tutorials/kubernetes_review_apps.md)
- [ExternalDNS: Интеграция с провайдерами](../../Networking/ServicesAndTools/external_dns_overview.md)

### Ссылки
- [Argo CD ApplicationSet Generator: SCM Provider](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-SCM-Provider/)
- [Crossplane Documentation](https://docs.crossplane.io/)

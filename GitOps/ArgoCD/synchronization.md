# ArgoCD: принцип работы и синхронизация

ArgoCD реализует GitOps-подход для Kubernetes: желаемое состояние описывается в Git, а кластер приводится к этому состоянию контроллером. Синхронизация — непрерывный процесс сравнения исходников (desired state) с реальными объектами в кластере (live state) и применения отличий с учётом политики.

## Компоненты, участвующие в синхронизации
*   API Server: интерфейс для UI/CLI и RBAC, хранение Application в Kubernetes.
*   Application Controller: цикл согласования; сравнение, вычисление диффа, запуск синхронизаций и ретраев.
*   Repo Server: клонирование репозиториев, рендеринг Helm/Kustomize/Plain YAML.
*   Application (CRD): декларативное описание источника, назначения и политики синка.
*   AppProject: границы доступа, окна синхронизации, ограничения по кластерам/неймспейсам/репозиториям.

## Цикл согласования
Контроллер периодически и по событиям (webhook из Git, изменение Application, ручной Refresh) обновляет кеш репозитория, рендерит манифесты и сравнивает их с live-объектами кластера. Вычисляются два независимых статуса: синхронизация (desired vs live) и здоровье (liveness/rollout готовность). При разрешённой политике auto ArgoCD применяет изменения, выполняет удаление дрейфующих ресурсов и повторяет до достижения консистентности или исчерпания лимита ретраев. Применение может использовать server-side apply, что улучшает мерджинг и детекцию конфликтов.

| Категория | Статус | Что означает |
| --- | --- | --- |
| Sync | Synced | Live совпадает с Git-манифестами |
| Sync | OutOfSync | Обнаружены отличия; требуется apply/prune |
| Health | Healthy | Объект готов (Ready/Available) |
| Health | Progressing | Идёт развёртывание/обновление |
| Health | Degraded | Ошибка, CrashLoopBackOff, неудачный rollout |
| Health | Missing | Объект отсутствует в кластере |

## Политики синхронизации
*   Manual: оператор инициирует sync вручную; безопасно для контролируемых релизов.
*   Automated: контроллер применяет изменения без участия оператора.
*   prune: удаляет ресурсы, исчезнувшие из Git.
*   selfHeal: пере-применяет дрейфующие live-объекты.
*   retry: экспоненциальные повторы при сбоях.
*   syncOptions: тонкая настройка применения (например, server-side apply, создание namespace).

Пример Application с автоматической синхронизацией и игнорированием несущественных различий:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.example.com/org/repo.git
    targetRevision: main
    path: k8s/demo
    helm:
      valueFiles:
        - values-prod.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: demo
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
      - ServerSideApply=true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/spec/containers/0/imagePullPolicy
```
## Порядок, хуки и окна
ArgoCD поддерживает упорядочивание через аннотацию sync-wave: ресурсы с меньшим значением применяются раньше, что полезно для CRD → CR → Deployments. Хуки (PreSync, Sync, PostSync, SyncFail) позволяют выполнять миграции, smoke-тесты и откаты; они обозначаются аннотациями на ресурсах и не попадают в live state после завершения при соответствующей политике удаления. AppProject может вводить окна синхронизации, ограничивая автоматические операции по времени или запрещая их для определённых приложений, что снижает риски вне рабочего окна.

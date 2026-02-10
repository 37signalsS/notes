# Настройка auto-sync в ArgoCD

Auto-sync — это автоматическое приведение кластера к состоянию, зафиксированному в Git для конкретного приложения. ArgoCD отслеживает ревизию источника и при появлении изменений инициирует синхронизацию без участия оператора. Такой режим уменьшает ручные действия и повышает согласованность окружений, но требует аккуратной настройки политики и ограничений.

## Включение и параметры auto-sync
Auto-sync активируется в манифесте Application через spec.syncPolicy.automated. Базовые параметры:
*   prune — автоматически удалять ресурсы, отсутствующие в Git.
*   selfHeal — устранять дрейф, возникший из-за ручных изменений в кластере.
*   allowEmpty — разрешать синхронизацию пустых результатов рендера (например, путь временно не содержит манифестов).

Пример Application с auto-sync и полезными опциями:
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
    path: k8s/demo
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
    namespace: demo
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - ApplyOutOfSyncOnly=true
    - RespectIgnoreDifferences=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```
Ключевые syncOptions:
*   CreateNamespace=true — создаёт namespace назначения.
*   ServerSideApply=true — устраняет конфликты патчинга и улучшает мерджинг.
*   ApplyOutOfSyncOnly=true — применяет только рассинхронизированные ресурсы.
*   RespectIgnoreDifferences=true — учитывает правила ignoreDifferences при сравнении.

Полезно задать targetRevision как тег или семвер-диапазон, например v1.2.* или v1.2.x, чтобы контролировать, какие релизы попадут в автосинк.

## Поведение при дрейфе и конфликтных изменениях
С включённым selfHeal ручные изменения в кластере будут автоматически откатываться к состоянию Git. Если это нежелательно для конкретных объектов, их можно пометить аннотациями:
*   argocd.argoproj.io/compare-options: IgnoreExtraneous — не считать объект «лишним».
*   argocd.argoproj.io/sync-options: Prune=false — не удалять объект при prune.

При сложных CRD и крупных манифестах ServerSideApply упрощает конвергенцию и уменьшает ошибки из-за конфликтов полей. Для ресурсоёмких апдейтов можно временно отключить prune или использовать replace-стратегии на уровне отдельных синков, однако в auto-sync разумнее тщательно выбирать окна и ревизии.

## Окна синхронизации и ограничения
Чтобы ограничить время автоприменения, используются окна синхронизации в AppProject: можно явно разрешать/запрещать auto-sync по расписанию в cron-формате.
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: prod
  namespace: argocd
spec:
  sourceRepos:
  - '*'
  destinations:
  - namespace: '*'
    server: https://kubernetes.default.svc
  syncWindows:
  - kind: allow
    schedule: "0 9-18 * * 1-5"   # каждый час с 09 до 18 по будням
    duration: 60m
    applications:
    - "prod-*"
    namespaces:
    - "*"
    timeZone: "Europe/Moscow"
  - kind: deny
    schedule: "0 0 25 12 *"      # 25 декабря
    duration: 24h
    applications:
    - "*"
```
В deny-окнах ArgoCD не будет выполнять авто-синхронизацию даже при новых коммитах. Это удобно для заморозки релизов, ночных периодов или регламентных работ.

## Практические нюансы эксплуатации
*   Включайте prune только после проверки, что «лишние» ресурсы не создаются сторонними контроллерами.
*   Для последовательного заказа применения используйте аннотации синк-волн (argocd.argoproj.io/sync-wave).
*   Настройте retry с экспоненциальным бэкоффом для временных сбоев кластера или зависимостей.
*   Журналируйте ревизии и события синхронизаций: это упрощает анализ регрессий при автоприменении.

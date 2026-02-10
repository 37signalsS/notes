# Webhook-и для уведомлений при обновлениях

Webhook — это исходящий HTTP-запрос, который система отправляет при наступлении события. В контексте GitOps это способ оповестить внешние системы о фактах синхронизации, обновления образов, смены статуса здоровья или дрейфа конфигурации. Такой канал хорошо подходит для интеграции с собственными порталами, чатами, системами инцидентов и аудитом, когда готовые интеграции не подходят.

## Когда полезны webhook-уведомления
*   Подтверждение успешного применения релиза и фиксация метаданных (коммит, образ, кластер, неймспейс).
*   Раннее оповещение о деградации здоровья приложения после автосинхронизации.
*   Отчеты об изменениях, внесенных Image Updater/Automation.
*   Трассировка и аудит: построение таймлайнов развертываний для соответствия требованиям.

## Argo CD: настройка webhook-сервиса уведомлений
В Argo CD уведомления реализуются через контроллер уведомлений с декларативной конфигурацией сервисов, шаблонов и триггеров. Для интеграции произвольного вебхука определяют сервис типа webhook и настраивают триггеры, которые его вызывают.

Пример минимальной конфигурации:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: argocd
type: Opaque
stringData:
  webhook-token: "s3cr3t-token"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.webhook.deploy: |
    url: https://hooks.example.com/deploy
    method: POST
    headers:
    - "Authorization: Bearer {{.secret.webhook-token}}"
    - "Content-Type: application/json"
  template.app-sync: |
    message: |
      {
        "app":"{{.app.metadata.name}}",
        "phase":"{{.app.status.operationState.phase}}",
        "health":"{{.app.status.health.status}}",
        "revision":"{{call .repo.GetRevision .app}}",
        "cluster":"{{.context.cluster}}"
      }
  trigger.on-sync-completed: |
    when: app.status.operationState.phase in ['Succeeded','Failed']
    send:
    - webhook.deploy
```
Подписка приложения на триггер выполняется аннотацией:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payments
  namespace: argocd
  annotations:
    notifications.argoproj.io/subscribe.webhook.deploy: on-sync-completed
```
Такой подход отправит JSON на указанный endpoint после завершения синхронизации приложения.

## Flux: отправка событий через notification-controller
В Flux за исходящие уведомления отвечает notification-controller. Настраиваются Provider (куда отправлять) и Alert (что отправлять и по каким источникам событий).
```yaml
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: outbound-webhook
  namespace: flux-system
spec:
  type: generic
  address: https://hooks.example.com/deploy
---
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: changes-to-webhook
  namespace: flux-system
spec:
  providerRef:
    name: outbound-webhook
  eventSeverity: info
  eventSources:
  - kind: Kustomization
    name: apps-*
  - kind: HelmRelease
    name: "*"
  eventMetadata:
    cluster: prod-eu
    team: core
```
При любых событиях у указанных объектов (включая успешные и неуспешные применений) контроллер отправит POST с данными о событии.

## Сравнение подходов
| Критерий | Argo CD | Flux |
| --- | --- | --- |
| Где настраивается | ConfigMap/Secret + аннотации Application | Provider/Alert CRD |
| Гранулярность | По триггерам и шаблонам, на уровне Application | По видам объектов и фильтрам событий |
| Формат полезной нагрузки | Гибкий шаблон (Go template) | Стандартизованный payload с metadata |
| Подписки | Аннотации, глобальные подписки | Alert охватывает список источников |
| Расширяемость | Пользовательские сервисы, каналы | Разные типы Provider, единый механизм |

## Надежность и безопасность
*   Подпишите запросы: добавляйте HMAC/Authorization заголовки и проверяйте их на стороне приемника.
*   Используйте TLS и ограничение источников (allow-list IP/сертификатов) на стороне сервера вебхука.
*   Закладывайте идемпотентность: передавайте eventID и обрабатывайте повторные доставки.
*   Учитывайте лимиты приемника: настраивайте ретраи и backoff в промежуточном прокси или используйте очередь.
*   Логируйте и кореллируйте события с релизами: включайте коммит, образ, кластер и namespace в полезную нагрузку.
